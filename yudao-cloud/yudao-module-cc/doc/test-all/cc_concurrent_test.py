#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
并发呼入压测脚本
================
通过 pjsua 批量登录第三方网关(FS <A服务器公网>:9988)账户(18600000000 起, 共 100 个),
发令枪并发呼叫 4001234(sipproxy 公网入局 -> route101 -> flow101 -> 转坐席组1),
分级(10/20/30/50/80/100, 可 --levels 覆盖)验证:

  1. 坐席组成员状态更新正确性(Redis fs:agent:status 轨迹 + DB online_status 一致性)
  2. 空闲坐席获取并发正确性(同一坐席被重复分配 -> 通话重复建立)
  3. 排队逻辑(--queue-test 临时把坐席组1 改为排队策略, 测完自动还原)
  4. 溢出分支行为(组1 现配置为全忙溢出转 IVR, 而其溢出目标 flow_id=1 在库中不存在)
  5. 每级成功/失败统计 + 失败原因分类, 汇总 Markdown/JSON 报告

使用方式(系统 python3.11 直跑, 无 venv):
    python3 cc_concurrent_test.py                          # 默认分级 10,20,30,50,80,100
    python3 cc_concurrent_test.py --levels 10              # 只跑 10 级(冒烟)
    python3 cc_concurrent_test.py --headless --levels 10,20,50,100
    python3 cc_concurrent_test.py --levels 10 --queue-test # 排队子测试(临时改组1 配置)
    python3 cc_concurrent_test.py --skip-l0                # 跳过 L0 环境核对

退出码约定:
    0 = 全部级通过; 1 = 存在失败级; 2 = 环境/数据核对失败或参数错误
"""
import argparse
import collections
import logging
import os
import re
import sys
import time
from datetime import datetime, timedelta

# ==================== 路径装配: 复用 ../common 与主脚本公共资产 ====================
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_COMMON_DIR = os.path.join(_THIS_DIR, "common")
for _p in (_COMMON_DIR, _THIS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import config  # noqa: E402
import cc_e2e_test as e2e  # noqa: E402 - 复用探针/日志游标/事件采集/清理等公共资产
from browser_test import BrowserTest  # noqa: E402
from concurrent_helpers import (AgentStatusSampler, ConcurrentReporter, InboundCallerPool,
                                STATUS_TEXT, AGENT_STATUS_KEY)  # noqa: E402
from db_helper import DbHelper  # noqa: E402
from esl_helper import EslHelper  # noqa: E402
from redis_helper import RedisHelper  # noqa: E402

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s")
logger = logging.getLogger("cc_concurrent")

# 远端后端日志路径(与主脚本一致)
REMOTE_JAVA_LOG_PATH = e2e.REMOTE_JAVA_LOG_PATH

# 坐席组1 成员分机号(flow101 转坐席组1, 数据库 cc_sys_agent_group_rel 已核对)
AGENT_GROUP_SIPS = ("1001", "1002", "1003")

# 流程101 转坐席组相关的后端日志关键词(供级末证据收集)
KW_GROUP_TRANSFER = re.compile(r"\[ivr-转接-转坐席组处理器\]\[转坐席组")
KW_QUEUE_NO_AGENT = re.compile(r"队列获取空闲坐席失败")
KW_QUEUE_TIMEOUT = re.compile(r"排队超时")
KW_QUEUE_JOINED = re.compile(r"队列获取空闲坐席失败|入队即播放|转接前提示音|排队等待|跳过放音继续排队")
# fsAcd 排队扫描异常(ClassCastException: Collections.singleton(agentIds) 的 multiGet 字段类型错误,
# 异常 message 为 null 故日志尾为空; 每 2s 扫描周期抛一次 -> 排队分配完全失效)
KW_QUEUE_EXCEPTION = re.compile(r"\[排队异常")
KW_OVERFLOW = re.compile(r"转IVR溢出策略")
# audioFork(TTS 流式放音)失败: 高并发下 mod_audio_fork 连接建立失败/流式播放超时,
# 导致 IVR 放音节点异常、流程无法推进到转坐席组(20 级实测瓶颈)
KW_AUDIOFORK_FAIL = re.compile(r"uuid_audio_fork 启动失败|audio fork 建立失败|流式放音完成但呼叫信息缺失")


def build_env(headless: bool = False) -> dict:
    """构建并发测试环境组件集合(浏览器/ESL×2/MySQL/Redis/日志游标/事件采集)"""
    browser = BrowserTest(headless=headless, slow_mo=config.BROWSER_SLOW_MO)
    esl = EslHelper(config.ESL_HOST, config.ESL_PORT, config.ESL_PASSWORD)          # fs2
    esl2 = EslHelper(config.ESL_HOST_2, config.ESL_PORT_2, config.ESL_PASSWORD_2)  # fs1
    db = DbHelper(config.MYSQL_HOST, config.MYSQL_PORT, config.MYSQL_USER,
                  config.MYSQL_PASSWORD, config.MYSQL_DATABASE)
    redis = RedisHelper(config.REDIS_HOST, config.REDIS_PORT,
                        config.REDIS_PASSWORD, config.REDIS_DATABASE)
    log_tail = e2e.RemoteLogTail(REMOTE_JAVA_LOG_PATH, config.SSH_HOST, config.SSH_USER,
                                 config.SSH_PASSWORD)
    result_tail = e2e.RemoteLogTail(REMOTE_JAVA_LOG_PATH, config.SSH_HOST, config.SSH_USER,
                                    config.SSH_PASSWORD)
    collectors = []
    esl_hosts = [(config.ESL_HOST, config.ESL_PORT, config.ESL_PASSWORD),
                 (config.ESL_HOST_2, config.ESL_PORT_2, config.ESL_PASSWORD_2)]
    # CHANNEL_CREATE 供并发场景统计坐席腿被分配次数(主脚本订阅集无此事件, 此处扩展)
    sub_events = list(e2e.EslEventCollector.SUBSCRIBE_EVENTS) + ["CHANNEL_CREATE"]
    for idx, (host, port, password) in enumerate(esl_hosts, start=1):
        collector = e2e.EslEventCollector(host, port, password, tag="fs%d" % idx)
        collector.SUBSCRIBE_EVENTS = sub_events  # 实例级覆盖订阅集
        # 100 级并发事件量远超默认 5000 上限, 扩容防事件溢出导致接通/振铃计数低估
        collector._events = collections.deque(maxlen=30000)  # noqa: SLF001
        if collector.start():
            collectors.append(collector)
    return {"browser": browser, "esl": esl, "esl2": esl2, "db": db, "redis": redis,
            "log_tail": log_tail, "result_tail": result_tail, "collectors": collectors,
            "esl_hosts": esl_hosts, "pages": {}, "agent_id_map": {}}


def teardown_env(env: dict) -> None:
    """释放全部环境组件(幂等)"""
    try:
        if env["esl"].sock:
            env["esl"].hangup_all_channels()
    except Exception as exc:  # noqa: BLE001
        logger.warning("ESL 挂断异常: %s", exc)
    try:
        if env["esl2"].sock:
            env["esl2"].hangup_all_channels()
    except Exception as exc:  # noqa: BLE001
        logger.warning("ESL2 挂断异常: %s", exc)
    for collector in env["collectors"]:
        try:
            collector.stop()
        except Exception:  # noqa: BLE001
            pass
    for helper in (env["esl"], env["esl2"]):
        try:
            helper.disconnect()
        except Exception:  # noqa: BLE001
            pass
    try:
        env["db"].disconnect()
    except Exception:  # noqa: BLE001
        pass
    try:
        env["redis"].disconnect()
    except Exception:  # noqa: BLE001
        pass
    try:
        env["browser"].stop()
    except Exception as exc:  # noqa: BLE001
        logger.warning("浏览器关闭异常: %s", exc)
    for tail in (env["log_tail"], env["result_tail"]):
        try:
            tail.close()
        except Exception:  # noqa: BLE001
            pass
    logger.info("并发测试环境组件已全部清理")


# ==================== L0 环境核对 ====================
def _esl_probe(host: str, port: int, password: str) -> bool:
    """ESL TCP+auth 连通性探测(短连接)"""
    helper = EslHelper(host, port, password)
    try:
        return helper.connect()
    finally:
        try:
            helper.disconnect()
        except Exception:  # noqa: BLE001
            pass


def run_l0_check(env: dict, recorder: e2e.StepRecorder, max_level: int) -> bool:
    """
    L0 环境核对: 网络全清单 + 第三方 FS 账户数(需 >= 最大并发级) + 坐席组1 配置读取。

    需求背景: 并发压测前必须确认外部依赖可达、第三方 FS 账户充足(不足 100 则
    100 级必然大面积注册失败被误判)、坐席组1 现配置可用, 否则分级结果无意义。
    预期结果: 全部通过返回 True; 任一失败返回 False(主流程退出码 2)。
    """
    ok = True
    network_items = [
        ("后端-HTTP", lambda: e2e.http_probe(config.LOCAL_BACKEND_URL), config.LOCAL_BACKEND_URL),
        ("前端-HTTP", lambda: e2e.http_probe(config.LOCAL_FRONTEND_URL), config.LOCAL_FRONTEND_URL),
        ("ESL-fs2", lambda: _esl_probe(config.ESL_HOST, config.ESL_PORT, config.ESL_PASSWORD),
         "%s:%s" % (config.ESL_HOST, config.ESL_PORT)),
        ("ESL-fs1", lambda: _esl_probe(config.ESL_HOST_2, config.ESL_PORT_2, config.ESL_PASSWORD_2),
         "%s:%s" % (config.ESL_HOST_2, config.ESL_PORT_2)),
        ("MySQL", lambda: _mysql_probe(), "%s:%s/%s" % (config.MYSQL_HOST, config.MYSQL_PORT,
                                                        config.MYSQL_DATABASE)),
        ("Redis", lambda: _redis_probe(), "%s:%s" % (config.REDIS_HOST, config.REDIS_PORT)),
        ("第三方FS-SIP", lambda: e2e.tcp_probe(config.THIRD_PARTY_FS_HOST, config.THIRD_PARTY_FS_SIP_PORT),
         "%s:%s" % (config.THIRD_PARTY_FS_HOST, config.THIRD_PARTY_FS_SIP_PORT)),
        ("第三方FS-ESL", lambda: _esl_probe(config.THIRD_PARTY_FS_HOST,
                                            config.THIRD_PARTY_FS_ESL_PORT,
                                            config.THIRD_PARTY_FS_ESL_PASSWORD),
         "%s:%s" % (config.THIRD_PARTY_FS_HOST, config.THIRD_PARTY_FS_ESL_PORT)),
        ("sipproxy-TCP", lambda: e2e.tcp_probe(config.SIP_PROXY_PUBLIC_IP, config.SIP_PROXY_PUBLIC_PORT),
         "%s:%s" % (config.SIP_PROXY_PUBLIC_IP, config.SIP_PROXY_PUBLIC_PORT)),
    ]
    for name, probe_fn, target in network_items:
        passed = probe_fn()
        recorder.record("L0-网络 %s(%s)" % (name, target), passed)
        ok = ok and passed

    # 第三方 FS 账户数核对(SSH + fs_cli list_users: 该 FS 的 ESL api 空间无 show/list 命令,
    # list_users 仅在 CLI 可用, 输出为 'userid|context|domain|...' 行首用户号格式)
    visible = _count_third_party_users()
    recorder.record("L0-第三方FS 注册表账户核对(%d 个, 需>=%d)" % (visible, max_level),
                    visible >= max_level)
    ok = ok and visible >= max_level

    # 坐席组1 配置读取(备份给排队子测试还原用)
    rows = env["db"].query("SELECT id, full_busy_type, overflow_type, overflow_value, "
                           "time_out, queue_length FROM cc_sys_agent_group WHERE id=1 AND deleted=0")
    if not rows:
        recorder.record("L0-坐席组1 配置读取", False, "坐席组1 不存在")
        ok = False
    else:
        env["group_config_backup"] = rows[0]
        recorder.record("L0-坐席组1 配置读取", True,
                        "full_busy=%s overflow_type=%s overflow_value=%s timeout=%ss queue_length=%s" % (
                            rows[0]["full_busy_type"], rows[0]["overflow_type"],
                            rows[0]["overflow_value"], rows[0]["time_out"], rows[0]["queue_length"]))
    return ok


def _count_third_party_users() -> int:
    """SSH 到第三方 FS 容器执行 fs_cli list_users, 返回注册表可见用户数(失败返回 0)"""
    import paramiko
    try:
        cli = paramiko.SSHClient()
        cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        cli.connect(hostname=config.SSH_HOST, username=config.SSH_USER,
                    password=config.SSH_PASSWORD, timeout=15,
                    look_for_keys=False, allow_agent=False)
        try:
            # 定位 9988 第三方 FS 容器(list_users 仅 CLI 可用, 经 docker exec fs_cli 执行)
            _, so, _ = cli.exec_command(
                "docker ps --format '{{.Names}}' | grep freeswitch | grep %s | head -1"
                % config.THIRD_PARTY_FS_SIP_PORT, timeout=10)
            container = so.read().decode().strip()
            if not container:
                logger.error("未找到第三方 FS 容器(端口 %s)", config.THIRD_PARTY_FS_SIP_PORT)
                return 0
            _, so, _ = cli.exec_command(
                "docker exec %s fs_cli -P %s -p %s -x 'list_users' 2>/dev/null"
                % (container, config.THIRD_PARTY_FS_ESL_PORT,
                   config.THIRD_PARTY_FS_ESL_PASSWORD), timeout=15)
            body = so.read().decode("utf-8", "replace")
            # list_users 行格式: 'userid|context|domain|...', 按行首用户号去重计数
            return len(set(re.findall(r"(?m)^(18\d{9})\|", body)))
        finally:
            cli.close()
    except Exception as exc:  # noqa: BLE001 - 核对失败返回 0 由上层判 FAIL
        logger.error("第三方 FS 账户数核对异常: %s", exc)
        return 0


def _mysql_probe() -> bool:
    temp = DbHelper(config.MYSQL_HOST, config.MYSQL_PORT, config.MYSQL_USER,
                    config.MYSQL_PASSWORD, config.MYSQL_DATABASE)
    try:
        if not temp.connect():
            return False
        return bool(temp.query("SELECT 1 AS test"))
    finally:
        temp.disconnect()


def _redis_probe() -> bool:
    temp = RedisHelper(config.REDIS_HOST, config.REDIS_PORT, config.REDIS_PASSWORD,
                       config.REDIS_DATABASE)
    try:
        if not temp.connect():
            return False
        return bool(temp.client.ping())
    except Exception:  # noqa: BLE001
        return False
    finally:
        temp.disconnect()


# ==================== 坐席登录与状态辅助 ====================
def load_agent_id_map(db: DbHelper) -> dict:
    """从数据库加载坐席分机 -> 坐席ID 映射(坐席组1 成员)"""
    rows = db.query("SELECT id, name FROM cc_sys_agent WHERE name IN ('1001','1002','1003') "
                    "AND deleted=0")
    return {str(r["name"]): int(r["id"]) for r in rows}


def login_all_agents(env: dict, recorder: e2e.StepRecorder) -> bool:
    """
    登录并签入坐席组1 的三名坐席(1001/1002/1003, 独立浏览器上下文)。

    需求背景: 并发呼入最终转接到坐席组1, 组内坐席必须在线且就绪(READY),
    否则所有呼叫都走"无空闲坐席"分支, 无法验证坐席状态流转。
    预期结果: 三个页面各自登录/签入/置就绪成功, 页面存入 env["pages"];
    同时挂载 console/pageerror 监听, 供无接听时定位前端振铃/弹窗链路。
    """
    browser = env["browser"]
    env.setdefault("page_console", {})
    ok = True
    agents = [config.AGENT_A, config.AGENT_B, config.AGENT_C]  # 1001/1002/1003
    for idx, agent in enumerate(agents):
        page = browser.new_page() if idx == 0 else browser.new_context_page()
        env["pages"][agent["sip_number"]] = page
        env["page_console"][agent["sip_number"]] = []
        page.on("console", lambda msg, sip=agent["sip_number"]: env["page_console"][sip].append(
            "[%s] %s" % (msg.type, msg.text)) if env["page_console"].get(sip) is not None else None)
        page.on("pageerror", lambda exc, sip=agent["sip_number"]: env["page_console"][sip].append(
            "[PAGEERROR] %s" % exc) if env["page_console"].get(sip) is not None else None)
        if not e2e.login_and_signin(browser, page, agent, config.LOCAL_FRONTEND_URL, recorder):
            ok = False
        try:
            page.click("text=呼叫中心", timeout=10000)
            time.sleep(1)
        except Exception as exc:  # noqa: BLE001 - 导航失败非致命
            logger.warning("坐席%s 导航到呼叫中心失败(非致命): %s", agent["sip_number"], exc)
    if ok:
        recorder.record("L1L2-坐席组1 三名坐席在线就绪", True)
    return ok


def agents_all_ready(env: dict) -> bool:
    """检查三名坐席 UI 就绪状态(REDAY)"""
    browser = env["browser"]
    return all(browser.is_ready(page) for page in env["pages"].values())


def set_agents_ready(env: dict, ready: bool) -> None:
    """统一置坐席就绪/忙碌(坐席组1 成员), 单页失败仅告警"""
    browser = env["browser"]
    for sip, page in env["pages"].items():
        try:
            if not browser.set_ready(page, ready=ready):
                logger.warning("坐席%s 置%s失败", sip, "就绪" if ready else "忙碌")
        except Exception as exc:  # noqa: BLE001
            logger.warning("坐席%s 置%s异常: %s", sip, "就绪" if ready else "忙碌", exc)


def cleanup_fs_channels(esl: EslHelper, esl2: EslHelper) -> None:
    """挂断 CC 双 FS 全部残留通道(级间清理, 幂等)"""
    for helper in (esl, esl2):
        try:
            if helper.sock:
                helper.hangup_all_channels()
        except Exception as exc:  # noqa: BLE001
            logger.warning("FS hupall 异常: %s", exc)


# ==================== 自动接听与证据收集 ====================
def _query_level_records(db: DbHelper, since: datetime) -> dict:
    """
    查询本级并发窗口内的通话记录与坐席分配分布。

    :return: {"total": 总 CDR 行数, "by_callee": {坐席分机: 行数}, "callers": [主叫号, ...]}
    """
    # pymysql execute 内部用 % 插值, SQL 中字面 %(LIKE 通配)须写成 %%(见 db_helper 参数绑定)
    rows = db.query("SELECT caller_number, callee_number, answer_flag, call_state "
                    "FROM cc_call_record WHERE deleted=0 AND caller_number LIKE '186000000%%' "
                    "AND create_time >= %s ORDER BY id", (since,))
    total = len(rows)
    by_callee: dict = {}
    callers = []
    for r in rows:
        callee = str(r.get("callee_number") or "")
        if callee in AGENT_GROUP_SIPS:
            by_callee[callee] = by_callee.get(callee, 0) + 1
        callers.append(str(r.get("caller_number") or ""))
    logger.info("[查询] 并发窗口 CDR=%d 行, 坐席分配=%s (since=%s)", total, by_callee, since)
    return {"total": total, "by_callee": by_callee, "callers": callers}


def _count_esl_events(env: dict) -> dict:
    """
    从双 FS 事件采集器统计本级证据(主叫接通数/坐席腿被分配数)。

    主叫腿: CHANNEL_ANSWER 且 Caller-Caller-ID-Number 为 186 号段 -> 接通数;
    坐席腿: 内部呼叫坐到席(originate 1001@1.com:1)的事件, 依次匹配
    Caller-Destination-Number / Caller-Callee-ID-Number / variable_sip_req_user
    三个字段找 1001/1002/1003 -> 每坐席被分配次数。
    说明: 坐席腿事件需订阅 CHANNEL_CREATE(见 build_env 扩展 SUBSCRIBE_EVENTS)。
    """
    answered_callers, agent_rings = set(), {s: 0 for s in AGENT_GROUP_SIPS}
    for collector in env["collectors"]:
        with collector._lock:  # noqa: SLF001 - 复用主脚本的事件读取方式
            events = list(collector._events)  # noqa: SLF001
        for evt in events:
            name = evt.get("Event-Name")
            caller = evt.get("Caller-Caller-ID-Number") or ""
            callee = (evt.get("Caller-Destination-Number") or ""
                      or evt.get("Caller-Callee-ID-Number") or ""
                      or evt.get("variable_sip_req_user") or "")
            if name == "CHANNEL_ANSWER" and caller.startswith("186") and len(caller) == 11:
                answered_callers.add(caller)
            if name in ("CHANNEL_CREATE", "CHANNEL_ANSWER") and callee in AGENT_GROUP_SIPS:
                agent_rings[callee] = agent_rings.get(callee, 0) + 1
    return {"answered": len(answered_callers), "agent_rings": agent_rings}


def _check_duplication(records: dict) -> dict:
    """
    重复分配检测: DB 中同一坐席被并发分配 >=2 路即判疑似(坐席状态竞态窗口导致)。

    边界说明: 正常链路下坐席一旦被分配/振铃, 前端上报 RINGING 后 Redis 状态不再是
    READY, 后续呼叫不会选中它; 若并发窗口内同坐席出现 >=2 通记录, 说明选座->振铃
    上报之间存在竞态(即"空闲坐席获取重复"缺陷), 属测试核心断言。
    """
    duplication = {s: cnt for s, cnt in records.get("by_callee", {}).items() if cnt > 1}
    return duplication


def _compute_trajectory_violations(sampler: AgentStatusSampler, agent_id_map: dict) -> list:
    """状态轨迹合法性检查: 未知状态码/采样为空 视为异常, 返回异常清单"""
    violations = []
    for sip, agent_id in agent_id_map.items():
        traj = sampler.trajectory(agent_id)
        if not traj:
            violations.append("坐席%s 无任何状态采样" % sip)
            continue
        for _, name, code in traj:
            if code not in STATUS_TEXT:
                violations.append("坐席%s 出现未知状态码 %s" % (sip, code))
    return violations


def _verify_db_redis_consistency(env: dict, sampler: AgentStatusSampler,
                                 agent_id_map: dict) -> dict:
    """终态一致性: DB cc_sys_agent.online_status 与 Redis 最后采样比对, 返回 {不一致清单}"""
    diffs = []
    snapshot = sampler.snapshot()
    for sip, agent_id in agent_id_map.items():
        rows = env["db"].query("SELECT online_status FROM cc_sys_agent WHERE id=%s AND deleted=0",
                               (agent_id,))
        db_status = rows[0]["online_status"] if rows else None
        redis_status = snapshot.get(str(agent_id), {}).get("onlineStatus")
        if db_status is not None and redis_status is not None and db_status != redis_status:
            diffs.append("坐席%s DB=%s Redis=%s" % (sip, db_status, redis_status))
    return {"diffs": diffs}


# ==================== 坐席组1 配置临时修改(排队子测试) ====================
def switch_group_to_queue_mode(env: dict) -> bool:
    """
    坐席组1 临时改为排队策略(full_busy_type=0 + 调大 queue_length/time_out)。

    需求背景: 生产组1 为"全忙溢出(转IVR)", 排队行为需临时切换配置才能观察;
    queue_length 原值 1 / time_out 原值 1s 无排队观察窗口, 分别放大到
    CONCURRENT_QUEUE_LENGTH / CONCURRENT_QUEUE_TIMEOUT。
    预期结果: UPDATE 成功返回 True; 原值已在 run_l0_check 备份, 由还原函数恢复。
    """
    try:
        env["db"].execute(
            "UPDATE cc_sys_agent_group SET full_busy_type=0, queue_length=%s, time_out=%s "
            "WHERE id=1 AND deleted=0",
            (config.CONCURRENT_QUEUE_LENGTH, config.CONCURRENT_QUEUE_TIMEOUT))
        return True
    except Exception as exc:  # noqa: BLE001
        logger.error("坐席组1 切换排队配置失败: %s", exc)
        return False


def restore_group_config(env: dict) -> bool:
    """将坐席组1 配置还原为备份值(排队子测试收尾/异常兜底调用)"""
    backup = env.get("group_config_backup")
    if not backup:
        logger.warning("无坐席组1 配置备份, 跳过还原")
        return False
    try:
        env["db"].execute(
            "UPDATE cc_sys_agent_group SET full_busy_type=%s, overflow_type=%s, "
            "overflow_value=%s, time_out=%s, queue_length=%s WHERE id=1 AND deleted=0",
            (backup["full_busy_type"], backup["overflow_type"], backup["overflow_value"],
             backup["time_out"], backup["queue_length"]))
        logger.info("坐席组1 配置已还原: full_busy=%s queue_length=%s time_out=%s",
                    backup["full_busy_type"], backup["queue_length"], backup["time_out"])
        return True
    except Exception as exc:  # noqa: BLE001
        logger.error("坐席组1 配置还原失败: %s", exc)
        return False


# ==================== 单级并发执行(核心) ====================
def run_level(n: int, env: dict, recorder: e2e.StepRecorder, reporter: ConcurrentReporter,
              queue_mode: bool = False) -> bool:
    """
    执行一级并发呼入测试(n 路主叫并发呼叫 4001234)。

    流程: 采样器启动 -> 级前清理 -> (排队模式: 坐席置忙+组1 切排队) -> 批量注册主叫 ->
    发令枪齐发 -> 坐席自动接听第 1 路 -> settle 收集 -> 证据断言 -> 清理复位。
    :param n: 本集并发路数
    :param env: 环境组件集合(build_env 产出)
    :param recorder: 步骤记录器
    :param reporter: 分级结果收集器
    :param queue_mode: True 时执行排队逻辑子测试(临时改组1 配置并坐席置忙)
    :return: 本级是否通过(已记录缺陷不影响判定)
    """
    browser, db, redis = env["browser"], env["db"], env["redis"]
    esl, esl2 = env["esl"], env["esl2"]
    log_tail = env["log_tail"]
    collectors = env["collectors"]
    agent_id_map = env["agent_id_map"]
    level_start = datetime.now() - timedelta(seconds=10)  # 容忍本机与DB服务器时钟差
    buf = []

    # 步骤1: 坐席就绪确认 + 状态采样器启动
    if not agents_all_ready(env):
        set_agents_ready(env, ready=True)
        recorder.record("并发%d-坐席组就绪复位" % n, agents_all_ready(env))
    sampler = AgentStatusSampler(redis, list(agent_id_map.values()),
                                 config.CONCURRENT_STATUS_SAMPLE_INTERVAL).start()

    # 步骤2: 级前清理(残留通道/事件/日志游标)
    cleanup_fs_channels(esl, esl2)
    for collector in collectors:
        collector.clear()
    log_tail.reset()
    env["result_tail"].reset()

    # 步骤3: 排队模式准备(组1 切排队 + 坐席置忙)
    if queue_mode:
        if not switch_group_to_queue_mode(env):
            recorder.record("并发%d-坐席组1 切换排队配置" % n, False)
            sampler.stop()
            return False
        set_agents_ready(env, ready=False)  # 置忙 -> 无空闲坐席 -> 走排队分支
        time.sleep(3)

    # 步骤4: 批量注册 n 个第三方网关主叫
    callers = [_caller_number(i) for i in range(n)]
    pool = InboundCallerPool(callers)
    registered, reg_failed = pool.start()
    rate = registered / n if n else 0
    recorder.record("并发%d-批量注册主叫(%d/%d=%.0f%%)" % (n, registered, n, rate * 100),
                    registered >= max(1, int(n * 0.9)),
                    "失败账号: %s" % ",".join(reg_failed) if reg_failed else "")

    # 步骤5: 发令枪齐发(每路 CONNECTED 后监控线程自动发 DTMF '1')
    # DTMF 时机: IVR 应答后提示音播放约 2s 才开收号窗口(receive 5s), 发送偏早会被丢弃
    # 导致流程卡在 receive/playback(实测 CDR 停留在 4001234)。并发升高后 RFC2833 DTMF
    # 依赖 RTP 媒体时序易丢(20 级实测全丢), 改用 SIP INFO(信令通道) + 3s/5s/7s 三时点
    # 重发, 覆盖 receive 窗口漂移
    pool.fire(dtmf="1", dtmf_delays=(3.0, 5.0, 7.0), dtmf_method="info")

    # 步骤6: settle 等待 + 坐席自动接听(主线程轮询)
    # 注意: Playwright sync API 仅限主线程调用, 后台线程接听会触发 greenlet 跨线程错误
    # 导致接听失败(冒烟实测), 故自动接听必须放在本主线程的 settle 循环内。
    # 普通模式: 等 IVR 放音/DTMF/转坐席组/振铃/接听/通话(CONCURRENT_SETTLE_SECONDS)
    # 排队模式: 等 N 路入队(10s) -> 释放第 1 个坐席观察是否被排队分配 -> 等排队超时窗口
    answered_sips = []
    release_sip = None
    queue_exception_hits = 0
    if queue_mode:
        # 先等 15s 让全部呼叫完成 IVR 全链并进入排队态(flow101 全链约 10-15s), 再释放
        # 坐席, 避免"新到达呼叫直接分配"与"排队呼叫被 fsAcd 分配"两类现象混淆
        time.sleep(15)
        release_sip = sorted(env["pages"].keys())[0]
        if browser.set_ready(env["pages"][release_sip], ready=True):
            logger.info("并发%d-排队模式: 释放坐席%s 观察排队分配", n, release_sip)
        settle_sec = config.CONCURRENT_QUEUE_TIMEOUT + 5
    else:
        # 覆盖 DTMF 三发 + IVR 全链 + 转接放音链路 + audioFork 重试的时序波动
        # (实测转接可能在 fire+35s 后才振铃, 窗口不足导致弹窗检测遗漏)
        settle_sec = config.CONCURRENT_SETTLE_SECONDS + 30
    deadline = time.time() + settle_sec
    popup_seen = {sip: 0 for sip in env["pages"]}  # 弹窗出现次数统计(诊断用)
    while time.time() < deadline:
        for sip, page in env["pages"].items():
            if sip in answered_sips:
                continue
            try:
                if page.query_selector(".incoming-dialog") is not None:
                    popup_seen[sip] = popup_seen.get(sip, 0) + 1
                    t0_ans = time.time()
                    ok_ans = browser.answer_call(page)
                    logger.info("[诊断-%d级] 坐席%s 来电弹窗->接听 %s (耗时%.1fs)",
                                n, sip, "成功" if ok_ans else "失败", time.time() - t0_ans)
                    if ok_ans:
                        answered_sips.append(sip)
            except Exception as exc:  # noqa: BLE001 - 单次轮询异常不致命
                logger.warning("[%s] 自动接听轮询异常: %s", sip, exc)
        time.sleep(1)
    logger.info("[诊断-%d级] settle 期间各坐席弹窗出现次数: %s", n, popup_seen)
    states = pool.collect_states()

    # 无坐席接听时 DOM 取证(截图 + 弹窗/通话条元素计数 + 前端 console 轨迹),
    # 供定位前端振铃后弹窗未显示/接听失败根因
    if not answered_sips:
        for sip, page in env["pages"].items():
            try:
                dom_counts = page.evaluate(
                    "() => ({incoming: document.querySelectorAll('.incoming-dialog').length,"
                    " active: document.querySelectorAll('.active-call').length,"
                    " softphone: !!document.querySelector('.softphone, .phone-panel, .switch-wrap')})")
                console_all = env.get("page_console", {}).get(sip, [])
                # 过滤关键行: 来电处理/振铃/会话状态/错误, 定位弹窗未出现根因
                key_lines = [m for m in console_all if re.search(
                    r"收到来电|呼入会话|incoming|INVITE|振铃|failed|error|reject|busy|terminate|取消|拒绝", m, re.I)]
                logger.warning("[诊断-%d级] 坐席%s 无接听 DOM: %s | console共%d条, 关键行(%d): %s",
                               n, sip, dom_counts, len(console_all), len(key_lines),
                               " || ".join(key_lines[-15:]))
                os.makedirs("screenshots", exist_ok=True)
                page.screenshot(path=os.path.join("screenshots", "conc_l%d_%s.png" % (n, sip)))
            except Exception as exc:  # noqa: BLE001 - 取证失败不致命
                logger.warning("[诊断-%d级] 坐席%s DOM 取证失败: %s", n, sip, exc)

    # 步骤7: 证据收集(ESL 事件 + 后端日志窗口内完整读取)
    esl_evidence = _count_esl_events(env)
    buf.append(log_tail.read_new())
    log_text = "".join(buf)
    time.sleep(1)
    buf.append(log_tail.read_new())
    log_text = "".join(buf)

    # 步骤8: 级后清理(主叫停机 -> FS 清通道 -> 坐席复位就绪 -> 采样器停止)
    pool.hangup_all()
    time.sleep(2)
    pool.stop_all()
    cleanup_fs_channels(esl, esl2)
    time.sleep(3)  # 等 CDR/流程实例在挂断后落库
    # DB 终态记录: 在挂断后查询(转坐席组后 callee_number 被改写为坐席分机,
    # CDR 随通话结束写入, 清理前查询会漏记)
    db_records = _query_level_records(db, level_start)
    # DB/Redis 终态一致性: 在坐席复位前对比(此时为通话结束后的自然状态, 避免
    # set_agents_ready 的前端 WS 异步上报造成 Redis 滞后于 DB 的假性不一致)
    consistency = _verify_db_redis_consistency(env, sampler, agent_id_map)
    set_agents_ready(env, ready=True)
    if queue_mode:
        restore_group_config(env)
    sampler.stop()

    # ==================== 步骤9: 核心断言(基于已收集证据) ====================
    passed = True
    # 9.1 坐席状态更新: 轨迹无异常 + 接听坐席出现 TALKING_IN + 终态 DB=Redis 一致
    violations = _compute_trajectory_violations(sampler, agent_id_map)
    recorder.record("并发%d-坐席状态轨迹合法(3名坐席)" % n, not violations,
                    "; ".join(violations) if violations else "")
    passed = passed and not violations
    talking_sips = []
    for sip, agent_id in agent_id_map.items():
        traj = sampler.trajectory(agent_id)
        if any(code == 5 for _, _, code in traj):  # 5=TALKING_IN
            talking_sips.append(sip)
    recorder.record("并发%d-坐席接听(TALKING_IN: %s)" % (n, ",".join(talking_sips) or "无"),
                    bool(talking_sips) or not answered_sips,
                    "自动接听成功: %s" % ",".join(answered_sips) if answered_sips else "无坐席接听")
    recorder.record("并发%d-终态 DB=Redis 状态一致" % n, not consistency["diffs"],
                    "; ".join(consistency["diffs"]) if consistency["diffs"] else "三名坐席一致")

    # 9.2 空闲坐席获取: 重复分配检测(核心并发断言, 基于 DB 终态记录)
    duplication = _check_duplication(db_records)
    if duplication:
        dup_text = "; ".join("坐席%s=%d路" % (s, c) for s, c in duplication.items())
        reporter.add_defect("并发%d 坐席重复分配(通话重复建立风险)" % n,
                            "DB 并发窗口内同坐席被分配 >=2 路: %s; 坐席端将收到多路来电, "
                            "根因疑为选座->前端上报RINGING的竞态窗口" % dup_text)
    else:
        dup_text = ""
    recorder.record("并发%d-无坐席重复分配(空闲坐席获取并发正确)" % n, not duplication,
                    dup_text if duplication else "各坐席至多 1 路")
    passed = passed and not duplication
    # ESL 交叉证据: 坐席腿振铃次数(>1 同样提示竞态, 但 DB 为准)
    rings_text = "; ".join("%s=%d" % (s, c) for s, c in esl_evidence["agent_rings"].items())

    # 9.3 接通验证: 主叫侧接通(ESL CHANNEL_ANSWER)与坐席接听数
    # 高并发下 audioFork 放音链路不可用会致呼入全部挂断(30+ 级实测 pjsua 全 DISCONNECTED),
    # 接通率 <50% 判级 FAIL 并记录缺陷, 真实反映该级呼叫链路可用性
    answered_calls = esl_evidence["answered"]
    connect_rate = answered_calls / n if n else 0
    recorder.record("并发%d-主叫接通(%d/%d=%.0f%%)坐席接听=%d路" % (
        n, answered_calls, n, connect_rate * 100, len(answered_sips)),
        answered_calls >= 1, "坐席腿振铃分布: %s" % rings_text)
    if connect_rate < 0.5:
        reporter.add_defect("并发%d级 呼叫接通率骤降(%.0f%%, 仅%d路接通)" % (n, connect_rate * 100, answered_calls),
                            "主叫侧大部分呼叫未完成 IVR 应答即被挂断(pjsua 侧状态多数为 DISCONNECTED), "
                            "高并发下 IVR 放音链路(audioFork/TTS)不可用或 sipproxy/FS 呼叫处理到达上限, "
                            "本级的转坐席组/坐席状态验证不完整")
        passed = passed and connect_rate >= 0.5

    # 9.4 排队/溢出分支证据记录(不阻断主判定, 缺陷进报告)
    if queue_mode:
        kw_joined = len(KW_QUEUE_JOINED.findall(log_text))
        kw_timeout = len(KW_QUEUE_TIMEOUT.findall(log_text))
        kw_exception = len(KW_QUEUE_EXCEPTION.findall(log_text))
        # 入队证据: 入队日志命中数 + 扫描异常(仅队列非空时 fsAcd 才会执行到 multiGet 抛异常)
        # + 释放坐席后被分配(rec_alloc 成立必然说明队列中曾有排队呼叫)
        rec_alloc = (db_records.get("by_callee", {}).get(release_sip, 0) > 0
                     or esl_evidence["agent_rings"].get(release_sip, 0) > 0)
        queue_has_entries = kw_joined > 0 or kw_exception > 0 or rec_alloc
        if kw_exception:
            reporter.add_defect("并发%d级 排队分发失效(fsAcd 扫描异常)" % n,
                                "fsAcd 排队扫描命中异常 %d 次(每 2s 扫描周期抛 ClassCastException: "
                                "multiGet 的 Collections.singleton(agentIds) 字段类型错误, 与 handler() 已修复 "
                                "问题同源且漏修), 排队呼叫永远不会被分配到坐席, 最终全部排队超时挂断"
                                % kw_exception)
        # 释放的坐席是否被排队分配: ESL 坐席腿振铃 / DB 分配记录 任一命中
        recorder.record("并发%d-排队分支行为(有入队=%s 超时=%d 扫描异常=%d 释放%s后分配=%s)" % (
            n, "是" if queue_has_entries else "否", kw_timeout, kw_exception,
            release_sip, "是" if rec_alloc else "否"),
            rec_alloc and not kw_exception,
            "预期 FAIL: fsAcd 异常时排队呼叫无法分配(见缺陷报告)")
        passed = passed and rec_alloc and not kw_exception
    else:
        overflow_hits = len(KW_OVERFLOW.findall(log_text))
        overflow_value = str((env.get("group_config_backup") or {}).get("overflow_value") or "")
        # 仅当溢出目标非数字(期望 IVR 流程 ID)时才记为配置缺陷;
        # 修复后 overflow_value 为有效流程 ID, 溢出转 IVR 属正常分支行为
        if overflow_hits and not overflow_value.isdigit():
            reporter.add_defect("坐席组1 溢出分支触发(溢出目标配置无效)",
                                "全忙时溢出转 IVR 目标 overflow_value=%r 非数字(期望 IVR 流程 ID), "
                                "溢出呼叫无法进入有效流程, 日志命中溢出关键词 %d 次" % (overflow_value, overflow_hits))
        recorder.record("并发%d-溢出分支行为记录(命中=%d次, 目标=%s)" % (n, overflow_hits, overflow_value), True,
                        "溢出转 IVR(目标有效)" if overflow_hits and overflow_value.isdigit()
                        else ("溢出目标配置无效(缺陷详情见报告)" if overflow_hits else "未触发溢出"))

    # 9.5 audioFork(TTS 流式放音)并发瓶颈统计: 高并发下放音链路失败会阻断流程推进到
    # 转坐席组, 属被测系统并发上限发现, 记录缺陷不判级 FAIL(级判定由转接/接听断言承担)
    audiofork_hits = len(KW_AUDIOFORK_FAIL.findall(log_text))
    if audiofork_hits:
        reporter.add_defect("并发%d级 audioFork 放音瓶颈(TTS 流式放音并发上限)" % n,
                            "日志命中 audioFork 启动失败/流式播放超时 %d 次, 高并发下 "
                            "mod_audio_fork 连接建立失败导致放音节点异常、流程无法推进到转坐席组; "
                            "该级坐席组并发行为未完整验证" % audiofork_hits)
    recorder.record("并发%d-audioFork 放音失败统计(命中=%d次)" % (n, audiofork_hits), True,
                    "存在放音瓶颈(见缺陷报告)" if audiofork_hits else "无放音异常")

    # ==================== 步骤10: 级数据汇总进报告 ====================
    states_text = ", ".join("%s=%d" % (k, v) for k, v in sorted(states.items()))
    agent_dist = {s: db_records.get("by_callee", {}).get(s, 0) for s in AGENT_GROUP_SIPS}
    traj_lines = []
    for sip, agent_id in agent_id_map.items():
        traj_lines.append("%s: %s" % (sip, reporter.trajectory_summary(sampler.trajectory(agent_id))))
    reporter.add_level(n, {
        "started": n, "registered": registered, "connected": esl_evidence["answered"],
        "states": states, "states_text": states_text,
        "agent_dist": agent_dist,
        "agent_dist_text": "; ".join("%s=%d" % (s, c) for s, c in agent_dist.items()),
        "duplication": duplication,
        "duplication_text": dup_text if duplication else "无",
        "trajectory_text": " | ".join(traj_lines),
        "passed": passed,
        "summary": "" if passed else "存在失败断言",
    })
    return passed


def _caller_number(idx: int) -> str:
    """按序号生成第三方网关主叫分机号(18600000000 + idx, 支持 100+)"""
    base = int(config.CONCURRENT_CALLER_START)
    return str(base + idx)


def _ensure_create_subscribed(env: dict) -> None:
    """确保双 FS 事件订阅包含 CHANNEL_CREATE(场景11 复用主脚本 collector 时重订)"""
    for collector in env.get("collectors", []):
        # 复用主脚本 collector 时同步扩容事件队列(主脚本默认 5000 上限)
        if getattr(collector, "_events", None) is not None and \
                isinstance(collector._events, collections.deque) and \
                collector._events.maxlen < 30000:  # noqa: SLF001
            collector._events = collections.deque(maxlen=30000)  # noqa: SLF001
        if "CHANNEL_CREATE" in (collector.SUBSCRIBE_EVENTS or ()):
            continue
        try:
            # subscribe_events 为替换式订阅(先 off 再订阅新集), 幂等可重复调用
            collector.helper.subscribe_events(
                list(e2e.EslEventCollector.SUBSCRIBE_EVENTS) + ["CHANNEL_CREATE"])
            collector.SUBSCRIBE_EVENTS = list(collector.SUBSCRIBE_EVENTS) + ["CHANNEL_CREATE"]
            logger.info("[%s] 重订 CHANNEL_CREATE 事件", collector.tag)
        except Exception as exc:  # noqa: BLE001 - 重订失败仅影响坐席腿计数, DB 为准
            logger.warning("[%s] 重订 CHANNEL_CREATE 失败: %s", collector.tag, exc)


# ==================== 主执行器(独立脚本模式) ====================
class ConcurrentRunner:
    """独立压测执行器: 环境初始化 -> L0 -> 坐席登录 -> 分级执行 -> 汇总退出码"""

    def __init__(self, headless: bool = False, queue_test: bool = False,
                 out_dir: str = "reports"):
        self.headless = headless
        self.queue_test = queue_test
        self.out_dir = out_dir
        self.env = None
        self.reporter = ConcurrentReporter(out_dir)
        self._queue_mode_active = False

    def setup(self) -> bool:
        self.env = build_env(headless=self.headless)
        env = self.env
        try:
            if not env["browser"].start():
                logger.error("浏览器启动失败")
                return False
            if not env["esl"].connect():
                logger.error("ESL(fs2) 连接失败")
                return False
            if not env["esl2"].connect():
                logger.error("ESL(fs1) 连接失败")
                return False
            if not env["db"].connect():
                logger.error("MySQL 连接失败")
                return False
            if not env["redis"].connect():
                logger.error("Redis 连接失败")
                return False
            env["agent_id_map"] = load_agent_id_map(env["db"])
            logger.info("坐席映射: %s", env["agent_id_map"])
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error("环境初始化异常: %s", exc)
            return False

    def run(self, levels: list, skip_l0: bool = False) -> int:
        recorder = e2e.StepRecorder()
        if not skip_l0:
            if not run_l0_check(self.env, recorder, max(levels)):
                print("\n[L0 环境核对结果]")
                for line in recorder.summary_lines():
                    print(line)
                print("[FATAL] L0 环境/数据核对未通过, 终止测试(退出码 2)")
                return 2
            print("\n[L0 环境核对结果]")
            for line in recorder.summary_lines():
                print(line)
        else:
            print("[跳过] L0 环境核对(--skip-l0)")
        if not login_all_agents(self.env, recorder):
            print("[FATAL] 坐席登录签入失败, 终止测试(退出码 2)")
            return 2
        self.reporter.meta = {"levels": levels, "target_uri": e2e.INBOUND_TARGET_URI,
                              "queue_test": self.queue_test}
        all_pass = True
        for n in levels:
            r = e2e.StepRecorder()
            print("\n" + "=" * 60)
            print("执行并发 %d 级%s" % (n, "(排队模式)" if self.queue_test else ""))
            print("=" * 60)
            try:
                passed = run_level(n, self.env, r, self.reporter,
                                   queue_mode=self.queue_test)
            except Exception as exc:  # noqa: BLE001 - 级异常视为本级失败
                logger.exception("并发 %d 级异常", n)
                r.record("并发%d-执行异常" % n, False, str(exc))
                passed = False
            finally:
                # 兜底: 排队模式异常(如 UPDATE 后崩溃)必须还原组1 配置
                if self.queue_test:
                    restore_group_config(self.env)
            for line in r.summary_lines():
                print(line)
            all_pass = all_pass and passed
        print("\n[并发压测结果汇总]")
        for line in self.reporter.summary_lines():
            print(line)
        paths = self.reporter.write()
        print("\n[报告] .md=%s\n[报告] .json=%s" % (paths.get("md"), paths.get("json")))
        return 0 if all_pass else 1

    def teardown(self) -> None:
        if self.queue_test:
            restore_group_config(self.env)
        if self.env:
            teardown_env(self.env)


# ==================== 场景11 轻量入口(主脚本 cc_e2e_test 复用) ====================
def run_levels_light(ctx: dict, recorder: e2e.StepRecorder, levels: list = None,
                     queue_test: bool = False) -> bool:
    """
    主脚本场景11 入口: 复用主脚本已初始化的 ctx 组件, 补齐坐席 1003 页面后分级执行。

    需求背景: 主脚本的浏览器/ESL/DB/Redis/日志游标已初始化且不重复创建, 坐席1003
    (page_c) 在主脚本默认只登录 1001/1002, 此处按需补齐并签入。
    :param ctx: 主脚本 TestRunner.ctx(scenario 上下文)
    :param recorder: 主脚本 StepRecorder
    :param levels: 分级列表(默认 [10, 20] 轻量验证主链路)
    :param queue_test: 是否包含排队子测试(默认 False, 由独立脚本承担完整排队验证)
    """
    levels = levels or [10, 20]
    env = {
        "browser": ctx["browser"], "esl": ctx["esl"], "esl2": ctx["esl2"],
        "db": ctx["db"], "redis": ctx["redis"], "log_tail": ctx["log_tail"],
        "result_tail": ctx["result_tail"], "collectors": ctx["collectors"],
        "esl_hosts": ctx["esl_hosts"], "pages": {}, "agent_id_map": {},
    }
    env["agent_id_map"] = load_agent_id_map(ctx["db"])
    # 复用主脚本 collector 时需确保订阅含 CHANNEL_CREATE(坐席腿计数用)
    _ensure_create_subscribed(env)
    # 复用主脚本已登录的 1001/1002, 补 1003
    pages = {"1001": ctx.get("page_a"), "1002": ctx.get("page_b")}
    page_c = ctx.get("page_c")
    if page_c is None:
        page_c = ctx["browser"].new_context_page()
        ctx["page_c"] = page_c
        if not e2e.login_and_signin(ctx["browser"], page_c, config.AGENT_C,
                                    config.LOCAL_FRONTEND_URL, e2e.StepRecorder()):
            recorder.record("场景11-坐席1003 登录签入", False)
            return False
        try:
            page_c.click("text=呼叫中心", timeout=10000)
            time.sleep(1)
        except Exception:  # noqa: BLE001
            pass
    pages["1003"] = page_c
    env["pages"] = pages
    if not all(ctx["browser"].is_ready(p) for p in pages.values() if p is not None):
        for sip, page in pages.items():
            if page is not None:
                try:
                    ctx["browser"].set_ready(page, ready=True)
                except Exception:  # noqa: BLE001
                    pass
    # 组1 配置备份(排队子测试还原用)
    rows = ctx["db"].query("SELECT full_busy_type, overflow_type, overflow_value, "
                           "time_out, queue_length FROM cc_sys_agent_group WHERE id=1 AND deleted=0")
    env["group_config_backup"] = rows[0] if rows else None
    reporter = ConcurrentReporter(os.path.join(_THIS_DIR, "reports"))
    reporter.meta = {"levels": levels, "target_uri": e2e.INBOUND_TARGET_URI,
                     "queue_test": queue_test, "entry": "cc_e2e_test-scenario11"}
    all_pass = True
    for n in levels:
        r = e2e.StepRecorder()
        print("\n[场景11] 执行并发 %d 级%s" % (n, "(排队模式)" if queue_test else ""))
        try:
            passed = run_level(n, env, r, reporter, queue_mode=queue_test)
        except Exception as exc:  # noqa: BLE001
            logger.exception("场景11 并发 %d 级异常", n)
            r.record("并发%d-执行异常" % n, False, str(exc))
            passed = False
        finally:
            if queue_test:
                restore_group_config(env)
        for line in r.summary_lines():
            print(line)
        all_pass = all_pass and passed
    paths = reporter.write(tag="concurrent_report_scene11")
    print("\n[场景11 报告] .md=%s" % paths.get("md"))
    return all_pass


# ==================== 参数解析与主流程 ====================
def parse_args():
    parser = argparse.ArgumentParser(description="呼叫中心并发呼入压测脚本(独立于主脚本运行)")
    parser.add_argument("--levels", type=str, default=",".join(map(str, config.CONCURRENT_LEVELS_DEFAULT)),
                        help="并发分级, 逗号分隔(默认 %s)" % config.CONCURRENT_LEVELS_DEFAULT)
    parser.add_argument("--headless", action="store_true", default=False,
                        help="浏览器无头模式")
    parser.add_argument("--queue-test", action="store_true", default=False,
                        help="执行排队逻辑子测试(临时改坐席组1 为排队策略, 测完还原)")
    parser.add_argument("--out-dir", type=str, default="reports",
                        help="报告输出目录(默认 reports)")
    parser.add_argument("--skip-l0", action="store_true", default=False,
                        help="跳过 L0 环境核对")
    return parser.parse_args()


def _parse_levels(levels_str: str) -> list:
    """解析 --levels 并校验(1..CONCURRENT_MAX_LEVEL, 去重保序)"""
    nums = []
    for part in levels_str.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            num = int(part)
        except ValueError:
            print("[ERROR] 无效的并发分级: %s" % levels_str)
            sys.exit(2)
        if num < 1 or num > config.CONCURRENT_MAX_LEVEL:
            print("[ERROR] 并发分级 %d 越界(合法范围 1..%d)" % (num, config.CONCURRENT_MAX_LEVEL))
            sys.exit(2)
        if num not in nums:
            nums.append(num)
    return nums or list(config.CONCURRENT_LEVELS_DEFAULT)


def main() -> int:
    args = parse_args()
    levels = _parse_levels(args.levels)
    print("\n" + "#" * 60)
    print("# 呼叫中心并发呼入压测(cc_concurrent_test)")
    print("# 时间: %s" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("# 分级: %s | 排队子测试: %s | 模式: %s"
          % (levels, "是" if args.queue_test else "否",
             "无头" if args.headless else "有头"))
    print("#" * 60)
    runner = ConcurrentRunner(headless=args.headless, queue_test=args.queue_test,
                              out_dir=args.out_dir)
    try:
        if not runner.setup():
            print("[FATAL] 环境初始化失败(浏览器/ESL/MySQL/Redis 任一不可用)")
            return 2
        return runner.run(levels, skip_l0=args.skip_l0)
    finally:
        runner.teardown()


if __name__ == "__main__":
    sys.exit(main())