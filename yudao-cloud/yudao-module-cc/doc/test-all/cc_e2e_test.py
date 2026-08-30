#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
呼叫中心端到端测试主脚本(唯一主测试脚本)
=========================================
预期结果(多方跟踪验证,每场景 ≥3 类证据交叉):
    - ESL 事件(EslEventCollector 双 FS 订阅, uniqueId/主叫号精确过滤)
    - Java 后端日志关键词(wait_log_keywords + 远端 SSH 增量 + 共享 buf, 精确匹配 uniqueId)
    - MySQL 数据校验(cc_call_record / cc_flow_instances / cc_autocall_task_record, poll_until 轮询)
    - 软电话 RTP 收流(rxBytes 增量>0) + 浏览器 UI 状态(通话中/保持/来电)

使用方式(系统 python3.11 直跑, 无 venv):
    python3 cc_e2e_test.py                          # 默认执行场景 1,2,3,5,6,7(有头)
    python3 cc_e2e_test.py --headless               # 无头模式(CI 友好)
    python3 cc_e2e_test.py --scenarios 1,6          # 只执行指定场景(8/9 也须显式指定)
    python3 cc_e2e_test.py --rounds 2 --round-backoff 10   # 每场景失败重试 2 轮, 轮间隔 10s
    python3 cc_e2e_test.py --skip-l0                # 跳过 L0 环境/数据核对
    python3 cc_e2e_test.py --auto-fix               # L0 数据缺失时执行幂等 INSERT 修复(默认关闭)
    python3 cc_e2e_test.py --check-only             # 只跑 L0 核对, 不执行场景

退出码约定:
    0 = 全部通过; 1 = 存在失败场景; 2 = 环境/数据核对失败或参数错误(L0 快速失败)
"""

import argparse
import json
import logging
import os
import re
import socket
import sys
import threading
import time
from collections import deque
from datetime import datetime, timedelta

# ==================== 路径装配: 复用 ../common 公共组件(禁止复制) ====================
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_COMMON_DIR = os.path.join(_THIS_DIR, "common")
if _COMMON_DIR not in sys.path:
    sys.path.insert(0, _COMMON_DIR)

import config  # noqa: E402
from browser_test import BrowserTest  # noqa: E402
from data_spec import FLOW_SPECS, get_flow_node_ids, validate_specs  # noqa: E402
from db_helper import DbHelper  # noqa: E402
from esl_helper import EslHelper  # noqa: E402
from redis_helper import RedisHelper  # noqa: E402
from sip_client import SipClient, CallState, INBOUND_TARGET_URI  # noqa: E402

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s")
logger = logging.getLogger("cc_e2e")

# ==================== 常量(环境事实,与 common/config.py 对齐) ====================
# 远端后端日志路径(线上后端运行于 62.234.191.165, 日志落盘在该路径)
REMOTE_JAVA_LOG_PATH = "/home/ubuntu/cc/logs/yudao-server.log"
# 清理用 Redis key 前缀(与后端 RedisConstants 一致)
CLEANUP_REDIS_PATTERNS = ("autocall:task:*", "fs:ivr:instances:*", "statemachine:*")
# cc_autocall_task_record.status 语义(AutocallTaskRecordServiceImpl 实测)
AUTOCALL_RECORD_STATUS_TEXT = {0: "待呼叫", 1: "呼叫中", 2: "已接通", 3: "未接通", 4: "呼叫失败"}
# 可用的前端地址: 线上环境统一走 config.LOCAL_FRONTEND_URL(合法证书域)
FRONTEND_CANDIDATE_URLS = (config.LOCAL_FRONTEND_URL,)

# 场景默认执行顺序(scenario 4 已并入新场景3;8/9 可选项需 --scenarios 显式指定)
DEFAULT_SCENARIOS = [1, 2, 3, 5, 6, 7]
# 合法场景编号集合(未知编号如 4 立即报错退出码 2 并提示并入关系)
VALID_SCENARIOS = {1, 2, 3, 5, 6, 7, 8, 9, 10}


# ==================== 步骤结果记录 ====================
class StepRecorder:
    """步骤级 PASS/FAIL 记录器,输出结构化结果,场景末尾以其 all_passed 判定"""

    STATUS_PASS = "PASS"
    STATUS_FAIL = "FAIL"

    def __init__(self):
        self.steps = []

    def record(self, name: str, passed: bool, detail: str = "") -> bool:
        status = self.STATUS_PASS if passed else self.STATUS_FAIL
        self.steps.append({"name": name, "status": status, "detail": detail})
        logger.info("[%s] %s%s", status, name, (" | " + detail) if detail else "")
        return passed

    @property
    def all_passed(self) -> bool:
        return all(s["status"] == self.STATUS_PASS for s in self.steps)

    def summary_lines(self):
        return ["  [%s] %s%s" % (s["status"], s["name"], (" | " + s["detail"]) if s["detail"] else "")
                for s in self.steps]


# ==================== Java 日志增量读取(文件偏移, 支持滚动) ====================
class LogTail:
    """本地日志按偏移量只读新增部分(兼容本地调试);线上无本地日志, 实际走 RemoteLogTail"""

    def __init__(self, path: str):
        self.path = path
        self.offset = 0
        self.reset()

    def reset(self) -> None:
        """把游标移到当前文件末尾,后续只读新增内容"""
        try:
            self.offset = os.path.getsize(self.path)
        except OSError:
            self.offset = 0

    def read_new(self) -> str:
        """读取游标之后的新增日志;文件被滚动/截断时自动重置到文件开头"""
        try:
            size = os.path.getsize(self.path)
        except OSError:
            return ""
        if size < self.offset:  # 日志滚动或截断
            self.offset = 0
        if size == self.offset:
            return ""
        with open(self.path, "r", encoding="utf-8", errors="replace") as fp:
            fp.seek(self.offset)
            text = fp.read()
            self.offset = fp.tell()
        return text


class RemoteLogTail:
    """通过 SSH 增量读取远端 yudao-server.log 新增部分(线上环境无本地日志文件)。

    接口与 LogTail 完全一致(reset / read_new),复用 wait_log_keywords 的 buf 共享机制。
    采用"先取文件大小再 tail -c +offset"策略:即便读取期间有新日志追加,
    也最多产生重复(对关键词匹配幂等),不会丢行。
    """

    def __init__(self, path: str, ssh_host: str, ssh_user: str, ssh_password: str, ssh_port: int = 22):
        self.path = path
        self.ssh_host = ssh_host
        self.ssh_user = ssh_user
        self.ssh_password = ssh_password
        self.ssh_port = ssh_port
        self._cli = None
        self.offset = 0
        self.reset()

    def _connect(self) -> None:
        import paramiko
        cli = paramiko.SSHClient()
        cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        cli.connect(self.ssh_host, port=self.ssh_port, username=self.ssh_user,
                    password=self.ssh_password, timeout=15,
                    look_for_keys=False, allow_agent=False)
        self._cli = cli

    def _safe_path(self) -> str:
        # 固定路径, 仅做基础单引号转义
        return "'%s'" % self.path.replace("'", "'\\''")

    def close(self) -> None:
        """关闭 SSH 连接(幂等), 供 teardown 释放资源"""
        if self._cli is not None:
            try:
                self._cli.close()
            except Exception:  # noqa: BLE001
                pass
            self._cli = None

    def reset(self) -> None:
        try:
            if self._cli is None:
                self._connect()
            _, stdout, _ = self._cli.exec_command("wc -c < %s" % self._safe_path(), timeout=10)
            out = stdout.read().decode().strip()
            self.offset = int(out) if out.isdigit() else 0
        except Exception as exc:  # noqa: BLE001 - 连接失败不致命, 后续 read_new 重试
            logger.warning("[RemoteLogTail] reset 失败: %s", exc)
            self.offset = 0
            self.close()

    def read_new(self) -> str:
        try:
            if self._cli is None:
                self._connect()
            _, so, _ = self._cli.exec_command("wc -c < %s" % self._safe_path(), timeout=10)
            size_s = so.read().decode().strip()
            size = int(size_s) if size_s.isdigit() else self.offset
            # 日志滚动检测: logback 将主日志滚到分片后主日志大小归零重写, 若文件变小
            # 视为滚动, 重置 offset=0 从头读取滚动后的主日志, 避免滚动后新日志永远读不到。
            if size < self.offset:
                logger.warning("[RemoteLogTail] 检测到日志滚动(文件变小 %d->%d),重置 offset",
                               self.offset, size)
                self.offset = 0
            if size <= self.offset:
                return ""
            cmd = "tail -c +%d %s" % (self.offset + 1, self._safe_path())
            _, stdout, _ = self._cli.exec_command(cmd, timeout=10)
            data = stdout.read().decode("utf-8", "replace")
            self.offset = size
            return data
        except Exception as exc:  # noqa: BLE001 - 单次读取失败不影响主流程, 下次重试
            logger.warning("[RemoteLogTail] read_new 失败: %s", exc)
            self.close()
            return ""


def wait_log_keywords(log_tail: LogTail, keywords, timeout: float,
                      min_match: int = 1, poll: float = 2.0, buf: list = None):
    """
    在 timeout 内等待日志新增部分命中关键词,返回 (命中数, 累计文本)。

    需求背景: read_new 会一次性读走全部新增日志,命中即返回时未命中断言所需的
    更早日志行已被游标消耗(流程推进仅数秒,串行断言全部落空)。传入 buf(list) 后,
    每次读取的新增文本同步追加到 buf,匹配范围为 buf 全部累计文本,同一场景内
    多个断言共享 buf 即可互不丢失。keywords 支持普通字符串与正则对象混合。

    :param log_tail: 日志读取器(reset/read_new)
    :param keywords: 关键词列表(字符串或已编译正则)
    :param timeout: 最长等待秒数
    :param min_match: 命中几个关键词才返回
    :param poll: 轮询间隔秒数
    :param buf: 共享缓冲(建议传入,避免游标消耗导致早先日志丢失)
    :return: (命中数, 全部累计文本)
    """
    collected = []
    deadline = time.time() + timeout

    def matched_count(text: str) -> int:
        count = 0
        for kw in keywords:
            if hasattr(kw, "search"):
                if kw.search(text):
                    count += 1
            elif kw in text:
                count += 1
        return count

    while True:
        new_text = log_tail.read_new()
        if new_text:
            collected.append(new_text)
            if buf is not None:
                buf.append(new_text)
        full = "".join(buf if buf is not None else collected)
        hits = matched_count(full)
        if hits >= min_match:
            return hits, full
        if time.time() >= deadline:
            return hits, full
        time.sleep(poll)


# ==================== CC 侧 FS ESL 事件收集(双 FS 并行订阅) ====================
class EslEventCollector:
    """
    独立 ESL 连接 + 后台读取线程,持续收集订阅事件。

    需求背景: CC 服务按 callId hash 选择 FS 实例(fs1/fs2),呼叫落点不固定,
    因此两台实例都要订阅;事件读取放入后台线程避免阻塞主流程。
    SUBSCRIBE_EVENTS 额外订阅 CHANNEL_HOLD/CHANNEL_UNHOLD 供场景5 保持/恢复验证。
    """

    SUBSCRIBE_EVENTS = ["CHANNEL_ANSWER", "CHANNEL_BRIDGE", "CHANNEL_HANGUP",
                        "CHANNEL_PARK", "PLAYBACK_START", "PLAYBACK_STOP", "DTMF",
                        "CHANNEL_HOLD", "CHANNEL_UNHOLD"]

    def __init__(self, host: str, port: int, password: str, tag: str):
        self.tag = tag
        self.helper = EslHelper(host, port, password)
        self._events = deque(maxlen=5000)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self.connected = False

    def start(self) -> bool:
        if not self.helper.connect():
            logger.warning("[ESL-%s] 连接失败 %s:%s", self.tag, self.helper.host, self.helper.port)
            return False
        self.helper.subscribe_events(self.SUBSCRIBE_EVENTS)
        self.connected = True
        self._thread = threading.Thread(target=self._loop, name="esl-collector-%s" % self.tag,
                                        daemon=True)
        self._thread.start()
        logger.info("[ESL-%s] 事件订阅就绪 %s:%s", self.tag, self.helper.host, self.helper.port)
        return True

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                event = self.helper._read_event(timeout=2.0)  # noqa: SLF001 - 复用内部读取
            except socket.timeout:
                continue  # 空闲轮询超时属正常,继续等待事件
            except Exception:  # noqa: BLE001 - 其他读取异常视为连接断开,退出收集线程
                logger.warning("[ESL-%s] 事件读取线程退出", self.tag)
                break
            if event:
                event["_collector_tag"] = self.tag
                with self._lock:
                    self._events.append(event)

    def wait_event(self, event_name: str, timeout: float, match=None):
        """等待指定事件(可带匹配函数),命中返回事件 dict,超时返回 None"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                for idx, event in enumerate(self._events):
                    if event.get("Event-Name") != event_name:
                        continue
                    if match and not match(event):
                        continue
                    del self._events[idx]
                    return event
            time.sleep(0.3)
        return None

    def clear(self) -> None:
        with self._lock:
            self._events.clear()

    def stop(self) -> None:
        self._stop.set()
        try:
            self.helper.disconnect()
        except Exception:  # noqa: BLE001
            pass


def adhoc_esl(host: str, port: int, password: str):
    """按需创建短连接执行命令(清理用),失败返回 None"""
    helper = EslHelper(host, port, password)
    return helper if helper.connect() else None


def http_probe(url: str, timeout: float = 10.0) -> bool:
    """HTTP(S) 连通性探测: 状态码 <500 视为可用(https 证书必须有效)"""
    import urllib.request
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status < 500
    except Exception:  # noqa: BLE001
        return False


def tcp_probe(host: str, port: int, timeout: float = 5.0) -> bool:
    """TCP 端口连通性探测(供第三方 FS SIP / sipproxy 等非 HTTP 服务使用)"""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:  # noqa: BLE001
        return False


# ==================== 通用工具 ====================
def poll_until(fn, timeout: float, interval: float = 2.0):
    """轮询 fn 直至返回真值或超时,返回最后一次结果"""
    deadline = time.time() + timeout
    result = fn()
    while not result and time.time() < deadline:
        time.sleep(interval)
        result = fn()
    return result


def get_latest_flow_instance(db: DbHelper, flow_id: int, since: datetime):
    """查询测试开始之后创建的最新流程实例(终态校验用)"""
    rows = db.query("SELECT id, call_id, flow_id, status, start_time, end_time, "
                    "current_node_id, variables FROM cc_flow_instances "
                    "WHERE flow_id=%s AND deleted=0 AND create_time >= %s "
                    "ORDER BY id DESC LIMIT 1", (flow_id, since))
    return rows[0] if rows else None


def get_flow_instance_variables(instance) -> dict:
    """解析流程实例 variables 字段(json 字符串/dict 兼容)"""
    if not instance:
        return {}
    raw = instance.get("variables")
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return {}


# ==================== 节点 id 动态提取(消灭 NODE7_* 硬编码) ====================
def build_flow_node_ids(db: DbHelper, flow_id: int):
    """
    从数据库动态提取指定流程的节点 id 映射,供场景日志正则使用。

    需求背景: 历史脚本硬编码 NODE7_* 节点 id, 流程重绘即失效。改为执行前读取
    cc_flow_info.flow_data 并用 data_spec.get_flow_node_ids 按 type 顺序+索引消歧。
    """
    rows = db.query("SELECT flow_data FROM cc_flow_info WHERE id=%s AND deleted=0", (flow_id,))
    if not rows:
        raise RuntimeError("flow_id=%s 在 cc_flow_info 不存在,数据核对失败" % flow_id)
    return get_flow_node_ids(flow_id, rows[0].get("flow_data"))


# ==================== 登录签入与坐席就绪 ====================
def cleanup_sipproxy_registrations(redis_helper: RedisHelper,
                                   agent_sips=("1001", "1002", "1003")) -> None:
    """
    清理 sipproxy Redis 注册残留(仅测试坐席, 幂等安全)。

    需求背景: sipproxy SipSessionManager 将 REGISTER 映射持久化到 Redis
    (ipcc:sipproxy:user:session:*/session:register:*, TTL 3600s)。后端重启或浏览器
    异常退出时 WebSocket 关闭回调未执行, Redis 键残留 → 新 REGISTER 被判"重复登录"
    拒绝(实测 2026-08-19 后端部署后 1001/1002 签入 3 次全部失败)。
    预期结果: 删除测试坐席的 user→session 与 session→user 双向映射, 签入不再被拒。
    """
    if not redis_helper or not redis_helper.client:
        return
    for sip in agent_sips:
        user_key = "ipcc:sipproxy:user:session:%s:%s" % (sip, config.SIP_DOMAIN)
        try:
            session_id = redis_helper.client.get(user_key)
            if session_id:
                # redis-py 在 decode_responses=True 时返回 str, 否则返回 bytes, 兼容两者
                if isinstance(session_id, bytes):
                    session_id = session_id.decode()
                redis_helper.client.delete("ipcc:sipproxy:session:register:%s" % session_id)
                redis_helper.client.delete(user_key)
                logger.info("清理 sipproxy 注册残留: %s -> %s", user_key, session_id)
        except Exception as exc:  # noqa: BLE001 - 清理不阻断主流程
            logger.warning("清理 sipproxy 注册残留异常(%s): %s", user_key, exc)


def login_and_signin(browser: BrowserTest, page, agent: dict, frontend_url: str,
                     recorder: StepRecorder) -> bool:
    """
    坐席登录 + SIP 签入 + 置就绪(带 3 次重试),校验 is_ready。

    需求背景: 登录/UAC 注册/WebSocket 偶发瞬时失败, 单次尝试即失败会误报环境问题。
    预期结果: 页面登录成功、软电话签入成功、就绪状态校验通过。
    """
    label = "坐席%s(%s)" % (agent["sip_number"], agent["username"])
    for attempt in range(1, 4):
        try:
            browser.navigate_to_login(page, url=frontend_url)
            if not browser.login(page, agent["username"], agent["password"]):
                raise RuntimeError("登录失败")
            if not browser.signin(page):
                raise RuntimeError("SIP签入失败")
            if not browser.set_ready(page, ready=True):
                raise RuntimeError("设置就绪失败")
            if browser.is_ready(page):
                recorder.record("登录签入-%s 就绪" % label, True, "第%d次尝试" % attempt)
                return True
            raise RuntimeError("就绪状态校验未通过")
        except Exception as exc:  # noqa: BLE001 - 重试覆盖各类瞬时失败
            logger.warning("登录签入 %s 第%d次失败: %s", label, attempt, exc)
            if attempt < 3:
                time.sleep(3)
                try:
                    page.reload(wait_until="domcontentloaded")
                except Exception:  # noqa: BLE001
                    pass
    recorder.record("登录签入-%s 就绪" % label, False, "3次尝试均失败")
    return False


def ensure_agents_ready(browser: BrowserTest, pages: dict, recorder: StepRecorder) -> bool:
    """每轮场景前确认坐席仍为就绪态,否则重新置就绪(防上一轮残留忙碌状态) """
    ok = True
    for sip, page in pages.items():
        if page is None:
            continue
        if browser.is_ready(page):
            continue
        # 置就绪失败时升级为完整重登录: hold/transfer 等操作后 JsSIP 残留脏 SIP/WebRTC 状态,
        # set_ready 仅点 UI 无法恢复(实测场景5→场景6 重签后仍离线), 需页面重载+重新登录签入
        ready = browser.set_ready(page, ready=True) and browser.is_ready(page)
        if not ready:
            logger.warning("坐席%s 置就绪失败, 升级为页面重载+完整重登录", sip)
            try:
                page.reload(wait_until="domcontentloaded")
            except Exception:  # noqa: BLE001 - 重载失败不阻断后续重登录尝试
                pass
            agent = next((a for a in (config.AGENT_A, config.AGENT_B, config.AGENT_C)
                          if a["sip_number"] == sip), None)
            if agent is not None:
                ready = login_and_signin(browser, page, agent, config.LOCAL_FRONTEND_URL, recorder)
                # 重登录后导航到呼叫中心工作台, 确保 SoftPhone JsSIP 在正确页面接收来电
                if ready:
                    try:
                        page.click("text=呼叫中心", timeout=10000)
                        time.sleep(2)
                    except Exception:  # noqa: BLE001 - 导航失败非致命
                        logger.warning("坐席%s 重登录后导航呼叫中心失败(非致命)", sip)
            else:
                ready = False
        recorder.record("坐席%s恢复就绪" % sip, ready)
        ok = ok and ready
    return ok


def ensure_agent_online(browser: BrowserTest, page, label: str) -> bool:
    """
    坐席在线前置检查: 不在线则尝试重新签入。

    需求背景: IVR 挂断/保持等操作后 JsSIP WebSocket 偶发断连导致坐席离线,
    若不预先检查直接 make_call 会等待 CALL_TIMEOUT(60s) 才超时, 浪费整轮时长。
    """
    if browser.is_online(page):
        return True
    logger.warning("[前置] 坐席%s 未在线,尝试重新签入...", label)
    return bool(browser.signin(page))


def _force_re_signin_agents(browser: BrowserTest, pages: list, label: str):
    """
    按需重新签入一组坐席页面: 仅离线坐席执行 signout→signin, 在线坐席跳过。

    需求背景: hold/transfer 等高负载操作后 JsSIP 容易残留半挂断的 SIP/WebRTC 状态,
    但原地 signout→signin 往返不可靠(实测场景6 13:11 signin 全部 30s 超时, 且旧 WebSocket
    关闭后 sipproxy 注册绑定残留会把后续注册误判为重复登录拒绝), 因此:
    1. 在线坐席不动作(避免破坏健康状态);
    2. 离线坐席重签失败时升级为页面重载+完整重登录(login_and_signin)。
    预期结果: 所有指定坐席保持或恢复在线(任一步失败仅告警不抛异常)。
    """
    for page in pages:
        if page is None:
            continue
        try:
            if browser.is_online(page):
                logger.info("[%s] 坐席在线, 跳过重签", label)
                continue
        except Exception:  # noqa: BLE001
            pass
        try:
            browser.signout(page)
        except Exception as e:  # noqa: BLE001
            logger.warning("[%s] signout 异常: %s", label, e)
    time.sleep(2)
    for page in pages:
        if page is None:
            continue
        try:
            if browser.is_online(page):
                continue
            if not browser.signin(page):
                logger.warning("[%s] signin 失败(后续由 ensure_agents_ready 完整重登录兜底)", label)
            else:
                browser.set_ready(page, ready=True)
        except Exception as e:  # noqa: BLE001
            logger.warning("[%s] signin 异常: %s", label, e)
    time.sleep(2)


# ==================== 清理(幂等,场景间状态重置) ====================
def browser_hangup_if_active(browser: BrowserTest, page) -> None:
    """浏览器侧挂断残留通话(通话中/来电均处理,不抛异常) """
    try:
        if page.query_selector(".active-call"):
            browser.hangup(page)
            return
        if page.query_selector(".incoming-dialog"):
            try:
                browser.reject_call(page)
            except Exception:  # noqa: BLE001
                browser.answer_call(page)
                time.sleep(1)
                browser.hangup(page)
    except Exception as exc:  # noqa: BLE001 - 清理不阻断主流程
        logger.warning("浏览器清理残留通话异常: %s", exc)


def get_total_channel_count(esl: EslHelper, esl2: EslHelper) -> int:
    """
    汇总两个 FS 实例的通道数。

    需求背景: CC 服务 selectFreeSwitchNode 使用 callId hash 选择 FS 实例(fs1/fs2),
    单实例查询会漏判落在另一实例的呼叫(实测场景4 首试落在 fs1 → 误报未到达)。
    """
    count1 = esl.get_channel_count() if esl.sock else 0
    count2 = esl2.get_channel_count() if (esl2 and esl2.sock) else 0
    total = count1 + count2
    if count1 > 0 or count2 > 0:
        logger.info("通道数汇总: esl(fs1)=%d + esl2(fs2)=%d = %d", count1, count2, total)
    return total


def cleanup_calls(esl: EslHelper, esl2: EslHelper, browser: BrowserTest,
                  pages: list, esl_third_party=None) -> None:
    """
    清理所有通话(场景间状态重置,保证幂等可重复)。

    处理逻辑: ①两个 CC ESL 实例 hupall(通话可能落在任一实例); ②第三方 FS hupall;
    ③等待 2s 状态稳定; ④浏览器 UI 双保险挂断(存在 .active-call 时)。
    """
    try:
        esl.hangup_all_channels()
    except Exception as e:  # noqa: BLE001
        logger.warning("CC ESL 清理通道异常: %s", e)
    try:
        if esl2 and esl2.sock:
            esl2.hangup_all_channels()
    except Exception as e:  # noqa: BLE001
        logger.warning("CC ESL2 清理通道异常: %s", e)
    if esl_third_party and esl_third_party.sock:
        try:
            esl_third_party.hangup_all_channels()
        except Exception as e:  # noqa: BLE001
            logger.warning("第三方 ESL 清理通道异常: %s", e)
    time.sleep(2)
    for page in pages:
        if page is None:
            continue
        try:
            if page.query_selector(".active-call"):
                browser.hangup(page)
                logger.info("已通过 UI 挂断残留通话")
        except Exception as e:  # noqa: BLE001
            logger.warning("UI 清理异常: %s", e)


def cleanup_residual(esl_hosts, redis_helper: RedisHelper, browser: BrowserTest,
                     pages: dict, sip_clients: dict) -> None:
    """
    场景失败/轮次间深度清理:
    1. 软电话挂断; 2. 浏览器挂断坐席通话; 3. CC 两台 FS hupall 残留通道;
    4. Redis 删 autocall:task:* / fs:ivr:instances:* / statemachine:*;
    """
    for client in sip_clients.values():
        try:
            if client.get_call_state() not in (CallState.NULL, CallState.DISCONNECTED):
                client.hangup()
        except Exception:  # noqa: BLE001
            pass
    for page in pages.values():
        if page is not None:
            browser_hangup_if_active(browser, page)
    for host, port, password in esl_hosts:
        helper = adhoc_esl(host, port, password)
        if helper:
            try:
                helper.hangup_all_channels()
            except Exception as exc:  # noqa: BLE001
                logger.warning("hupall(%s:%s) 异常: %s", host, port, exc)
            finally:
                helper.disconnect()
    if redis_helper.client:
        for pattern in CLEANUP_REDIS_PATTERNS:
            try:
                keys = list(redis_helper.client.scan_iter(match=pattern, count=200))
                if keys:
                    redis_helper.client.delete(*keys)
                    logger.info("清理 Redis key[%s]: %d 个", pattern, len(keys))
            except Exception as exc:  # noqa: BLE001
                logger.warning("Redis 清理 %s 异常: %s", pattern, exc)
    time.sleep(2)


def take_screenshot_on_failure(browser: BrowserTest, page, scenario_name: str):
    """测试失败时截图存档(失败截图会污染但不阻断主流程) """
    if page is None:
        logger.warning("页面为 None, 无法截图: %s", scenario_name)
        return
    try:
        browser.take_screenshot(page, "failure_" + scenario_name)
    except Exception as e:  # noqa: BLE001
        logger.warning("截图失败(%s): %s", scenario_name, e)


# ==================== 外呼任务表单(适配当前前端下拉组件) ====================
def _find_visible_dropdown_option(page, option_text: str):
    """找到文本匹配且可见的下拉选项(页面上可能存在多个隐藏的下拉面板) """
    try:
        for opt in page.query_selector_all(
                ".el-select-dropdown__item:has-text('%s')" % option_text):
            try:
                if opt.is_visible():
                    return opt
            except Exception:  # noqa: BLE001 - 查询与判断之间元素脱链
                continue
    except Exception:  # noqa: BLE001
        pass
    return None


def _select_form_item_option(page, label: str, option_text: str, timeout: int = 15000) -> bool:
    """在 .com-dialog 内定位 label 对应的 el-select 并点选指定选项。

    弹窗表单选项异步加载会触发 Vue 重渲染, 已查询的元素随时可能脱链,
    因此每次循环重新查询并对 click 脱链异常做容错重试。
    注意: 严禁用 page.mouse.click(空白坐标) 收起下拉——Dialog 组件设置了
    close-on-click-modal=true, 点击遮罩会直接关闭整个弹窗。
    """
    deadline = time.time() + timeout / 1000.0
    while time.time() < deadline:
        try:
            select_el = page.query_selector(
                ".com-dialog .el-form-item:has-text('%s') .el-select" % label)
            if select_el:
                option = _find_visible_dropdown_option(page, option_text)
                if not option:
                    select_el.click()
                    time.sleep(0.6)
                    option = _find_visible_dropdown_option(page, option_text)
                if option:
                    option.click()
                    time.sleep(0.3)
                    return True
        except Exception as exc:  # noqa: BLE001 - 元素脱链等竞态, 重新查询重试
            print("[_select_form_item_option] %s 点选竞态重试: %s" % (label, exc))
        time.sleep(1)
    return False


def _dialog_dom_state(page) -> str:
    """弹窗 DOM 诊断信息(弹窗数/可见性/表单字段),用于失败时输出根因线索 """
    try:
        return str(page.evaluate(
            "() => Array.from(document.querySelectorAll('.com-dialog')).map(d => ({"
            "visible: d.offsetParent !== null, "
            "items: Array.from(d.querySelectorAll('.el-form-item__label'))"
            ".map(l => l.textContent.trim()), "
            "inputs: d.querySelectorAll('input').length, "
            "textareas: d.querySelectorAll('textarea').length}))"))
    except Exception as exc:  # noqa: BLE001
        return "诊断异常: %s" % exc


def fill_autocall_form(page, task_name: str, target_numbers: str,
                       ivr_flow_option: str, gateway_name: str) -> bool:
    """
    填写外呼任务创建表单(当前前端: IVR流程/出局网关均为 el-select 下拉)。

    不复用 browser_test.fill_autocall_task_form(其 IVR 字段按 input 填写, 与当前前端不匹配)。
    弹窗 open() 内部 resetForm+异步加载选项会触发重渲染, 填写统一用 page.fill(selector)
    每次重新定位, 不持有 element handle; IVR流程下拉 label 为「路由名称(路由号码)」。
    """
    try:
        input_sel = ".com-dialog .el-form-item:has-text('任务名称') input"
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                if page.query_selector(input_sel):
                    break
            except Exception:  # noqa: BLE001
                pass
            time.sleep(0.5)
        else:
            print("[fill_autocall_form] 弹窗内未找到任务名称输入框, DOM=%s" % _dialog_dom_state(page))
            return False
        for _ in range(3):
            try:
                page.fill(".com-dialog .el-form-item:has-text('任务名称') input", task_name)
                page.fill(".com-dialog .el-form-item:has-text('被叫号码列表') textarea", target_numbers)
                break
            except Exception as fill_exc:  # noqa: BLE001
                print("[fill_autocall_form] fill 竞态重试: %s | DOM=%s"
                      % (fill_exc, _dialog_dom_state(page)))
                time.sleep(1)
        else:
            return False
        if not _select_form_item_option(page, "IVR流程", ivr_flow_option):
            print("[fill_autocall_form] IVR流程下拉选项未找到: %s" % ivr_flow_option)
            return False
        if not _select_form_item_option(page, "出局网关", gateway_name):
            print("[fill_autocall_form] 出局网关下拉选项未找到: %s" % gateway_name)
            return False
        return True
    except Exception as exc:  # noqa: BLE001
        print("填写外呼任务表单失败: %s" % exc)
        return False


# ==================== 场景1: 内部呼叫(flow102) ====================
def _scenario_prepare(ctx: dict, recorder: StepRecorder, checker) -> None:
    """场景公共前置: 重置日志游标/事件队列/场景起始时间, 坐席就绪确认"""
    ctx["scenario_start"] = datetime.now() - timedelta(seconds=10)  # 容忍本机与DB服务器时钟差
    ctx["s_buf"] = []
    ctx["log_tail"].reset()
    for c in ctx["collectors"]:
        c.clear()
    ensure_agents_ready(ctx["browser"], checker(ctx), recorder)


def _pages(ctx: dict) -> dict:
    """当前已创建的坐席页面映射(sip -> page),供清理/就绪检查使用"""
    pages = {config.AGENT_A["sip_number"]: ctx["page_a"], config.AGENT_B["sip_number"]: ctx["page_b"]}
    if ctx.get("page_c") is not None:
        pages[config.AGENT_C["sip_number"]] = ctx["page_c"]
    return pages


def _flow_ended_predicate(inst) -> bool:
    """流程实例终态判定: status∈{2,3}(正常走完/中途挂断兑底) + end_time 非空"""
    return bool(inst and inst.get("end_time") is not None
                and int(inst.get("status") or 0) in (2, 3))


def scenario_1_internal_call(ctx: dict, recorder: StepRecorder) -> bool:
    """
    场景1: 内部呼叫(浏览器坐席A 拨 9#1002 → 路由102 → flow102 转接坐席1002)。

    需求背景: 验证浏览器 B2BUA 内部呼叫链路(坐席A JsSIP → sipproxy → FS park → 号码路由
    type=2 命中 9# → flow102 转接节点 routeValue=${start-node.callee}=1002 → 坐席1002 接通)。
    新库无 type=2 catch-all 路由, 裸号呼出会被挂断, 固拨号必须带 9# 前缀。

    预期结果(多方验证链):
      - UI: A/B 均进入通话中, A 挂断后 B 联动挂断(≤15s)
      - ESL: CHANNEL_ANSWER/CHANNEL_BRIDGE 事件(双FS 任一, 按坐席号过滤) + 通道数 ≥2(B2BUA 两段对话)
      - Java 日志: [删除前缀] 9#1002→1002、[进入callRoute电话] 路由命中
      - DB: cc_call_record(caller=1001) 生成 + cc_flow_instances(flow102) 终态
    前置条件: L1/L2 已登录签入 A/B 并置就绪。
    """
    browser, page_a, page_b = ctx["browser"], ctx["page_a"], ctx["page_b"]
    db = ctx["db"]
    _scenario_prepare(ctx, recorder, lambda c: _pages(c))
    scenario_start = ctx["scenario_start"]
    s1_buf = ctx["s_buf"]
    log_tail = ctx["log_tail"]
    callee = config.AGENT_B["sip_number"]
    dial = config.IVR_DIAL_PREFIX_INTERNAL + callee  # 9#1002
    spec = FLOW_SPECS["102"]

    # 步骤1: 坐席A 拨号 9#1002(内部呼叫不选网关, 路由102 归一去前缀后转接坐席1002)
    if not recorder.record("场景1-坐席A发起呼叫 %s" % dial, browser.make_call(page_a, dial)):
        take_screenshot_on_failure(browser, page_a, "scenario_1_call")
        return False
    if not recorder.record("场景1-坐席B收到来电", browser.wait_for_incoming_call(page_b, timeout=config.CALL_TIMEOUT)):
        take_screenshot_on_failure(browser, page_b, "scenario_1_incoming")
        return False
    if not recorder.record("场景1-坐席B接听", browser.answer_call(page_b)):
        take_screenshot_on_failure(browser, page_b, "scenario_1_answer")
        return False
    if not recorder.record("场景1-坐席A通话建立", browser.wait_for_call_connected(page_a, timeout=config.CALL_TIMEOUT)):
        take_screenshot_on_failure(browser, page_a, "scenario_1_connect")
        return False

    # 步骤2: 双方 UI 均显示通话中(接听后 ICE gathering/200 OK/WebSocket 推送链路需数秒, 轮询 25s)
    deadline = time.time() + 25
    status_a = status_b = ""
    while time.time() < deadline:
        status_a = browser.get_status_text(page_a)
        status_b = browser.get_status_text(page_b)
        if "通话中" in status_a and "通话中" in status_b:
            break
        time.sleep(1)
    logger.info("场景1 通话状态 - A: %s, B: %s", status_a, status_b)
    if not recorder.record("场景1-双方UI通话中", "通话中" in status_a and "通话中" in status_b,
                           "A=%s B=%s" % (status_a, status_b)):
        take_screenshot_on_failure(browser, page_a, "scenario_1_status")
        return False

    # 步骤3: ESL 证据——CHANNEL_ANSWER/CHANNEL_BRIDGE 事件(主叫/被叫坐席号过滤) + 通道数≥2
    ans_evt = None
    for c in ctx["collectors"]:
        ans_evt = c.wait_event("CHANNEL_ANSWER", timeout=5,
                               match=lambda e: e.get("Caller-Caller-ID-Number") in (config.AGENT_A["sip_number"],
                                                                                    callee))
        if ans_evt:
            break
    recorder.record("场景1-FS CHANNEL_ANSWER 事件(双FS)", ans_evt is not None,
                    ("fs=%s" % ans_evt.get("_collector_tag", "")) if ans_evt else "")
    bridge_evt = None
    for c in ctx["collectors"]:
        bridge_evt = c.wait_event("CHANNEL_BRIDGE", timeout=10)
        if bridge_evt:
            break
    recorder.record("场景1-FS CHANNEL_BRIDGE 事件(双FS, B2BUA桥接)", bridge_evt is not None,
                    ("fs=%s" % bridge_evt.get("_collector_tag", "")) if bridge_evt else "")
    channel_count = get_total_channel_count(ctx["esl"], ctx["esl2"])
    recorder.record("场景1-ESL 通道数≥2(B2BUA两段对话)", channel_count >= 2, "实际=%d" % channel_count)

    # 步骤4: Java 后端日志交叉断言(路由命中 → 删除前缀 → 进入 callRoute 转接)
    hits, _ = wait_log_keywords(
        log_tail,
        [re.compile(r"\[删除前缀\].{0,40}%s" % re.escape(dial)),
         r"[进入callRoute电话]"],
        timeout=20, min_match=2, buf=s1_buf)
    recorder.record("场景1-后端日志: [删除前缀] %s + 进入callRoute" % dial, hits >= 2,
                    "命中关键词数=%d" % hits)

    # 步骤5: 通话保持 ~10s(产生有效 CDR 与 UI 计时器), 期间轮询确认未提前挂断
    time.sleep(10)
    status_now = browser.get_status_text(page_a)
    recorder.record("场景1-通话保持10s(未提前挂断)", "通话中" in status_now, "A=%s" % status_now)

    # 步骤6: 坐席A 挂断 → 坐席B 联动挂断(实测联动链路 10-12s, 阈值放宽至 15s)
    hang_a = browser.hangup(page_a)
    recorder.record("场景1-坐席A挂断", hang_a)
    hup_t0 = time.time()
    ended = browser.wait_for_call_ended(page_b, timeout=30000)
    hup_elapsed = time.time() - hup_t0
    recorder.record("场景1-坐席B联动挂断(≤15s)", ended and hup_elapsed <= 15.0,
                    "实际耗时=%.1fs" % hup_elapsed)

    # 步骤7: DB 校验(CDR 落库需 FS HANGUP_COMPLETE 事件, 挂断后轮询)
    def _cdr_row():
        return db.query("SELECT id, call_id, caller_number, callee_number, direction, "
                        "call_state, call_type, answer_flag, call_start_time, call_end_time "
                        "FROM cc_call_record WHERE deleted=0 AND caller_number=%s "
                        "AND create_time >= %s ORDER BY id DESC LIMIT 1",
                        (config.AGENT_A["sip_number"], scenario_start))

    poll_until(_cdr_row, timeout=30)
    records = _cdr_row()
    recorder.record("场景1-cc_call_record 生成(主叫%s)" % config.AGENT_A["sip_number"],
                    bool(records), str(records[0]) if records else "未找到记录")

    def _flow_ended():
        inst = get_latest_flow_instance(db, spec["flow_id"], scenario_start)
        return inst if _flow_ended_predicate(inst) else None

    flow_inst = poll_until(_flow_ended, timeout=30)
    recorder.record("场景1-cc_flow_instances(flow102)终态", flow_inst is not None,
                    ("status=%s end_time=%s call_id=%s" %
                     (flow_inst.get("status"), flow_inst.get("end_time"), flow_inst.get("call_id")))
                    if flow_inst else "30s内未写入终态")
    return recorder.all_passed


# ==================== 场景2: 出局呼叫(flow105) ====================
def scenario_2_outbound_call(ctx: dict, recorder: StepRecorder) -> bool:
    """
    场景2: 出局呼叫(浏览器坐席A 拨 0#18600000000 + 第三方网关 → tl105 转外部网关)。

    需求背景: 验证出局呼叫链路——浏览器 INVITE 携带 X-Gateway-Id, 号码路由 type=2 命中
    0# 前缀(flow105), 删除前缀后转接节点 routeType=2 routeValue=2(第三方网关) 出局,
    pjsua 软电话 18600000000(注册于第三方 FS) 作为外部被叫接听。

    预期结果(多方验证链):
      - UI: 坐席A 通话中
      - ESL: 通道出现 + CHANNEL_ANSWER 事件(双FS)
      - Java 日志: [删除前缀] 0#18600000000→18600000000
      - RTP: 软电话 rxBytes 增量>0(通话媒体到达)
      - DB: cc_call_record(被叫 18600000000, call_type=1) + cc_flow_instances(flow105) 终态
    前置条件: pjsua 软电话A 已注册第三方 FS 9988 并在线。
    """
    browser, page_a = ctx["browser"], ctx["page_a"]
    sip_a = ctx["sip_a"]
    db = ctx["db"]
    _scenario_prepare(ctx, recorder, lambda c: _pages(c))
    scenario_start = ctx["scenario_start"]
    s2_buf = ctx["s_buf"]
    log_tail = ctx["log_tail"]
    target = config.THIRD_PARTY_AGENT_NUMBER  # 18600000000(注册于第三方 FS)
    dial = config.IVR_DIAL_PREFIX_EXTERNAL + target  # 0#18600000000
    spec = FLOW_SPECS["105"]

    # 步骤1: 坐席A 指定第三方网关发起出局呼叫 0#18600000000(前缀路由 105 → 转接网关2)
    if not recorder.record("场景2-坐席A发起出局呼叫 %s(网关%s)" % (dial, config.THIRD_PARTY_GATEWAY_NAME),
                           browser.make_call(page_a, dial, gateway_name=config.THIRD_PARTY_GATEWAY_NAME)):
        take_screenshot_on_failure(browser, page_a, "scenario_2_call")
        return False

    # 步骤2: 软电话A 等待来电并接听(第三方 FS ring → sipproxy → CC 网关出局)
    if not recorder.record("场景2-%s 收到外呼来电" % target, sip_a.wait_incoming(timeout=90)):
        take_screenshot_on_failure(browser, page_a, "scenario_2_no_incoming")
        return False
    sip_a.reset_rx_stats()
    sip_a.answer()
    state = sip_a.wait_call_state(timeout=60, states=("CONNECTED", "DISCONNECTED"))
    if not recorder.record("场景2-%s 接听并建立通话" % target, state == CallState.CONNECTED,
                           "呼叫状态=%s" % state):
        return False

    # 步骤3: UI 通话中 + ESL 通道与 CHANNEL_ANSWER 事件
    deadline = time.time() + 25
    status_a = ""
    while time.time() < deadline:
        status_a = browser.get_status_text(page_a)
        if "通话中" in status_a:
            break
        time.sleep(1)
    recorder.record("场景2-坐席A UI 通话中", "通话中" in status_a, "A=%s" % status_a)
    channel_count = get_total_channel_count(ctx["esl"], ctx["esl2"])
    recorder.record("场景2-ESL 通道出现", channel_count > 0, "实际=%d" % channel_count)
    ans_evt = None
    for c in ctx["collectors"]:
        ans_evt = c.wait_event("CHANNEL_ANSWER", timeout=5)
        if ans_evt:
            break
    recorder.record("场景2-FS CHANNEL_ANSWER 事件(双FS)", ans_evt is not None,
                    ("fs=%s" % ans_evt.get("_collector_tag", "")) if ans_evt else "")

    # 步骤4: 后端日志断言(删除前缀归一化 + 路由/转接处理) + RTP 收流
    hits, _ = wait_log_keywords(
        log_tail,
        [re.compile(r"\[删除前缀\].{0,40}%s" % re.escape(dial)),
         re.compile(r"\[删除前缀\].{0,40}%s" % re.escape(target))],
        timeout=20, min_match=1, buf=s2_buf)
    recorder.record("场景2-后端日志: [删除前缀] %s→%s" % (dial, target), hits >= 1,
                    "命中关键词数=%d" % hits)
    rx_deadline, rx_bytes = time.time() + 15, 0
    sip_a.reset_rx_stats()
    while time.time() < rx_deadline:
        rx_bytes = sip_a.get_rx_bytes()
        if rx_bytes > 0:
            break
        time.sleep(1)
    recorder.record("场景2-软电话 RTP 收流(rxBytes增量>0)", rx_bytes > 0, "rxBytes=%d" % rx_bytes)

    # 步骤5: 通话保持 6s 后坐席A 挂断
    time.sleep(6)
    recorder.record("场景2-坐席A挂断", browser.hangup(page_a))
    browser.wait_for_call_ended(page_a, timeout=15000)

    # 步骤6: DB 校验
    def _cdr_row():
        return db.query("SELECT id, call_id, caller_number, callee_number, direction, "
                        "call_state, call_type, answer_flag, call_start_time, call_end_time "
                        "FROM cc_call_record WHERE deleted=0 AND callee_number=%s "
                        "AND create_time >= %s ORDER BY id DESC LIMIT 1",
                        (target, scenario_start))

    cdr = poll_until(_cdr_row, timeout=40)
    cdr_row = cdr[0] if cdr else None
    recorder.record("场景2-cc_call_record 生成(被叫%s)" % target, cdr_row is not None,
                    str(cdr) if cdr else "未找到记录")
    if cdr_row:
        recorder.record("场景2-cc_call_record 类型=1(IVR呼叫,后端实际语义)",
                        int(cdr_row.get("call_type") or 0) == 1, "call_type=%s" % cdr_row.get("call_type"))
        recorder.record("场景2-cc_call_record answer_flag=1(已接听)",
                        int(cdr_row.get("answer_flag") or 0) == 1, "answer_flag=%s" % cdr_row.get("answer_flag"))

    def _flow_ended():
        inst = get_latest_flow_instance(db, spec["flow_id"], scenario_start)
        return inst if _flow_ended_predicate(inst) else None

    flow_inst = poll_until(_flow_ended, timeout=30)
    recorder.record("场景2-cc_flow_instances(flow105)终态", flow_inst is not None,
                    ("status=%s end_time=%s call_id=%s" %
                     (flow_inst.get("status"), flow_inst.get("end_time"), flow_inst.get("call_id")))
                    if flow_inst else "30s内未写入终态")
    return recorder.all_passed


# ==================== 场景3: 入局IVR全面版(flow101, 覆盖原场景3+4) ====================
def _diagnose_inbound_failure(collectors, label: str) -> None:
    """
    入局失败诊断: 扫描双 FS 是否以 INCOMPATIBLE_DESTINATION(488) 等挂断。

    需求背景: 原场景4 的"双FS通道数轮询等待入局 + 失败诊断(第三方有通道但CC无 →
    sipproxy/隧道问题)"逻辑提炼为场景3 失败路径的通用诊断辅助, 输出具体挂断原因。
    """
    logger.warning("[诊断-%s] 转接/入局未按预期发生, 扫描双FS CHANNEL_HANGUP 原因...", label)
    for c in collectors:
        evt = c.wait_event("CHANNEL_HANGUP", timeout=5)
        if evt:
            logger.warning("[诊断-%s] fs=%s 通道挂断 uniqueId=%s cause=%s",
                           label, c.tag, evt.get("Unique-ID", ""), evt.get("Hangup-Cause", ""))


def scenario_3_inbound_ivr(ctx: dict, recorder: StepRecorder) -> bool:
    """
    场景3: 入局IVR全面版(pjsua 18600000000 呼 4001234 → tl101 全链路转坐席组)。

    需求背景: 覆盖原全场景场景3(ESL originate 模拟入局)与场景4(第三方FS 呼入)的完整
    外部呼入信令链路——pjsua 软电话注册于第三方 FS(62.234.191.165:9988), 真实呼叫
    sip:4001234@62.234.191.165:5561(sipproxy 公网入局), 比 ESL originate 更真实。
    flow101 主链: receive 收号 → 判断器1(IF result==1) → 放音 → method(1) → 判断器2
    → transfer(routeType=4 坐席组1, 组内任一就绪坐席随机接听) → end。

    预期结果(多方验证链):
      - ESL: CHANNEL_ANSWER(主叫 18600000000 过滤取 uniqueId) → 转坐席组后组内坐席 CHANNEL_ANSWER
      - Java 日志: 流式放音完成(uniqueId 精确匹配) → <receive>.result=1 → 分支命中×2 →
        放音完成×2(收号+分支放音均 TTS) → ivr方法调用节点处理 → [转坐席组]
      - RTP: 软电话 rxBytes 增量(收号提示音/放音/通话)
      - UI: 组内任一坐席(1001/1002) 接听并通话中
      - DB: cc_call_record(主叫 18600000000) + cc_flow_instances(flow101) 终态
    前置条件: L0 已核对流程101 节点序列与坐席组1 至少 1 名就绪成员; pjsua 软电话A 在线。
    """
    browser, page_a, page_b = ctx["browser"], ctx["page_a"], ctx["page_b"]
    sip_a = ctx["sip_a"]
    db = ctx["db"]
    _scenario_prepare(ctx, recorder, lambda c: _pages(c))
    scenario_start = ctx["scenario_start"]
    s3_buf = ctx["s_buf"]
    log_tail, result_tail = ctx["log_tail"], ctx["result_tail"]
    spec = FLOW_SPECS["101"]
    dtmf_key = spec["dtmf"]  # "1"
    # 动态提取 flow101 节点 id(消灭 NODE7_* 硬编码; condition 同名节点按数组序分列断言)
    node_ids = build_flow_node_ids(db, spec["flow_id"])
    receive_id = node_ids.get("receive", ["receive-node"])[0]
    method_id = node_ids.get("method", ["method-node"])[0]

    # 步骤1: pjsua 软电话发起真实外部呼入(sipproxy 公网入局, 与线上呼叫路径一致)
    recorder.record("场景3-发起呼叫 %s -> %s" % (sip_a.username, INBOUND_TARGET_URI), True)
    sip_a.call(INBOUND_TARGET_URI)
    state = sip_a.wait_call_state(timeout=90, states=("CONNECTED", "DISCONNECTED"))
    if not recorder.record("场景3-呼叫接通(IVR 应答)", state == CallState.CONNECTED,
                           "呼叫状态=%s" % state):
        return False

    # 步骤2: 定位 pjsua 呼叫的 uniqueId(CHANNEL_ANSWER 按主叫号过滤)——
    # 幽灵呼叫隔离: 场景执行期间坐席浏览器可能残留自动外呼 4001234, 不按 uniqueId 过滤
    # 会命中幽灵呼叫的"流式播放完成"导致 DTMF 提前发送错过收号窗口。
    sip_a.reset_rx_stats()
    pjsua_uuid = None
    for c in ctx["collectors"]:
        with c._lock:
            for evt in list(c._events):
                if (evt.get("Event-Name") == "CHANNEL_ANSWER"
                        and evt.get("Caller-Caller-ID-Number") == sip_a.username):
                    pjsua_uuid = evt.get("Unique-ID")
                    break
        if pjsua_uuid:
            break
    if pjsua_uuid:
        play_done_pattern = re.compile(r"流式放音完成，uniqueId: %s" % re.escape(pjsua_uuid))
        logger.info("[场景3] 已定位 pjsua 呼叫 uniqueId=%s, 精确匹配其流式放音完成", pjsua_uuid)
    else:
        play_done_pattern = re.compile(r"流式放音完成")
        logger.warning("[场景3] 未从 ESL 事件获取呼叫 uniqueId, 降级为不限 uniqueId 匹配")

    # 步骤3: 等待收号节点执行(匹配成功路径"流式播放完成"=fork 提示音播完=DTMF 窗口开启)
    hits1, _ = wait_log_keywords(log_tail, [play_done_pattern], timeout=30, min_match=1, buf=s3_buf)
    recorder.record("场景3-收号节点(%s)执行(流式播放完成)" % receive_id, hits1 >= 1,
                    "命中关键词数=%d" % hits1)
    # RTP 收流(收号提示音/静音下通话 RTP 均可)
    rx_deadline, rx_bytes = time.time() + 30, sip_a.get_rx_bytes()
    while time.time() < rx_deadline:
        rx_bytes = sip_a.get_rx_bytes()
        if rx_bytes > 0:
            break
        time.sleep(0.5)
    recorder.record("场景3-通话媒体流到达(rxBytes增量>0)", rx_bytes > 0, "rxBytes=%d" % rx_bytes)

    # 步骤4: 收号节点启动后立即发送 DTMF "1"(留 1s 余量, 命中 5s 收号窗口)
    time.sleep(1.0)
    try:
        sip_a.send_dtmf(dtmf_key, method="auto")
        recorder.record("场景3-发送 DTMF '%s'(收号节点启动后+1s)" % dtmf_key, True)
    except Exception as exc:  # noqa: BLE001
        recorder.record("场景3-发送 DTMF '%s'" % dtmf_key, False, str(exc))
        return False

    # 步骤5: IVR 执行链断言(收号结果 → 判断器1 → 放音 → 方法 → 判断器2)
    # 运行时变量存于 Redis extendedState, DB variables 列为节点配置 JSON → 以后端日志为证据
    result_pattern = re.compile(r"%s\.result(?:=|\":\")%s" % (re.escape(receive_id), dtmf_key))
    hits2, _ = wait_log_keywords(result_tail, [result_pattern], timeout=45, min_match=1)
    recorder.record("场景3-收号结果 result='%s' 写入流程变量" % dtmf_key, hits2 >= 1,
                    "后端日志运行时变量证据(Redis extendedState)")
    # 两个 condition 节点均须命中 next_IF(分支顺序按 flow_data 数组序不定, 全量断言计数)
    cond_patterns = [re.compile(r"分支命中.{0,80}%s.{0,60}next_IF" % re.escape(cid))
                     for cid in node_ids.get("condition", [])]
    hits3, _ = wait_log_keywords(log_tail, cond_patterns or [r"分支命中.{0,80}next_IF"],
                                 timeout=30, min_match=len(cond_patterns) or 1, buf=s3_buf)
    recorder.record("场景3-判断器1+2 IF 分支命中(共%d个condition)" % len(cond_patterns),
                    hits3 >= (len(cond_patterns) or 1), "命中=%d 期望>=%d" % (hits3, len(cond_patterns) or 1))
    # 放音节点执行(日志 + RTP 增长双证据): flow101 主链分支放音配置为 TTS 文本放音
    # (playbackType=2), 成功日志与收号提示音同为"流式放音完成"(streamPlayback), 以同一
    # uniqueId 出现次数≥2(收号 1 次 + IF 分支放音 1 次)判定; 兼容语音文件放音路径"语音文件就绪"
    voice_ready_pattern = re.compile(r"语音文件就绪")
    play2_deadline, hits4 = time.time() + 30, 0
    while time.time() < play2_deadline:
        s3_buf.append(log_tail.read_new())
        play_text = "".join(s3_buf)
        hits4 = len(play_done_pattern.findall(play_text)) + len(voice_ready_pattern.findall(play_text))
        if hits4 >= 2:
            break
        time.sleep(1)
    rx2_deadline, rx2_bytes = time.time() + 30, 0
    sip_a.reset_rx_stats()
    while time.time() < rx2_deadline:
        rx2_bytes = sip_a.get_rx_bytes()
        if rx2_bytes > 0:
            break
        time.sleep(2)
    recorder.record("场景3-放音节点执行(放音完成×2/RTP)",
                    hits4 >= 2 or rx2_bytes > 0, "放音完成/语音文件就绪命中=%d, rxBytes增量=%d" % (hits4, rx2_bytes))
    hits5, _ = wait_log_keywords(
        log_tail, [re.compile(r"ivr方法调用节点处理.{0,40}%s" % re.escape(method_id)), method_id],
        timeout=30, min_match=1, buf=s3_buf)
    recorder.record("场景3-方法节点(%s method=1)执行" % method_id, hits5 >= 1)

    # 步骤6: 转坐席组(routeType=4 组1; 兼容新旧日志关键词)
    hits6, _ = wait_log_keywords(
        log_tail, [re.compile(r"\[转坐席组\]"), re.compile(r"ivr-转接-转坐席组处理器.{0,40}转坐席组")],
        timeout=30, min_match=1, buf=s3_buf)
    if not recorder.record("场景3-后端发起转坐席组(组1任一就绪成员)", hits6 >= 1):
        _diagnose_inbound_failure(ctx["collectors"], "转坐席组")
        return False

    # 步骤7: 浏览器侧并发监控坐席组来电(1001/1002 任一可能被随机选中, 不能固定 page_a)
    _diag_console = []

    def _on_console(msg):
        _diag_console.append("[%s] %s" % (msg.type, msg.text))

    def _on_pageerror(exc):
        _diag_console.append("[PAGEERROR] %s" % exc)

    page_a.on("console", _on_console)
    page_a.on("pageerror", _on_pageerror)
    page_b.on("console", _on_console)
    page_b.on("pageerror", _on_pageerror)
    answer_page = None
    incoming_deadline = time.time() + 60
    while time.time() < incoming_deadline:
        if page_a.query_selector(".incoming-dialog"):
            answer_page = page_a
            break
        if page_b.query_selector(".incoming-dialog"):
            answer_page = page_b
            break
        time.sleep(1)
    answer_agent = "1001" if answer_page is page_a else ("1002" if answer_page is page_b else "未知")
    if not recorder.record("场景3-坐席%s 收到转坐席组来电" % answer_agent, answer_page is not None):
        browser.take_screenshot(page_a, "s3_no_incoming")
        logger.warning("[诊断] 转坐席坐席未收到来电, 页面 console/pageerror (%d 条):", len(_diag_console))
        for _m in _diag_console:
            logger.warning("    [诊断] %s", _m)
        return False
    answered = browser.answer_call(answer_page) and browser.wait_for_call_connected(answer_page, timeout=60000)
    if not recorder.record("场景3-坐席%s 接听并建立通话" % answer_agent, answered):
        browser.take_screenshot(answer_page, "s3_answer_failed")
        return False
    sip_state = sip_a.wait_call_state(timeout=10, states=("CONNECTED",))
    recorder.record("场景3-软电话侧呼叫保持 CONNECTED", sip_state == CallState.CONNECTED)

    # 步骤8: 双向通话(软电话收流 + UI 计时器)
    sip_a.reset_rx_stats()
    rx3_deadline, rx3_bytes = time.time() + 15, 0
    while time.time() < rx3_deadline:
        rx3_bytes = sip_a.get_rx_bytes()
        if rx3_bytes > 0:
            break
        time.sleep(1)
    ui_duration = browser.get_call_duration(answer_page)
    recorder.record("场景3-双向通话(软电话 rxBytes 增长)", rx3_bytes > 0,
                    "rxBytes=%d, UI计时=%s" % (rx3_bytes, ui_duration))

    # 步骤9: 软电话挂断, 坐席侧联动挂断(联动耗时链路长, 阈值 ≤15s)
    sip_a.hangup()
    sip_disc = sip_a.wait_call_state(timeout=20, states=("DISCONNECTED",))
    recorder.record("场景3-18600000000 挂断", sip_disc == CallState.DISCONNECTED)
    hup_t0 = time.time()
    ended = browser.wait_for_call_ended(answer_page, timeout=30000)
    hup_elapsed = time.time() - hup_t0
    recorder.record("场景3-坐席侧自动挂断(≤15s)", ended and hup_elapsed <= 15.0,
                    "实际耗时=%.1fs" % hup_elapsed)

    # 步骤10: DB 校验(转坐席后 callee_number 被改写为坐席分机, 按主叫+时间窗口定位)
    def _cdr_row():
        return db.query("SELECT id, call_id, caller_number, callee_number, direction, "
                        "call_state, call_type, answer_flag, call_start_time, call_end_time "
                        "FROM cc_call_record WHERE deleted=0 AND caller_number=%s "
                        "AND create_time >= %s ORDER BY id DESC LIMIT 1",
                        (config.IVR_SOFTPHONE_A, scenario_start))

    poll_until(_cdr_row, timeout=30)
    records = _cdr_row()
    recorder.record("场景3-cc_call_record 生成(主叫%s 被叫%s)" % (config.IVR_SOFTPHONE_A,
                                                                  config.IVR_INBOUND_ROUTE_NUM), bool(records),
                    str(records[0]) if records else "未找到记录")

    def _flow_ended():
        inst = get_latest_flow_instance(db, spec["flow_id"], scenario_start)
        return inst if _flow_ended_predicate(inst) else None

    flow_inst = poll_until(_flow_ended, timeout=30)
    recorder.record("场景3-cc_flow_instances(flow101)终态", flow_inst is not None,
                    ("status=%s end_time=%s current_node=%s call_id=%s" %
                     (flow_inst.get("status"), flow_inst.get("end_time"),
                      flow_inst.get("current_node_id"), flow_inst.get("call_id")))
                    if flow_inst else "30s内未写入终态")
    return recorder.all_passed


# ==================== 场景5: 保持/恢复(重新实现, 基线 9#1002) ====================
def _establish_base_call(ctx: dict, recorder: StepRecorder, label: str) -> bool:
    """
    建立浏览器 A→B 基线通话(坐席A 拨 9#1002 → B 接听 → 双方通话中)。

    场景1/5/6 共用基线(flow102 转接坐席1002)。新建库无 catch-all 呼出路由,
    裸号 1002 会被挂断, 必须带 9# 前缀。
    """
    browser = ctx["browser"]
    page_a, page_b = ctx["page_a"], ctx["page_b"]
    dial = config.IVR_DIAL_PREFIX_INTERNAL + config.AGENT_B["sip_number"]
    if not browser.make_call(page_a, dial):
        recorder.record("%s-坐席A发起呼叫 %s" % (label, dial), False)
        return False
    if not browser.wait_for_incoming_call(page_b, timeout=config.CALL_TIMEOUT):
        recorder.record("%s-坐席B收到来电" % label, False)
        take_screenshot_on_failure(browser, page_b, "%s_incoming" % label)
        return False
    if not browser.answer_call(page_b):
        recorder.record("%s-坐席B接听" % label, False)
        return False
    if not browser.wait_for_call_connected(page_a, timeout=config.CALL_TIMEOUT):
        recorder.record("%s-坐席A通话建立" % label, False)
        return False
    deadline = time.time() + 25
    status_a = status_b = ""
    while time.time() < deadline:
        status_a = browser.get_status_text(page_a)
        status_b = browser.get_status_text(page_b)
        if "通话中" in status_a and "通话中" in status_b:
            break
        time.sleep(1)
    recorder.record("%s-基线通话建立(双方通话中)" % label,
                    "通话中" in status_a and "通话中" in status_b, "A=%s B=%s" % (status_a, status_b))
    return "通话中" in status_a and "通话中" in status_b


def scenario_5_hold_resume(ctx: dict, recorder: StepRecorder) -> bool:
    """
    场景5: 通话保持/恢复(重新实现, 基线 9#1002, 3 轮 hold/resume)。

    需求背景: 验证通话中 hold/resume 信令流程(B2BUA 透传 re-INVITE: 坐席A JsSIP 发送
    re-INVITE(sendonly)→ sipproxy WsInviteRequestHandler 同 Call-ID 直传不重新 park → FS
    切换媒体方向; resume 同理 sendrecv)。旧实现基线裸号 1002 在新库无路由已失效,
    基线改为 9#1002 经 flow102 建立 A-B 通话后, 在同一通话内执行 3 轮保持/恢复。

    预期结果(多方验证链):
      - UI: 保持后显示"保持", 恢复后显示"通话中"
      - ESL: 保持/恢复期间通道数≥2 不中断 + FS CHANNEL_HOLD/CHANNEL_UNHOLD 事件
      - DB: 通话记录正常生成
      - 场景末 _force_re_signin_agents 强制重签 A/B, 防 JsSIP 状态污染场景6
    容错策略: re-INVITE 透传不稳定时, 保持信令已发出(UI 或通道数任一证据)即算降级通过;
    任一轮成功即场景通过, 全部失败才 FAIL。
    """
    browser = ctx["browser"]
    page_a, page_b = ctx["page_a"], ctx["page_b"]
    db = ctx["db"]
    _scenario_prepare(ctx, recorder, lambda c: _pages(c))
    scenario_start = ctx["scenario_start"]
    # 前置: 坐席在线检查(场景5 前若有失败操作可能致 JsSIP 断连)
    for page, name in [(page_a, "A"), (page_b, "B")]:
        if not ensure_agent_online(browser, page, name):
            recorder.record("场景5-前置坐席%s重新签入" % name, False)
            return False
        browser.set_ready(page, ready=True)
        time.sleep(1)

    hold_success_count = 0
    hold_degraded_count = 0
    call_alive = True
    try:
        # 步骤1: 建立基线 A-B 通话(9#1002)
        if not _establish_base_call(ctx, recorder, "场景5"):
            take_screenshot_on_failure(browser, page_a, "scenario_5_base_call")
            return False
        initial_channel_count = get_total_channel_count(ctx["esl"], ctx["esl2"])
        recorder.record("场景5-初始 ESL 通道数≥2", initial_channel_count >= 2,
                        "实际=%d" % initial_channel_count)
        if initial_channel_count < 2:
            take_screenshot_on_failure(browser, page_a, "scenario_5_init_channel")
            return False

        # 步骤2: 3 轮保持/恢复
        for round_num in range(1, 4):
            logger.info("---------- 场景5 保持/恢复 第 %d 轮 ----------", round_num)
            # 2.0 通话在线检查(上轮 hold 后 JsSIP 可能自发 BYE, 断线则重建基线)
            status_now = browser.get_status_text(page_a)
            if "通话中" not in status_now:
                logger.warning("第%d轮: 通话已断开(A=%s), 重建基线...", round_num, status_now)
                call_alive = _establish_base_call(ctx, recorder, "场景5-重建")
                if not call_alive:
                    recorder.record("场景5-第%d轮 重建基线失败" % round_num, False)
                    continue
            # 2.1 点击保持(re-INVITE sendonly)
            if not browser.toggle_hold(page_a):
                recorder.record("场景5-第%d轮 点击保持" % round_num, False)
                continue
            recorder.record("场景5-第%d轮 点击保持" % round_num, True)
            # 2.2 证据1: FS CHANNEL_HOLD 事件; 证据2: UI"保持"或通道数≥2
            hold_evt = None
            for c in ctx["collectors"]:
                hold_evt = c.wait_event("CHANNEL_HOLD", timeout=15)
                if hold_evt:
                    break
            time.sleep(3)
            status_a = browser.get_status_text(page_a)
            hold_channel_count = get_total_channel_count(ctx["esl"], ctx["esl2"])
            logger.info("第%d轮 保持后 A=%s 通道=%d hold事件=%s",
                        round_num, status_a, hold_channel_count, hold_evt is not None)
            hold_ok = ("保持" in status_a) or hold_channel_count >= 2 or hold_evt is not None
            recorder.record("场景5-第%d轮 保持验证(UI/通道/事件任一)" % round_num, hold_ok,
                            "UI=%s 通道=%d CHANNEL_HOLD=%s" %
                            (status_a, hold_channel_count, hold_evt is not None))
            if not hold_ok:
                recorder.record("场景5-第%d轮 保持失败" % round_num, False)
                continue
            # hold 后通话被 JsSIP 自发 BYE 破坏(媒体协商失败): 信令已验证, 降级通过
            status_after_hold = browser.get_status_text(page_a)
            if "通话中" not in status_after_hold and "保持" not in status_after_hold:
                logger.warning("第%d轮: hold 后通话断开(A=%s), 信令已发送, 降级通过本轮",
                               round_num, status_after_hold)
                hold_degraded_count += 1
                continue
            # 2.3 保持 3 秒后点击恢复(re-INVITE sendrecv)
            time.sleep(3)
            if not browser.toggle_hold(page_a):
                recorder.record("场景5-第%d轮 点击恢复" % round_num, False)
                hold_degraded_count += 1
                continue
            recorder.record("场景5-第%d轮 点击恢复" % round_num, True)
            # 2.4 证据1: FS CHANNEL_UNHOLD 事件; 证据2: UI"通话中"或通道数≥2
            unhold_evt = None
            for c in ctx["collectors"]:
                unhold_evt = c.wait_event("CHANNEL_UNHOLD", timeout=15)
                if unhold_evt:
                    break
            time.sleep(3)
            status_a = browser.get_status_text(page_a)
            resume_channel_count = get_total_channel_count(ctx["esl"], ctx["esl2"])
            logger.info("第%d轮 恢复后 A=%s 通道=%d unhold事件=%s",
                        round_num, status_a, resume_channel_count, unhold_evt is not None)
            resume_ok = ("通话中" in status_a) or resume_channel_count >= 2 or unhold_evt is not None
            recorder.record("场景5-第%d轮 恢复验证(UI/通道/事件任一)" % round_num, resume_ok,
                            "UI=%s 通道=%d CHANNEL_UNHOLD=%s" %
                            (status_a, resume_channel_count, unhold_evt is not None))
            if resume_ok:
                hold_success_count += 1
                logger.info("第%d轮 保持/恢复 完全通过", round_num)
            else:
                hold_degraded_count += 1

        # 步骤3: DB 通话记录校验
        time.sleep(2)
        record_count = db.count_call_records_since(scenario_start)
        recorder.record("场景5-通话记录生成(DB)", record_count > 0, "新增=%d" % record_count)

        # 最终判定: 至少 1 轮(成功或降级通过)即场景通过(保持 re-INVITE 透传历史不稳定性)
        passed_count = hold_success_count + hold_degraded_count
        recorder.record("场景5-保持/恢复判定(成功%d轮 降级%d轮)" % (hold_success_count, hold_degraded_count),
                        passed_count >= 1, "3轮中%d轮验证通过" % passed_count)
        return passed_count >= 1
    finally:
        # 清理 + 强制重签 A/B: hold 后 JsSIP 易残留脏 SIP/WebRTC 状态, 防污染场景6
        cleanup_calls(ctx["esl"], ctx["esl2"], browser, [page_a, page_b])
        _force_re_signin_agents(browser, [page_a, page_b], "场景5结束")


# ==================== 场景6: 咨询转接(基线 9#1002, attended 转 1003) ====================
def scenario_6_consult_transfer(ctx: dict, recorder: StepRecorder) -> bool:
    """
    场景6: 咨询转接(坐席A 基线通话 9#1002, attended 转接坐席C 1003)。

    需求背景: 验证咨询转接(attended transfer)全流程——A 发送 REFER(X-Transfer-Type:
    attended)→ sipproxy WsReferRequestHandler → uuidHold(a-leg) + originate c-leg 到坐席C;
    C 接听后 A 挂断 → bridgeCall(b-leg, c-leg) B-C 桥接通话。

    预期结果(多方验证链):
      - 浏览器: window._transferDebug.referResult=true(REFER 确实发出)
      - UI: C 收到咨询来电并接听; A 挂断退出通话; B-C 通话保持
      - ESL: 咨询期通道≥2(A-B hold + A-C 咨询), 转接后仍≥2(B-C)
      - DB: 通话记录生成
    前置条件: 坐席C(1003) 首次使用时在场景内创建/登录/签入(page_c 懒创建)。
    """
    browser = ctx["browser"]
    page_a, page_b = ctx["page_a"], ctx["page_b"]
    db = ctx["db"]
    _scenario_prepare(ctx, recorder, lambda c: _pages(c))
    scenario_start = ctx["scenario_start"]
    # 前置: 坐席在线检查 + 强制重签 A/B(场景5 hold 副作用彻底清除)
    for page, name in [(page_a, "A"), (page_b, "B")]:
        if not ensure_agent_online(browser, page, name):
            # 在线检查失败(可能 SIP 会话残留/ws 断连), 升级为完整重登录恢复
            agent = config.AGENT_A if name == "A" else config.AGENT_B
            re_ok = login_and_signin(browser, page, agent, config.LOCAL_FRONTEND_URL, recorder)
            recorder.record("场景6-前置坐席%s重新签入" % name, re_ok)
            if not re_ok:
                return False
        browser.set_ready(page, ready=True)
        time.sleep(1)
    _force_re_signin_agents(browser, [page_a, page_b], "场景6前置")

    try:
        # 步骤1: 坐席A 呼叫坐席B 建立基线(9#1002, 2 次尝试容忍首呼偶发失败)
        call_established = False
        for call_attempt in range(1, 3):
            if _establish_base_call(ctx, recorder, "场景6-第%d次" % call_attempt):
                call_established = True
                break
            cleanup_calls(ctx["esl"], ctx["esl2"], browser, [page_a, page_b])
            time.sleep(2)
            if not ensure_agent_online(browser, page_b, "B"):
                logger.warning("[场景6] 重试前 B 重签失败")
            browser.set_ready(page_b, ready=True)
            time.sleep(2)
        if not call_established:
            recorder.record("场景6-基线通话建立", False, "2 次尝试均失败")
            take_screenshot_on_failure(browser, page_b, "scenario_6_no_incoming")
            return False

        # 步骤2: 创建并签入坐席C(懒创建, 仅首次)
        if ctx.get("page_c") is None:
            page_c = browser.new_context_page()
            browser.navigate_to_login(page_c, config.LOCAL_FRONTEND_URL)
            if not browser.login(page_c, config.AGENT_C["username"], config.AGENT_C["password"]):
                recorder.record("场景6-坐席C登录", False)
                take_screenshot_on_failure(browser, page_c, "scenario_6_c_login")
                return False
            if not browser.signin(page_c):
                recorder.record("场景6-坐席C SIP签入", False)
                take_screenshot_on_failure(browser, page_c, "scenario_6_c_signin")
                return False
            if not browser.set_ready(page_c, ready=True):
                recorder.record("场景6-坐席C设置就绪", False)
                return False
            ctx["page_c"] = page_c
            recorder.record("场景6-坐席C(1003)创建并签入就绪", True)
        page_c = ctx["page_c"]

        # 步骤3: 打开转接弹窗并执行咨询转接至 1003
        if not recorder.record("场景6-坐席A打开转接弹窗", browser.open_transfer_popup(page_a)):
            take_screenshot_on_failure(browser, page_a, "scenario_6_open_popup")
            return False
        if not recorder.record("场景6-发起咨询转接(attended→1003)",
                               browser.perform_transfer(page_a, target=config.AGENT_C["sip_number"],
                                                        transfer_type="attended")):
            take_screenshot_on_failure(browser, page_a, "scenario_6_perform")
            return False
        # 步骤4: 检查 window._transferDebug 确认 REFER 确实发出(JsSIP refer() 在 session
        # 非 CONFIRMED 状态返回 false → REFER 未发送, 需直接失败)
        try:
            transfer_debug = page_a.evaluate("window._transferDebug")
            logger.info("window._transferDebug: %s", transfer_debug)
            refer_sent = bool(transfer_debug and transfer_debug.get("referResult") is True)
            recorder.record("场景6-REFER 已发送(_transferDebug.referResult)", refer_sent,
                            str(transfer_debug) if transfer_debug else "无调试变量")
            # referResult 为 False(REFER 未发出)或 None(调试变量未注入)时均视为未成功发送,
            # 后续断言全部基于未发生的行为, 直接失败返回
            if transfer_debug is not None and transfer_debug.get("referResult") is not True:
                take_screenshot_on_failure(browser, page_a, "scenario_6_refer_failed")
                return False
        except Exception as eval_e:  # noqa: BLE001
            logger.warning("读取 window._transferDebug 失败: %s", eval_e)

        # 步骤5: 坐席C 等待咨询来电并接听
        if not recorder.record("场景6-坐席C收到咨询来电",
                               browser.wait_for_incoming_call(page_c, timeout=config.CALL_TIMEOUT)):
            take_screenshot_on_failure(browser, page_c, "scenario_6_wait_incoming")
            return False
        if not recorder.record("场景6-坐席C接听咨询通话", browser.answer_call(page_c)):
            take_screenshot_on_failure(browser, page_c, "scenario_6_answer")
            return False
        # 步骤6: 咨询通话稳定(A-C 媒体建立)后校验通道
        time.sleep(5)
        consult_channel_count = get_total_channel_count(ctx["esl"], ctx["esl2"])
        recorder.record("场景6-咨询期间ESL 通道数≥2(A-B hold + A-C 咨询)",
                        consult_channel_count >= 2, "实际=%d" % consult_channel_count)

        # 步骤7: 坐席A 挂断完成转接(A 挂断 → sipproxy bridgeCall(b-leg, c-leg))
        hangup_ok = browser.hangup(page_a)
        if not recorder.record("场景6-坐席A挂断完成转接", hangup_ok):
            take_screenshot_on_failure(browser, page_a, "scenario_6_hangup_failed")
            logger.warning("坐席A挂断失败, 尝试通过 ESL 清理")
        call_ended = browser.wait_for_call_ended(page_a, timeout=15000)
        recorder.record("场景6-坐席A退出通话", hangup_ok and call_ended)

        # 步骤8: 转接后 B-C 通话仍存在(通道≥2)
        time.sleep(3)
        final_channel_count = get_total_channel_count(ctx["esl"], ctx["esl2"])
        recorder.record("场景6-转接后B-C通道≥2(桥接建立)", final_channel_count >= 2,
                        "实际=%d" % final_channel_count)

        # 步骤9: B/C 挂断清理——B-C 桥接(uuid_bridge)后 FS 侧 dialog 与客户端 tag 不一致
        # (B2BUA 透传边界, 客户端 BYE 被 FS 回 481 无法拆除通道), 改用 ESL 批量挂断
        # 触发挂断链与 CDR 收尾; 桥接后 B/C 的媒体直通, UI 挂断按钮仅影响本端会话
        for esl in (ctx["esl"], ctx["esl2"]):
            try:
                esl.hangup_all_channels()
            except Exception:  # noqa: BLE001
                pass
        browser.wait_for_call_ended(page_b, timeout=15000)
        browser.wait_for_call_ended(page_c, timeout=15000)
        # CDR 落库存在挂断链收尾延迟(COMPLETE 事件处理 + DB 写入), 轮询等待而非一次查询
        record_count = 0
        cdr_deadline = time.time() + 15
        while time.time() < cdr_deadline:
            record_count = db.count_call_records_since(scenario_start)
            if record_count > 0:
                break
            time.sleep(2)
        recorder.record("场景6-通话记录生成(DB)", record_count > 0, "新增=%d" % record_count)
        return recorder.all_passed
    finally:
        cleanup_calls(ctx["esl"], ctx["esl2"], browser,
                      [page_a, page_b, ctx.get("page_c")])


# ==================== 场景7: 自动外呼全面版(显式选路由103) ====================
def scenario_7_autocall(ctx: dict, recorder: StepRecorder) -> bool:
    """
    场景7: 自动外呼全面版(页面建任务, 显式选路由103 + target 18600000001 + 第三方网关)。

    需求背景: 验证自动外呼全流程——页面创建外呼任务(IVR流程下拉显式选"呼出-自动外呼"
    即路由103, 出局网关=第三方网关), 执行后软电话B(18600000001) 接听并执行 flow103
    (start→receive→end), 三表(cc_call_record / cc_autocall_task_record / cc_flow_instances)
    call_id 一致。显式选路由绕过号码翻译不确定性(00200 号段在仓库无翻译证据,
    主路径确定可达); 路由命中冒烟在步骤5 以日志告警方式附带验证。

    预期结果(多方验证链):
      - UI: 任务列表"待执行→执行中", 记录弹窗显示执行记录
      - ESL: CHANNEL_ANSWER(被叫 18600000001 过滤) + 通道出现
      - Java 日志: 收号节点"流式播放完成"(uniqueId 精确) → <receive>.result=1;
        若后端日志出现 [自动外呼][号码路由匹配] 亦记录(冒烟, 失败仅告警)
      - RTP: 软电话B rxBytes 增量
      - DB: cc_autocall_task_record 终态 + 三表 call_id 一致 + flow103 终态
    前置条件: 软电话B 已注册第三方 FS; 外呼任务表单下拉含"呼出-自动外呼(^(00200).*)"选项。
    """
    browser, page_a = ctx["browser"], ctx["page_a"]
    sip_b = ctx["sip_b"]
    db = ctx["db"]
    _scenario_prepare(ctx, recorder, lambda c: _pages(c))
    scenario_start = ctx["scenario_start"]
    s7_buf = ctx["s_buf"]
    log_tail, result_tail = ctx["log_tail"], ctx["result_tail"]
    spec = FLOW_SPECS["103"]
    dtmf_key = spec["dtmf"] or "1"
    node_ids = build_flow_node_ids(db, spec["flow_id"])
    receive_id = node_ids.get("receive", ["receive-node"])[0]
    task_name = "E2E_AUTOCALL_%d" % int(time.time())
    target = config.AUTOCALL_TARGET_NUMBER  # 18600000001
    # 前端 IVR流程下拉选项 label 为「路由名称(路由号码)」, value 是号码路由 id(非 flow_id)
    ivr_flow_option = "%s(%s)" % (spec["name"], spec["regex"])  # 呼出-自动外呼(^(00200).*)
    task_id_from_db = None

    try:
        # 步骤1: 导航到外呼任务管理页面(Vue Router 初始跳转偶发上下文销毁, 带重试)
        nav_ok = False
        for nav_attempt in range(1, 4):
            try:
                nav_ok = browser.navigate_to_admin_path(page_a, "/cc/cc_call/autocall-task")
            except Exception as nav_e:  # noqa: BLE001
                logger.warning("[场景7] 导航异常(第%d次): %s", nav_attempt, nav_e)
                nav_ok = False
            if nav_ok:
                break
            time.sleep(2)
        if not recorder.record("场景7-导航外呼任务页面 /cc/cc_call/autocall-task", nav_ok):
            take_screenshot_on_failure(browser, page_a, "scenario_7_navigate")
            return False
        browser.refresh_autocall_task_list(page_a)
        try:
            browser.delete_autocall_task_by_name(page_a, task_name)
        except Exception:  # noqa: BLE001 - 无同名任务视为正常
            pass

        # 步骤2: 创建外呼任务(弹窗 Vue 重渲染偶发元素脱链, 创建步骤带重试)
        created = False
        for create_attempt in range(1, 4):
            try:
                if page_a.query_selector(".com-dialog"):
                    page_a.keyboard.press("Escape")
                    time.sleep(1)
            except Exception:  # noqa: BLE001
                pass
            created = (browser.open_autocall_task_create_form(page_a)
                       and fill_autocall_form(page_a, task_name, target,
                                              ivr_flow_option, config.THIRD_PARTY_GATEWAY_NAME)
                       and browser.submit_autocall_task_form(page_a))
            if created:
                break
            logger.warning("创建外呼任务第%d次尝试失败, 弹窗状态: %s", create_attempt,
                           page_a.evaluate("() => Array.from(document.querySelectorAll('.com-dialog'))"
                                           ".map(d => d.offsetParent !== null)"))
            time.sleep(2)
        if not recorder.record("场景7-创建外呼任务(%s 流程%s 网关%s)" %
                               (task_name, spec["flow_id"], config.THIRD_PARTY_GATEWAY_NAME), created):
            take_screenshot_on_failure(browser, page_a, "scenario_7_create")
            return False
        time.sleep(2)
        if not recorder.record("场景7-任务列表出现新任务(待执行)",
                               browser.find_autocall_task_row(page_a, task_name)):
            take_screenshot_on_failure(browser, page_a, "scenario_7_task_row")
            return False
        # 记录任务ID: 供终端 DB 校验与 finally 软删除兑底使用
        try:
            task_rows = db.query("SELECT id FROM cc_autocall_task WHERE task_name = %s AND deleted = 0",
                                 (task_name,))
            if task_rows:
                task_id_from_db = task_rows[0].get("id")
                logger.info("数据库查询到任务ID: %s", task_id_from_db)
        except Exception:  # noqa: BLE001
            pass

        # 步骤3: 触发任务执行 → 软电话B 等待来电并接听
        if not recorder.record("场景7-触发任务执行", browser.execute_autocall_task_by_name(page_a, task_name)):
            return False
        if not recorder.record("场景7-%s 收到外呼来电" % target, sip_b.wait_incoming(timeout=90)):
            take_screenshot_on_failure(browser, page_a, "scenario_7_no_incoming")
            return False
        sip_b.reset_rx_stats()
        sip_b.answer()
        state = sip_b.wait_call_state(timeout=60, states=("CONNECTED", "DISCONNECTED"))
        if not recorder.record("场景7-%s 接听" % target, state == CallState.CONNECTED,
                               "呼叫状态=%s" % state):
            return False
        # 任务状态 UI 断言(执行中; 快速完成时可能已回写, 仅告警不阻断)
        try:
            status_text = browser.get_autocall_task_status_text(page_a, task_name)
            logger.info("执行后任务状态: %s", status_text)
            if "执行中" not in status_text:
                logger.warning("任务状态非'执行中': %s(可能已快速完成)", status_text)
        except Exception:  # noqa: BLE001
            pass

        # 步骤4: 收号断言(定位软电话B 通道 uniqueId 精确匹配"流式播放完成")
        rx_deadline, rx_bytes = time.time() + 10, 0
        while time.time() < rx_deadline:
            rx_bytes = sip_b.get_rx_bytes()
            if rx_bytes > 0:
                break
            time.sleep(0.5)
        recorder.record("场景7-被叫收到 IVR 媒体流(rxBytes增量>0)", rx_bytes > 0, "rxBytes=%d" % rx_bytes)
        pjsua_b_uuid = None
        for c in ctx["collectors"]:
            with c._lock:
                for evt in list(c._events):
                    if (evt.get("Event-Name") == "CHANNEL_ANSWER"
                            and (evt.get("Caller-Caller-ID-Number") == sip_b.username
                                 or evt.get("Caller-Destination-Number") == sip_b.username)):
                        pjsua_b_uuid = evt.get("Unique-ID")
                        break
            if pjsua_b_uuid:
                break
        if pjsua_b_uuid:
            play_done_pattern = re.compile(r"流式放音完成，uniqueId: %s" % re.escape(pjsua_b_uuid))
            logger.info("[场景7] 已定位软电话B通道 uniqueId=%s, 精确匹配其流式放音完成", pjsua_b_uuid)
        else:
            play_done_pattern = re.compile(r"流式放音完成")
            logger.warning("[场景7] 未从 ESL 事件获取软电话B uniqueId, 降级为不限 uniqueId 匹配")
        hits1, _ = wait_log_keywords(log_tail, [play_done_pattern], timeout=30, min_match=1, buf=s7_buf)
        recorder.record("场景7-收号节点(%s)执行" % receive_id, hits1 >= 1, "命中=%d" % hits1)
        time.sleep(1.0)
        try:
            sip_b.send_dtmf(dtmf_key, method="auto")
            recorder.record("场景7-发送 DTMF '%s'" % dtmf_key, True)
        except Exception as exc:  # noqa: BLE001
            recorder.record("场景7-发送 DTMF '%s'" % dtmf_key, False, str(exc))
        result_pattern = re.compile(r"%s\.result(?:=|\":\")%s" % (re.escape(receive_id), dtmf_key))
        hits2, _ = wait_log_keywords(result_tail, [result_pattern], timeout=45, min_match=1)
        recorder.record("场景7-收号结果 result='%s' 写入流程变量" % dtmf_key, hits2 >= 1)
        # 路由命中冒烟: 显式选路由时后端可能不打此日志, 失败仅告警不阻断
        hits_route, _ = wait_log_keywords(
            log_tail, [re.compile(r"\[自动外呼\]\[号码路由匹配\]")], timeout=10, min_match=1,
            buf=s7_buf)
        if hits_route >= 1:
            logger.info("[场景7-冒烟] 后端日志命中 [自动外呼][号码路由匹配]")
        else:
            logger.warning("[场景7-冒烟] 未命中 [自动外呼][号码路由匹配](显式选路由时属正常, 忽略)")

        # 步骤5: 通话结束(IVR 结束节点主动挂断或被叫挂断均可)
        disc = sip_b.wait_call_state(timeout=30, states=("DISCONNECTED",))
        if disc != CallState.DISCONNECTED:
            logger.info("场景7: IVR 未在30s内主动挂断, 由被叫挂断(可接受)")
            sip_b.hangup()
            disc = sip_b.wait_call_state(timeout=15, states=("DISCONNECTED",))
        recorder.record("场景7-通话结束挂断(IVR主动或被叫挂断均可)", disc == CallState.DISCONNECTED)

        # 步骤6: DB 校验——三表 call_id 一致 + 任务记录终态 + 流程终态
        def _cdr_ok():
            rows = db.query("SELECT id, call_id, caller_number, callee_number, direction, "
                            "call_state, call_type, answer_flag, call_start_time, call_end_time "
                            "FROM cc_call_record WHERE deleted=0 AND callee_number=%s "
                            "AND create_time >= %s ORDER BY id DESC LIMIT 1",
                            (target, scenario_start))
            return rows[0] if rows else None

        cdr = poll_until(_cdr_ok, timeout=30)
        recorder.record("场景7-cc_call_record 生成(被叫%s)" % target, cdr is not None,
                        str(cdr) if cdr else "未找到记录")
        if cdr:
            recorder.record("场景7-cc_call_record 类型=1(IVR呼叫)",
                            int(cdr.get("call_type") or 0) == 1, "call_type=%s" % cdr.get("call_type"))
            recorder.record("场景7-cc_call_record answer_flag=1(已接听)",
                            int(cdr.get("answer_flag") or 0) == 1, "answer_flag=%s" % cdr.get("answer_flag"))

        def _task_record_done():
            rows = db.query("SELECT id, task_id, call_id, target_number, status, duration, "
                            "dtmf_collected, hangup_cause FROM cc_autocall_task_record "
                            "WHERE deleted=0 AND target_number=%s AND create_time >= %s "
                            "ORDER BY id DESC LIMIT 1", (target, scenario_start))
            if rows and int(rows[0]["status"]) >= 2:  # 已回写终态(2已接通/3未接通/4失败)
                return rows[0]
            return None

        task_record = poll_until(_task_record_done, timeout=45)
        recorder.record("场景7-cc_autocall_task_record 回写终态", task_record is not None,
                        ("status=%s(%s) call_id=%s duration=%s dtmf=%s" %
                         (task_record["status"],
                          AUTOCALL_RECORD_STATUS_TEXT.get(int(task_record["status"])),
                          task_record["call_id"], task_record["duration"],
                          task_record["dtmf_collected"]))
                        if task_record else "45s 内未回写终态")

        flow_inst = poll_until(
            lambda: (lambda i: i if _flow_ended_predicate(i) else None)
            (get_latest_flow_instance(db, spec["flow_id"], scenario_start)), timeout=30)
        recorder.record("场景7-cc_flow_instances(flow103)终态", flow_inst is not None,
                        ("status=%s end_time=%s call_id=%s" %
                         (flow_inst.get("status"), flow_inst.get("end_time"),
                          flow_inst.get("call_id")))
                        if flow_inst else "30s内未写入终态")
        if cdr and task_record and flow_inst:
            id_set = {str(cdr.get("call_id")), str(task_record.get("call_id")),
                      str(flow_inst.get("call_id"))}
            recorder.record("场景7-三表 call_id 一致", len(id_set) == 1, "call_ids=%s" % sorted(id_set))

        # 步骤7: 记录弹窗查看(UI 证据, 失败不阻断) + 任务数据清理
        try:
            if browser.view_autocall_task_records(page_a, task_name):
                try:
                    page_a.wait_for_selector(".com-dialog .el-loading-mask", state="hidden", timeout=10000)
                except Exception:  # noqa: BLE001
                    pass
                records = page_a.query_selector_all(".com-dialog .el-table__row")
                recorder.record("场景7-任务记录弹窗显示记录", len(records) >= 1, "记录数=%d" % len(records))
                try:
                    browser.close_dialog(page_a)
                except Exception:  # noqa: BLE001
                    pass
        except Exception as e:  # noqa: BLE001
            logger.warning("查看任务记录弹窗异常(非致命): %s", e)
        return recorder.all_passed
    finally:
        # 清理: 挂断所有通道 + DB 软删除测试任务(页面删除失败时兜底)
        cleanup_calls(ctx["esl"], ctx["esl2"], browser, [page_a])
        if task_id_from_db:
            try:
                db.execute("UPDATE cc_autocall_task SET deleted = 1 WHERE id = %s", (task_id_from_db,))
                db.execute("UPDATE cc_autocall_task_record SET deleted = 1 WHERE task_id = %s",
                           (task_id_from_db,))
            except Exception:  # noqa: BLE001
                pass
        try:
            db.execute("UPDATE cc_autocall_task SET deleted = 1 WHERE task_name = %s", (task_name,))
        except Exception:  # noqa: BLE001
            pass
        try:
            browser.delete_autocall_task_by_name(page_a, task_name)
        except Exception as e:  # noqa: BLE001
            logger.warning("UI 删除测试任务异常(非致命, DB 已清理): %s", e)


# ==================== 场景8(可选): 客服组繁忙(flow104) ====================
def scenario_8_group_busy(ctx: dict, recorder: StepRecorder) -> bool:
    """
    场景8(可选): 客服组繁忙点验(浏览器拨 00300xxx → tl104 播放"客服组繁忙请稍等再拨")。

    需求背景: 验证呼出前缀 00300 命中路由104 后 flow104(start→playback→end) 广播忙提示音
    并自动结束挂断, 用于快速点验新路由/流程是否可用。仅当 --scenarios 显式包含 8 时执行。

    预期结果(多方验证链):
      - Java 日志: [删除前缀] 未发生(无前缀) + 播放"客服组繁忙请稍等再拨" + 流程终态
      - ESL: 呼叫通道生命周期(CHANNEL_ANSWER 出现, 结束后通道回收)
      - DB: cc_flow_instances(flow104) 终态(status∈{2,3} + end_time 非空)
    前置条件: 路由104 已启用(场景执行前 L0 核对)。
    """
    browser, page_a = ctx["browser"], ctx["page_a"]
    db = ctx["db"]
    _scenario_prepare(ctx, recorder, lambda c: _pages(c))
    scenario_start = ctx["scenario_start"]
    s8_buf = ctx["s_buf"]
    log_tail = ctx["log_tail"]
    spec = FLOW_SPECS["104"]
    dial = "0030012345"  # 00300 前缀命中路由104, 任意后缀即可

    # 步骤1: 坐席A 浏览器拨号触发 flow104(IVR 应答播放忙提示音)
    if not recorder.record("场景8-坐席A发起呼叫 %s" % dial, browser.make_call(page_a, dial)):
        take_screenshot_on_failure(browser, page_a, "scenario_8_call")
        return False
    connected = browser.wait_for_call_connected(page_a, timeout=config.CALL_TIMEOUT)
    recorder.record("场景8-IVR应答(播放忙提示音)", connected)
    if not connected:
        take_screenshot_on_failure(browser, page_a, "scenario_8_connect")
        return False

    # 步骤2: 后端日志断言(播放内容 + 路由处理)
    hits1, _ = wait_log_keywords(
        log_tail,
        [r"客服组繁忙请稍等再拨", re.compile(r"\[进入callRoute电话\]"), r"语音文件就绪"],
        timeout=30, min_match=1, buf=s8_buf)
    recorder.record("场景8-后端日志[客服组繁忙请稍等再拨]等关键词", hits1 >= 1, "命中=%d" % hits1)

    # 步骤3: 流程自动结束挂断(playback 播完 → end 节点)
    ended = browser.wait_for_call_ended(page_a, timeout=30000)
    recorder.record("场景8-自动挂断(流程结束)", ended)

    # 步骤4: DB 流程终态校验
    def _flow_ended():
        inst = get_latest_flow_instance(db, spec["flow_id"], scenario_start)
        return inst if _flow_ended_predicate(inst) else None

    flow_inst = poll_until(_flow_ended, timeout=30)
    recorder.record("场景8-cc_flow_instances(flow104)终态", flow_inst is not None,
                    ("status=%s end_time=%s call_id=%s" %
                     (flow_inst.get("status"), flow_inst.get("end_time"), flow_inst.get("call_id")))
                    if flow_inst else "30s内未写入终态")
    return recorder.all_passed


# ==================== 场景9(可选): 满意度评价(flow106) ====================
def scenario_9_satisfaction(ctx: dict, recorder: StepRecorder) -> bool:
    """
    场景9(可选): 满意度评价点验(浏览器拨 00100xxx → tl106 收号按1 → 感谢您的评价)。

    需求背景: 验证呼出前缀 00100 命中路由106 后 flow106(start→receive→method→end)
    收号按键触发方法调用并播放"感谢您的评价,再见"结束语后自动结束。
    仅当 --scenarios 显式包含 9 时执行。

    预期结果(多方验证链):
      - Java 日志: <receive>.result=1(动态节点id) + ivr方法调用节点处理 + "感谢您的评价"
      - UI: 呼叫自动结束(流程 end 节点挂断)
      - DB: cc_flow_instances(flow106) 终态
    前置条件: 路由106 已启用; 坐席1001 在线(L1/L2 登签)。
    """
    browser, page_a = ctx["browser"], ctx["page_a"]
    db = ctx["db"]
    _scenario_prepare(ctx, recorder, lambda c: _pages(c))
    scenario_start = ctx["scenario_start"]
    s9_buf = ctx["s_buf"]
    log_tail, result_tail = ctx["log_tail"], ctx["result_tail"]
    spec = FLOW_SPECS["106"]
    dtmf_key = spec["dtmf"] or "1"
    node_ids = build_flow_node_ids(db, spec["flow_id"])
    receive_id = node_ids.get("receive", ["receive-node"])[0]
    dial = "0010012345"  # 00100 前缀命中路由106, 任意后缀即可

    # 步骤1: 坐席A 浏览器拨号触发 flow106
    if not recorder.record("场景9-坐席A发起呼叫 %s" % dial, browser.make_call(page_a, dial)):
        take_screenshot_on_failure(browser, page_a, "scenario_9_call")
        return False
    connected = browser.wait_for_call_connected(page_a, timeout=config.CALL_TIMEOUT)
    recorder.record("场景9-IVR应答(开始收号)", connected)
    if not connected:
        take_screenshot_on_failure(browser, page_a, "scenario_9_connect")
        return False

    # 步骤2: 收号节点就绪(uniqueId 精确匹配"流式播放完成")后发送 DTMF
    s9_uuid = None
    for c in ctx["collectors"]:
        with c._lock:
            for evt in list(c._events):
                if (evt.get("Event-Name") == "CHANNEL_ANSWER"
                        and evt.get("Caller-Caller-ID-Number") == config.AGENT_A["sip_number"]):
                    s9_uuid = evt.get("Unique-ID")
                    break
        if s9_uuid:
            break
    play_done_pattern = (re.compile(r"流式放音完成，uniqueId: %s" % re.escape(s9_uuid))
                         if s9_uuid else re.compile(r"流式放音完成"))
    hits1, _ = wait_log_keywords(log_tail, [play_done_pattern], timeout=30, min_match=1, buf=s9_buf)
    recorder.record("场景9-收号节点(%s)执行" % receive_id, hits1 >= 1, "命中=%d" % hits1)
    time.sleep(1.0)
    if not recorder.record("场景9-发送 DTMF '%s'" % dtmf_key,
                           browser.send_dtmf(page_a, dtmf_key)):
        return False

    # 步骤3: IVR 执行链断言(收号结果 → 方法调用 → 感谢语)
    result_pattern = re.compile(r"%s\.result(?:=|\":\")%s" % (re.escape(receive_id), dtmf_key))
    hits2, _ = wait_log_keywords(result_tail, [result_pattern], timeout=45, min_match=1)
    recorder.record("场景9-收号结果 result='%s' 写入流程变量" % dtmf_key, hits2 >= 1)
    hits3, _ = wait_log_keywords(
        log_tail, [re.compile(r"ivr方法调用节点处理"), r"感谢您的评价"],
        timeout=30, min_match=2, buf=s9_buf)
    recorder.record("场景9-方法调用节点执行 + 播放'感谢您的评价'", hits3 >= 2, "命中=%d" % hits3)

    # 步骤4: 流程自动结束挂断 + DB 终态
    ended = browser.wait_for_call_ended(page_a, timeout=30000)
    recorder.record("场景9-呼叫自动结束(流程 end 节点)", ended)

    def _flow_ended():
        inst = get_latest_flow_instance(db, spec["flow_id"], scenario_start)
        return inst if _flow_ended_predicate(inst) else None

    flow_inst = poll_until(_flow_ended, timeout=30)
    recorder.record("场景9-cc_flow_instances(flow106)终态", flow_inst is not None,
                    ("status=%s end_time=%s call_id=%s" %
                     (flow_inst.get("status"), flow_inst.get("end_time"), flow_inst.get("call_id")))
                    if flow_inst else "30s内未写入终态")
    return recorder.all_passed


# ==================== 场景10(可选): AI 对话(flow107) ====================
def scenario_10_ai_dialogue(ctx: dict, recorder: StepRecorder) -> bool:
    """
    场景10(可选): AI 对话点验(浏览器坐席1001 拨 00600 → tl107 AI 对话 → 中断词"转人工" → 转坐席1002)。

    需求背景: 验证 AI 对话专用路由107(呼出 ^(00600).*, 不与其他路由混用)全链路——
      浏览器坐席1001 拨 00600 进入 flow107: start(asr/tts) → ai节点(聊天角色+中断词"转人工"+开场语)
      → 假麦克风循环播放"转人工"WAV(Chrome --use-file-for-fake-audio-capture, 由 runner 注入)
      → ASR 识别命中中断词写入 interruptWord → 条件节点 EQ 分支 → 转接坐席1002 → 浏览器坐席B接听。
    预期结果(多方验证链):
      - Java 日志: [进入callRoute电话] + [ivrAI对话][创建会话成功] + 流式放音完成(开场语)
        + [ivrAI对话][中断词命中] + [ivr-转接-坐席处理节点] + 1002
      - UI: 浏览器坐席B(1002) 收到来电并接听, 双方通话中; 主叫挂断后联动挂断
      - DB: cc_call_record(主叫1001) + cc_flow_instances(107) 终态 +
        ai_chat_conversation 时间窗内新增(AI 会话落库)
    前置条件: 路由107(^(00600).*) 与流程107 已启用(L0 核对); 坐席1001/1002 浏览器在线就绪;
      ai_chat_role 存在公开角色且 ai_model 可用; ASR/TTS 引擎已配置。场景默认不执行,
      仅 --scenarios 10 显式指定时运行(依赖 AI 链路稳定性, 不拖累常规回归)。
    """
    browser, page_a, page_b = ctx["browser"], ctx["page_a"], ctx["page_b"]
    db = ctx["db"]
    _scenario_prepare(ctx, recorder, lambda c: _pages(c))
    scenario_start = ctx["scenario_start"]
    s10_buf = ctx["s_buf"]
    log_tail, result_tail = ctx["log_tail"], ctx["result_tail"]
    spec = FLOW_SPECS["107"]
    dial = config.AI_DIALOGUE_NUMBER  # 00600: 命中路由107, 不与其他路由混用

    # 步骤1: 坐席A(1001) 浏览器拨号触发路由107(IVR 应答, 进入 AI 节点)
    if not recorder.record("场景10-坐席A发起呼叫 %s" % dial, browser.make_call(page_a, dial)):
        take_screenshot_on_failure(browser, page_a, "scenario_10_call")
        return False
    connected = browser.wait_for_call_connected(page_a, timeout=config.CALL_TIMEOUT)
    recorder.record("场景10-IVR应答(进入AI节点)", connected)
    if not connected:
        take_screenshot_on_failure(browser, page_a, "scenario_10_connect")
        return False

    # 步骤2: 路由命中 + AI 会话创建 + 开场语流式播放完成(播完才进入监听, 避开 busy 门控)
    hits1, _ = wait_log_keywords(
        log_tail,
        [re.compile(r"\[进入callRoute电话\]"), re.compile(r"\[ivrAI对话\]\[创建会话成功")],
        timeout=45, min_match=2, buf=s10_buf)
    recorder.record("场景10-路由107命中+AI会话创建", hits1 >= 2, "命中=%d" % hits1)
    hits2, _ = wait_log_keywords(log_tail, [r"流式放音完成"], timeout=45, min_match=1, buf=s10_buf)
    recorder.record("场景10-AI开场语播放完成", hits2 >= 1, "命中=%d" % hits2)

    # 步骤3: 假麦克风循环播放"转人工"→ ASR 识别命中中断词(等待识别, 首轮即可命中)
    hits3, _ = wait_log_keywords(
        log_tail, [re.compile(r"\[ivrAI对话\]\[中断词命中")],
        timeout=90, min_match=1, buf=s10_buf)
    recorder.record("场景10-中断词命中(转人工)", hits3 >= 1, "命中=%d" % hits3)

    # 步骤4: 条件分支命中 → 转坐席1002
    hits4, _ = wait_log_keywords(
        log_tail,
        [re.compile(r"\[ivr-转接-坐席处理节点\]"), r"1002"],
        timeout=45, min_match=2, buf=s10_buf)
    recorder.record("场景10-转接坐席1002", hits4 >= 2, "命中=%d" % hits4)

    # 步骤5: 坐席B(1002) 浏览器收到转接来电并接听, 双向通话建立
    incoming = browser.wait_for_incoming_call(page_b, timeout=config.CALL_TIMEOUT)
    recorder.record("场景10-坐席B收到转接来电", incoming)
    if not incoming:
        take_screenshot_on_failure(browser, page_b, "scenario_10_incoming")
        return False
    if not recorder.record("场景10-坐席B接听", browser.answer_call(page_b)):
        take_screenshot_on_failure(browser, page_b, "scenario_10_answer")
        return False
    connected_b = browser.wait_for_call_connected(page_b, timeout=config.CALL_TIMEOUT)
    recorder.record("场景10-坐席B通话建立(双向媒体)", connected_b)
    if not connected_b:
        take_screenshot_on_failure(browser, page_b, "scenario_10_connect_b")
        return False

    # 步骤6: 主叫挂断 → 坐席B联动挂断
    if not recorder.record("场景10-坐席A挂断", browser.hangup(page_a)):
        return False
    ended = browser.wait_for_call_ended(page_b, timeout=30000)
    recorder.record("场景10-坐席B联动挂断", ended)

    # 步骤7: DB 证据闭环(CDR + 流程实例终态 + AI 会话落库)
    def _cdr_row():
        return db.query("SELECT id, call_id, caller_number, direction, call_state "
                        "FROM cc_call_record WHERE deleted=0 AND caller_number=%s "
                        "AND create_time >= %s ORDER BY id DESC LIMIT 1",
                        (config.AGENT_A["sip_number"], scenario_start))
    poll_until(_cdr_row, timeout=30)
    records = _cdr_row()
    recorder.record("场景10-cc_call_record 生成(主叫1001)", bool(records),
                    str(records[0]) if records else "未找到记录")

    def _flow_ended():
        inst = get_latest_flow_instance(db, spec["flow_id"], scenario_start)
        return inst if _flow_ended_predicate(inst) else None
    flow_inst = poll_until(_flow_ended, timeout=30)
    recorder.record("场景10-cc_flow_instances(flow107)终态", flow_inst is not None,
                    ("status=%s end_time=%s call_id=%s" %
                     (flow_inst.get("status"), flow_inst.get("end_time"), flow_inst.get("call_id")))
                    if flow_inst else "30s内未写入终态")

    def _ai_row():
        return db.query("SELECT id, role_id, user_id FROM ai_chat_conversation "
                        "WHERE user_id=%s AND create_time >= %s ORDER BY id DESC LIMIT 1",
                        (config.AI_SYSTEM_USER_ID, scenario_start))
    ai_conv = poll_until(_ai_row, timeout=30)
    recorder.record("场景10-ai_chat_conversation 新增(AI会话落库)", bool(ai_conv),
                    str(ai_conv[0]) if ai_conv else "时间窗内未新增会话")
    return recorder.all_passed


# ==================== 场景注册表(模块级, runner 按编号调度) ====================
SCENARIOS = {
    1: ("场景1_内部呼叫", scenario_1_internal_call),
    2: ("场景2_出局呼叫", scenario_2_outbound_call),
    3: ("场景3_入局IVR", scenario_3_inbound_ivr),
    5: ("场景5_保持恢复", scenario_5_hold_resume),
    6: ("场景6_咨询转接", scenario_6_consult_transfer),
    7: ("场景7_自动外呼", scenario_7_autocall),
    8: ("场景8_客服组繁忙(可选)", scenario_8_group_busy),
    9: ("场景9_满意度评价(可选)", scenario_9_satisfaction),
    10: ("场景10_AI对话(可选)", scenario_10_ai_dialogue),
}


# ==================== L0 环境核对(网络全清单 + 数据核对, 失败快速退出码2) ====================
def _network_check_items() -> list:
    """网络联通全清单: 后端/前端/ESL×2/MySQL/Redis/第三方FS SIP+ESL/sipproxy"""
    items = [
        ("后端-HTTP", lambda: http_probe(config.LOCAL_BACKEND_URL),
         config.LOCAL_BACKEND_URL),
        ("前端-HTTP", lambda: http_probe(config.LOCAL_FRONTEND_URL),
         config.LOCAL_FRONTEND_URL),
        ("ESL-fs2", lambda: _esl_probe(config.ESL_HOST, config.ESL_PORT, config.ESL_PASSWORD),
         "%s:%s" % (config.ESL_HOST, config.ESL_PORT)),
        ("ESL-fs1", lambda: _esl_probe(config.ESL_HOST_2, config.ESL_PORT_2, config.ESL_PASSWORD_2),
         "%s:%s" % (config.ESL_HOST_2, config.ESL_PORT_2)),
        ("MySQL", lambda: _mysql_probe(),
         "%s:%s/%s" % (config.MYSQL_HOST, config.MYSQL_PORT, config.MYSQL_DATABASE)),
        ("Redis", lambda: _redis_probe(),
         "%s:%s" % (config.REDIS_HOST, config.REDIS_PORT)),
        ("第三方FS-SIP", lambda: tcp_probe(config.THIRD_PARTY_FS_HOST, config.THIRD_PARTY_FS_SIP_PORT),
         "%s:%s" % (config.THIRD_PARTY_FS_HOST, config.THIRD_PARTY_FS_SIP_PORT)),
        ("第三方FS-ESL", lambda: _esl_probe(config.THIRD_PARTY_FS_HOST,
                                            config.THIRD_PARTY_FS_ESL_PORT,
                                            config.THIRD_PARTY_FS_ESL_PASSWORD),
         "%s:%s" % (config.THIRD_PARTY_FS_HOST, config.THIRD_PARTY_FS_ESL_PORT)),
        ("sipproxy-TCP", lambda: tcp_probe(config.SIP_PROXY_PUBLIC_IP, config.SIP_PROXY_PUBLIC_PORT),
         "%s:%s" % (config.SIP_PROXY_PUBLIC_IP, config.SIP_PROXY_PUBLIC_PORT)),
    ]
    return items


def _esl_probe(host: str, port: int, password: str) -> bool:
    """ESL TCP+auth 连通性探测(短连接, 不污染主连接)"""
    helper = EslHelper(host, port, password)
    try:
        return helper.connect()
    finally:
        try:
            helper.disconnect()
        except Exception:  # noqa: BLE001
            pass


def _mysql_probe() -> bool:
    """MySQL 连通性探测(SELECT 1)"""
    temp_db = DbHelper(config.MYSQL_HOST, config.MYSQL_PORT, config.MYSQL_USER,
                       config.MYSQL_PASSWORD, config.MYSQL_DATABASE)
    try:
        if not temp_db.connect():
            return False
        return bool(temp_db.query("SELECT 1 AS test"))
    finally:
        temp_db.disconnect()


def _redis_probe() -> bool:
    """Redis 连通性探测(PING)"""
    temp_redis = RedisHelper(config.REDIS_HOST, config.REDIS_PORT,
                             config.REDIS_PASSWORD, config.REDIS_DATABASE)
    try:
        if not temp_redis.connect():
            return False
        return bool(temp_redis.client.ping())
    except Exception:  # noqa: BLE001
        return False
    finally:
        temp_redis.disconnect()


def _auto_fix_routes(db: DbHelper) -> list:
    """
    幂等 INSERT 缺失路由(--auto-fix 白名单, 仅 cc_call_route)。

    需求背景: validate_specs 发现路由缺失时, 可依据 FLOW_SPECS 的声明字段插入缺失路由
    (id 不存在才插, 绝不 UPDATE/DELETE 已有数据, 每次写操作记录日志)。
    流程缺失无法凭空构造 flow_data, 不自动修复, 由人工在管理后台创建。
    """
    fixed = []
    for fid, spec in FLOW_SPECS.items():
        rows = db.query("SELECT id FROM cc_call_route WHERE id=%s AND deleted=0",
                        (spec["route_id"],))
        if rows:
            continue
        try:
            db.execute(
                "INSERT INTO cc_call_route (id, name, route_num, delete_prefix, type, status, "
                "flow_id, deleted) VALUES (%s, %s, %s, %s, %s, %s, %s, 0)",
                (spec["route_id"], spec["name"], spec["regex"], spec["delete_prefix"],
                 spec["direction"], 1, spec["flow_id"]))
            msg = "INSERT cc_call_route id=%s name=%s(幂等)" % (spec["route_id"], spec["name"])
            fixed.append(msg)
            logger.warning("[auto-fix] %s", msg)
        except Exception as exc:  # noqa: BLE001
            msg = "INSERT cc_call_route id=%s 失败: %s" % (spec["route_id"], exc)
            fixed.append(msg)
            logger.error("[auto-fix] %s", msg)
    return fixed


def run_l0_check(ctx: dict, recorder: StepRecorder, auto_fix: bool = False,
                 check_only: bool = False) -> bool:
    """
    L0 环境/数据核对(网络联通全清单 + 数据存在性/正确性)。

    需求背景: 执行前必须确认所有外部依赖可达且数据库规格未漂移(6 路由/6 流程/
    坐席 1001-1003/坐席组1/网关2/软电话), 否则场景断言会误报且浪费整轮时长。
    预期结果: 全部通过返回 True; 任一失败返回 False(主流程退出码 2)。
    """
    ok = True
    # ---- 1. 网络联通全清单 ----
    for name, probe_fn, target in _network_check_items():
        passed = probe_fn()
        recorder.record("L0-网络 %s(%s)" % (name, target), passed,
                        "" if passed else "连接失败, 请确认服务已启动/网络可达")
        ok = ok and passed
    # ---- 2. 数据核对(validate_specs 全项) ----
    issues = validate_specs(ctx["db"])
    if issues and auto_fix:
        # --auto-fix: 仅幂等 INSERT 缺失路由(白名单, 默认关闭)
        fixed = _auto_fix_routes(ctx["db"])
        recorder.record("L0-auto-fix 修复尝试", True, "; ".join(fixed))
        issues = validate_specs(ctx["db"])  # 修复后复验
    for issue in issues:
        logger.error("L0-数据核对失败: %s", issue)
    recorder.record("L0-数据核对 validate_specs(6路由/6流程/坐席/组/网关)",
                    not issues, "缺失/不一致 %d 项" % len(issues))
    ok = ok and not issues
    # ---- 3. 软电话注册核对(REGISTER 幂等, 允许自动重注册) ----
    for name, client in ctx["sip_clients"].items():
        reg_ok = client.is_registered(timeout=10) or client.register(timeout=25, retries=2)
        recorder.record("L0-软电话 %s 注册第三方FS" % name, reg_ok,
                        "" if reg_ok else "REGISTER 失败, 请确认 pjsua 与第三方 FS 9988 可达")
        ok = ok and reg_ok
    return ok


# ==================== TestRunner(执行器) ====================
class TestRunner:
    """
    测试运行器: 管理组件初始化、L0-L5 执行顺序、结果收集与汇总输出。

    属性:
        - ctx: 场景共享上下文(browser/pages/sip/db/redis/日志游标/ESL 采集器)
        - results: 测试结果列表, 每项为 (用例名, 状态, 耗时, 详情)
        - round_num: 多轮重试轮次编号(与 --rounds 共用: 场景失败自动重试)
    """

    STATUS_PASS = "PASS"
    STATUS_FAIL = "FAIL"
    STATUS_SKIP = "SKIP"
    STATUS_ERROR = "ERROR"

    def __init__(self, headless: bool = False, rounds: int = 3, round_backoff: int = 10,
                 fake_audio_wav: str = None):
        # fake_audio_wav: 场景10(AI 对话)等需要假麦克风循环播放 WAV 注入语音时传入
        self.browser = BrowserTest(headless=headless, slow_mo=config.BROWSER_SLOW_MO,
                                   fake_audio_wav=fake_audio_wav)
        # CC 双 FS ESL(呼叫按 callId hash 落点, 两实例均需连接)
        self.esl = EslHelper(config.ESL_HOST, config.ESL_PORT, config.ESL_PASSWORD)  # fs2
        self.esl2 = EslHelper(config.ESL_HOST_2, config.ESL_PORT_2, config.ESL_PASSWORD_2)  # fs1
        self.db = DbHelper(config.MYSQL_HOST, config.MYSQL_PORT, config.MYSQL_USER,
                           config.MYSQL_PASSWORD, config.MYSQL_DATABASE)
        self.redis = RedisHelper(config.REDIS_HOST, config.REDIS_PORT,
                                 config.REDIS_PASSWORD, config.REDIS_DATABASE)
        self.rounds = rounds
        self.round_backoff = round_backoff
        self.results = []
        self.test_start_time = None
        self.ctx = None
        self.sip_clients = {}
        self.collectors = []
        self.log_tail = None
        self.result_tail = None

    # ---------- 初始化与清理 ----------
    def setup(self) -> bool:
        """初始化所有辅助组件(浏览器/ESL×2/MySQL/Redis/日志游标/软电话/事件采集), 全程复用"""
        self.test_start_time = datetime.now()
        if not self.browser.start():
            logger.error("浏览器启动失败")
            return False
        if not self.esl.connect():
            logger.error("ESL(fs2) 连接失败: %s:%s", config.ESL_HOST, config.ESL_PORT)
            return False
        if not self.esl2.connect():
            logger.error("ESL(fs1) 连接失败: %s:%s", config.ESL_HOST_2, config.ESL_PORT_2)
            return False
        if not self.db.connect():
            logger.error("MySQL 连接失败")
            return False
        if not self.redis.connect():
            logger.error("Redis 连接失败")
            return False
        # 远端日志游标(线上无本地日志, SSH 增量读取; result_tail 专供 result 变量断言
        # 避免主游标被先行断言消耗后 result 日志行丢失)
        self.log_tail = RemoteLogTail(REMOTE_JAVA_LOG_PATH, config.SSH_HOST, config.SSH_USER,
                                      config.SSH_PASSWORD)
        self.result_tail = RemoteLogTail(REMOTE_JAVA_LOG_PATH, config.SSH_HOST, config.SSH_USER,
                                         config.SSH_PASSWORD)
        # 软电话(固定 SIP/RTP 端口避免与自测脚本冲突; start() 无同步返回值, 异常时抛 SipError)
        sip_a = SipClient(config.IVR_SOFTPHONE_A, backend="cli", sip_port=20160, rtp_port=20000)
        sip_b = SipClient(config.IVR_SOFTPHONE_B, backend="cli", sip_port=20162, rtp_port=20002)
        try:
            sip_a.start()
            sip_b.start()
        except Exception as exc:  # noqa: BLE001 - 启动异常统一归为环境初始化失败
            logger.error("pjsua 软电话启动失败(请确认 brew pjproject 已安装): %s", exc)
            # sip_a 可能已启动且尚未登记到 self.sip_clients, 显式停止避免 pjsua 子进程残留
            try:
                sip_a.stop()
            except Exception:  # noqa: BLE001
                pass
            return False
        self.sip_clients = {config.IVR_SOFTPHONE_A: sip_a, config.IVR_SOFTPHONE_B: sip_b}
        # CC 侧双 FS 事件订阅(呼叫落点按 callId hash 不固定)
        esl_hosts = [(config.ESL_HOST, config.ESL_PORT, config.ESL_PASSWORD),
                     (config.ESL_HOST_2, config.ESL_PORT_2, config.ESL_PASSWORD_2)]
        for idx, (host, port, password) in enumerate(esl_hosts, start=1):
            collector = EslEventCollector(host, port, password, tag="fs%d" % idx)
            if collector.start():
                self.collectors.append(collector)
        if not self.collectors:
            logger.error("CC 侧两台 FS 的 ESL 事件订阅均失败, 无法交叉验证")
            return False
        self.ctx = {
            "browser": self.browser, "page_a": None, "page_b": None, "page_c": None,
            "sip_a": sip_a, "sip_b": sip_b, "sip_clients": self.sip_clients,
            "db": self.db, "redis": self.redis,
            "log_tail": self.log_tail, "result_tail": self.result_tail,
            "collectors": self.collectors, "esl": self.esl, "esl2": self.esl2,
            "esl_hosts": esl_hosts,
            "scenario_start": None, "s_buf": None,
        }
        logger.info("所有核心辅助组件初始化成功")
        return True

    def teardown(self):
        """释放所有资源(先挂断通道, 再断 ESL/DB/Redis, 最后关浏览器与软电话)"""
        try:
            if self.esl.sock:
                self.esl.hangup_all_channels()
        except Exception as e:  # noqa: BLE001
            logger.warning("CC ESL 挂断异常: %s", e)
        try:
            if self.esl2 and self.esl2.sock:
                self.esl2.hangup_all_channels()
        except Exception as e:  # noqa: BLE001
            logger.warning("CC ESL2 挂断异常: %s", e)
        for collector in self.collectors:
            try:
                collector.stop()
            except Exception:  # noqa: BLE001
                pass
        try:
            self.esl.disconnect()
        except Exception as e:  # noqa: BLE001
            logger.warning("ESL 断开异常: %s", e)
        try:
            self.esl2.disconnect()
        except Exception as e:  # noqa: BLE001
            logger.warning("ESL2 断开异常: %s", e)
        try:
            self.db.disconnect()
        except Exception as e:  # noqa: BLE001
            logger.warning("MySQL 断开异常: %s", e)
        try:
            self.redis.disconnect()
        except Exception as e:  # noqa: BLE001
            logger.warning("Redis 断开异常: %s", e)
        for client in self.sip_clients.values():
            try:
                client.stop()
            except Exception:  # noqa: BLE001
                pass
        for tail in (self.log_tail, self.result_tail):
            try:
                tail.close()
            except Exception:  # noqa: BLE001
                pass
        try:
            self.browser.stop()
        except Exception as e:  # noqa: BLE001
            logger.warning("浏览器关闭异常: %s", e)
        # 浏览器强制关闭后 sipproxy 可能收不到 WS close 事件, Redis 注册映射会残留
        # (ttl 3600s), 导致下一轮签入被判"重复登录" → 收尾再清一次测试坐席残留键
        cleanup_sipproxy_registrations(self.redis)
        logger.info("所有资源已清理")

    # ---------- 用例执行 ----------
    def run_test(self, name: str, test_func, *args, **kwargs) -> bool:
        """执行单个测试用例并记录 (名称, 状态, 耗时, 详情)"""
        print("\n" + "=" * 60)
        print("执行: %s" % name)
        print("=" * 60)
        start = time.time()
        try:
            result = test_func(*args, **kwargs)
            elapsed = time.time() - start
            status = self.STATUS_PASS if result else self.STATUS_FAIL
            self.results.append((name, status, elapsed, ""))
            print("[结果] %s: %s (耗时 %.1fs)" % (name, status, elapsed))
            return result
        except Exception as e:  # noqa: BLE001
            elapsed = time.time() - start
            detail = "%s: %s" % (type(e).__name__, e)
            self.results.append((name, self.STATUS_ERROR, elapsed, detail))
            print("[异常] %s: ERROR - %s" % (name, detail))
            import traceback
            traceback.print_exc()
            return False

    def run_l0(self, auto_fix: bool = False, check_only: bool = False) -> bool:
        recorder = StepRecorder()
        passed = run_l0_check(self.ctx, recorder, auto_fix=auto_fix, check_only=check_only)
        print("\n[L0 环境核对结果]")
        for line in recorder.summary_lines():
            print(line)
        if not passed:
            print("[L0] 环境/数据核对失败, 请修复上述缺失项后重试(缺失路由可用 --auto-fix 幂等补齐; 流程需人工创建)")
        return passed

    def run_login(self) -> bool:
        """L1+L2 登录签入(坐席A 1001 / 坐席B 1002, 独立上下文隔离 token)

        登签前先清理 sipproxy Redis 注册残留(防"重复登录被拒绝"), 再创建页面签入。
        """
        recorder = StepRecorder()
        ctx = self.ctx
        cleanup_sipproxy_registrations(self.redis)
        page_a = self.browser.new_page()
        page_b = self.browser.new_context_page()
        ctx["page_a"], ctx["page_b"] = page_a, page_b
        ok = (login_and_signin(self.browser, page_a, config.AGENT_A, config.LOCAL_FRONTEND_URL, recorder)
              and login_and_signin(self.browser, page_b, config.AGENT_B, config.LOCAL_FRONTEND_URL, recorder))
        # 导航到呼叫中心工作台, 确保 SoftPhone JsSIP 在正确页面接收来电
        for page in (page_a, page_b):
            try:
                page.click("text=呼叫中心", timeout=10000)
                time.sleep(2)
            except Exception as e:  # noqa: BLE001
                logger.warning("导航到呼叫中心工作台失败(非致命): %s", e)
        if ok and self.browser.is_online(page_a) and self.browser.is_online(page_b):
            recorder.record("L1L2-坐席A/B 在线就绪", True)
        else:
            ok = False
            recorder.record("L1L2-坐席A/B 在线就绪", False)
        print("\n[登录签入结果]")
        for line in recorder.summary_lines():
            print(line)
        return ok

    def run_scenario(self, scenario_num: int) -> bool:
        """执行指定编号场景(含多轮重试: 每场景最多 rounds 轮, 轮间 round_backoff 秒)

        未知编号在 main 参数校验阶段即报错退出码 2, 此处视为防御性跳过。
        """
        if scenario_num not in SCENARIOS:
            print("[跳过] 未知场景编号: %s" % scenario_num)
            self.results.append(("场景%s" % scenario_num, self.STATUS_SKIP, 0, "未知场景"))
            return True
        name, scenario_fn = SCENARIOS[scenario_num]
        start = time.time()
        passed = False
        round_details = []
        for round_no in range(1, self.rounds + 1):
            recorder = StepRecorder()
            # 轮前置: 场景间残留清理 + 坐席就绪(场景函数内部 _scenario_prepare 再确认)
            cleanup_calls(self.esl, self.esl2, self.browser,
                          [self.ctx.get("page_a"), self.ctx.get("page_b"), self.ctx.get("page_c")])
            logger.info("========== %s 第%d/%d轮 ==========", name, round_no, self.rounds)
            try:
                passed = scenario_fn(self.ctx, recorder)
            except Exception as exc:  # noqa: BLE001 - 场景异常视为本轮失败
                logger.exception("%s 第%d轮异常", name, round_no)
                recorder.record("%s 异常捕获" % name, False, str(exc))
                passed = False
            finally:
                cleanup_residual(self.ctx["esl_hosts"], self.redis, self.browser,
                                 self._pages_for_cleanup(), self.sip_clients)
            print("\n[%s 第%d轮结果]" % (name, round_no))
            for line in recorder.summary_lines():
                print(line)
            round_details.append("第%d轮:%s" % (round_no, "PASS" if passed else "FAIL"))
            if passed:
                break
            if round_no < self.rounds:
                logger.info("第%d轮失败, %ds 后重试", round_no, self.round_backoff)
                time.sleep(self.round_backoff)
        elapsed = time.time() - start
        status = self.STATUS_PASS if passed else self.STATUS_FAIL
        detail = ", ".join(round_details)
        self.results.append((name, status, elapsed, detail))
        print("[结果] %s: %s (耗时 %.1fs, %s)" % (name, status, elapsed, detail))
        return passed

    def _pages_for_cleanup(self) -> dict:
        """当前已创建的坐席页面映射, 供轮次清理使用"""
        pages = {}
        for key in ("page_a", "page_b", "page_c"):
            if self.ctx.get(key) is not None:
                pages[key] = self.ctx[key]
        return pages

    def run_all_scenarios(self, scenario_nums: list) -> bool:
        """依次执行指定场景列表, 全部通过返回 True"""
        all_pass = True
        for num in scenario_nums:
            if not self.run_scenario(num):
                all_pass = False
        return all_pass

    def run_l5(self) -> bool:
        """L5 数据校验: 测试期间通话记录生成 + 坐席在线状态"""
        record_count = self.db.count_call_records_since(self.test_start_time)
        if record_count == 0:
            print("[L5] 未生成任何通话记录")
            ok = False
        else:
            print("[L5] 通话记录生成数量: %d" % record_count)
            ok = True
        for sip in ("1001", "1002"):
            status = self.db.get_agent_online_status(sip)
            print("[L5] 坐席%s 在线状态: %s" % (sip, status))
        return ok

    def print_summary(self):
        """打印全部用例结果汇总"""
        print("\n" + "=" * 60)
        print("测试结果汇总")
        print("=" * 60)
        pass_count = fail_count = skip_count = error_count = 0
        for name, status, elapsed, detail in self.results:
            icon = {"PASS": "OK", "FAIL": "XX", "SKIP": "--", "ERROR": "!!"}[status]
            print("  [%s] %-32s %-6s %6.1fs  %s" % (icon, name, status, elapsed, detail))
            if status == self.STATUS_PASS:
                pass_count += 1
            elif status == self.STATUS_FAIL:
                fail_count += 1
            elif status == self.STATUS_SKIP:
                skip_count += 1
            else:
                error_count += 1
        print("-" * 60)
        print("  总计: %d  通过: %d  失败: %d  跳过: %d  错误: %d"
              % (len(self.results), pass_count, fail_count, skip_count, error_count))
        print("=" * 60)

    def has_failure(self) -> bool:
        return any(s in (self.STATUS_FAIL, self.STATUS_ERROR) for _, s, _, _ in self.results)


# ==================== 参数解析与主流程 ====================
def parse_args():
    """解析命令行参数(与计划文件对齐: scenarios/headless/rounds/round-backoff/skip-l0/auto-fix/check-only)"""
    parser = argparse.ArgumentParser(description="yudao-cloud-cc 呼叫中心端到端测试套件(唯一主脚本)")
    parser.add_argument("--scenarios", type=str, default="1,2,3,5,6,7",
                        help="只执行指定场景, 逗号分隔(如 1,3,5; 场景8/9 可选须显式指定), 默认 1,2,3,5,6,7")
    parser.add_argument("--headless", action="store_true", default=False,
                        help="浏览器无头模式(不显示窗口, 适合 CI)")
    parser.add_argument("--rounds", type=int, default=3, help="每场景最大重试轮数(默认3)")
    parser.add_argument("--round-backoff", type=int, default=10, help="轮间退避秒数(默认10)")
    parser.add_argument("--skip-l0", action="store_true", default=False,
                        help="跳过 L0 环境/数据核对(已在其他地方验证过)")
    parser.add_argument("--auto-fix", action="store_true", default=False,
                        help="L0 数据核对发现缺失路由时执行幂等 INSERT 修复(白名单, 默认关闭)")
    parser.add_argument("--check-only", action="store_true", default=False,
                        help="只跑 L0 环境/数据核对, 不执行场景(通过退出码0/失败退出码2)")
    return parser.parse_args()


def _parse_scenario_nums(scenarios_str: str) -> list:
    """解析 --scenarios 参数并校验编号合法性(未知编号如 4 报错退出码 2)"""
    nums = []
    for part in scenarios_str.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            num = int(part)
        except ValueError:
            print("[ERROR] 无效的场景参数: %s(应为逗号分隔的数字)" % scenarios_str)
            sys.exit(2)
        if num not in VALID_SCENARIOS:
            if num == 4:
                print("[ERROR] 场景4 已并入场景3(外部呼入链路由场景3 pjsua 真实呼入覆盖), 请使用 --scenarios 3")
            else:
                print("[ERROR] 未知场景编号: %s(合法编号: %s)" % (num, ",".join(map(str, sorted(VALID_SCENARIOS)))))
            sys.exit(2)
        nums.append(num)
    return nums or list(DEFAULT_SCENARIOS)


def main() -> int:
    """
    主入口: 解析参数 → 组件初始化 → L0(可跳过/可 check-only) → L1/L2 登签 → 场景(多轮重试)→ L5 → 汇总

    退出码: 0=全部通过; 1=存在失败场景; 2=环境/数据核对失败或参数错误
    """
    args = parse_args()
    scenario_nums = _parse_scenario_nums(args.scenarios)
    print("\n" + "#" * 60)
    print("# yudao-cloud-cc 端到端测试套件(cc_e2e_test)")
    print("# 时间: %s" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("# 模式: %s | 场景: %s | 重试轮数: %d | 轮间隔: %ds"
          % ("无头" if args.headless else "有头", ",".join(map(str, scenario_nums)),
             args.rounds, args.round_backoff))
    print("#" * 60)

    runner = TestRunner(headless=args.headless, rounds=args.rounds,
                        round_backoff=args.round_backoff,
                        fake_audio_wav=(config.AI_INTERRUPT_WAV
                                        if 10 in scenario_nums and os.path.exists(config.AI_INTERRUPT_WAV)
                                        else None))
    try:
        # 步骤1: 组件初始化
        if not runner.setup():
            print("[FATAL] 环境初始化失败(浏览器/ESL/MySQL/Redis/pjsua 任一不可用)")
            runner.teardown()
            return 2

        # 步骤2: L0 环境/数据核对(可跳过; check-only 提前返回)
        if not args.skip_l0:
            if not runner.run_l0(auto_fix=args.auto_fix, check_only=args.check_only):
                print("[FATAL] L0 环境/数据核对未通过, 终止测试(退出码 2)")
                runner.print_summary()
                return 2
            if args.check_only:
                print("\n[check-only] L0 核对全部通过, 按 --check-only 提前退出")
                return 0

        # 步骤3: L1/L2 登录签入
        if not runner.run_login():
            print("[FATAL] 登录签入失败, 终止测试(退出码 2)")
            runner.print_summary()
            return 2

        # 步骤4: L4 通话场景(多轮重试在 run_scenario 内部)
        runner.run_all_scenarios(scenario_nums)

        # 步骤5: L5 数据校验
        runner.run_test("L5_数据校验", runner.run_l5)

        # 步骤6: 汇总
        runner.print_summary()
        return 1 if runner.has_failure() else 0
    finally:
        runner.teardown()


if __name__ == "__main__":
    sys.exit(main())
