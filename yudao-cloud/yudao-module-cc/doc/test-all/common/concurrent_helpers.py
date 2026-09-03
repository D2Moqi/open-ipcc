# -*- coding: utf-8 -*-
"""
并发呼入测试公共组件
====================
供 cc_concurrent_test.py 与主脚本场景11 复用的三个组件:

- InboundCallerPool: 批量 pjsua 主叫软电话池(并发启动注册 -> 发令枪齐呼 -> 状态统计 -> 统一清理);
- AgentStatusSampler: Redis 坐席状态定时采样线程(记录 fs:agent:status 状态轨迹供并发断言);
- ConcurrentReporter: 并发分级结果汇聚与报告输出(Markdown/JSON)。

需求背景: 并发呼入压测需要同时拉起 N 个第三方网关账户(pjsua CLI 子进程, 一进程一账号)
并发呼叫 4001234, 期间持续采样坐席组内坐席的 Redis 状态变化(1-空闲/6-振铃中/5-通话中/
7-话后等), 并在每级结束后输出结构化统计与失败原因分类。
预期结果: 场景脚本只调用本组件的公共接口, 不重复实现批量软电话管理与采样逻辑。
"""
import json
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# 与 sip_client.py 同处 common/ 目录, 由脚本将本目录加入 sys.path 后直接同级导入
import config  # noqa: E402
from sip_client import CallState, INBOUND_TARGET_URI, SipClient  # noqa: E402

logger = logging.getLogger("concurrent_helpers")

# 后端 RedisConstants.AGENT_CURRENT_STATUS_KEY, Hash: field=坐席ID, value=SipAgentStatusVo JSON
AGENT_STATUS_KEY = "fs:agent:status"

# SipAgentStatusEnum 状态码 -> 名称映射(与后端枚举一致, 1空闲/2忙碌/3勿扰/4离线/5通话中/6振铃中/7话后)
STATUS_TEXT = {1: "READY", 2: "NOT_READY", 3: "NOT_READY_NOT_TALKING", 4: "OFF_ON",
               5: "TALKING_IN", 6: "RINGING", 7: "TALKING_OUT"}


def parse_agent_status(raw: Optional[str]) -> Optional[dict]:
    """解析 Redis fs:agent:status 值(Jackson JSON 字符串)为扁平字典, 解析失败返回 None"""
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return {
        "id": data.get("id"),
        "name": data.get("name"),
        "onlineStatus": data.get("onlineStatus"),
        "status": data.get("status"),
        "statusTime": data.get("statusTime"),
        "callEndTime": data.get("callEndTime"),
        "userName": data.get("userName"),
    }


class AgentStatusSampler:
    """
    Redis 坐席状态定时采样线程。

    需求背景: 并发呼入期间坐席状态(README/忙/振铃/通话/话后)变化频繁, 单次快照无法还原
    状态机轨迹; 本组件每 interval 秒采样一次 fs:agent:status 并追加到内存轨迹, 供级末
    对比"状态更新是否按预期流转、是否存在非法跳变"。
    线程模型: 独立 daemon 线程, stop() 幂等; Redis 读失败仅告警不中断。
    """

    def __init__(self, redis_helper, agent_ids: List[int], interval: float = 0.5):
        self._redis = redis_helper
        self._agent_ids = [str(a) for a in agent_ids]
        self._interval = interval
        self._trajectories: Dict[str, List[Tuple[float, str, int]]] = {a: [] for a in self._agent_ids}
        self._snapshots: Dict[str, dict] = {}
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def start(self) -> "AgentStatusSampler":
        self._thread = threading.Thread(target=self._loop, name="agent-status-sampler", daemon=True)
        self._thread.start()
        return self

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._sample_once()
            except Exception as exc:  # noqa: BLE001 - 采样失败不致命, 下轮重试
                logger.warning("[AgentStatusSampler] 采样异常: %s", exc)
            self._stop.wait(self._interval)

    def _sample_once(self) -> None:
        if self._redis is None or self._redis.client is None:
            return
        try:
            raw_map = self._redis.client.hmget(AGENT_STATUS_KEY, self._agent_ids)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[AgentStatusSampler] hmget 失败: %s", exc)
            return
        now = time.time()
        with self._lock:
            for agent_id, raw in zip(self._agent_ids, raw_map):
                parsed = parse_agent_status(raw)
                if parsed is None:
                    continue
                self._snapshots[agent_id] = parsed
                code = parsed.get("onlineStatus")
                self._trajectories[agent_id].append((now, STATUS_TEXT.get(code, str(code)), code))

    def trajectory(self, agent_id) -> List[Tuple[float, str, int]]:
        """返回指定坐席完整轨迹 [(采样时间戳, 状态名, 状态码), ...]"""
        with self._lock:
            return list(self._trajectories.get(str(agent_id), []))

    def snapshot(self) -> Dict[str, dict]:
        """返回最近一次采样快照 {agentId: {name, onlineStatus, ...}}"""
        with self._lock:
            return {k: dict(v) for k, v in self._snapshots.items()}

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self._interval * 2 + 1)
            self._thread = None


class InboundCallerPool:
    """
    批量 pjsua 主叫软电话池。

    一个实例对应一批第三方网关账户(18600000000 起), 每账户一个 pjsua CLI 子进程
    (--max-calls=1, --null-audio)。端口段与常规场景错开(config.CONCURRENT_SIP_PORT_BASE/
    CONCURRENT_RTP_PORT_BASE), 避免与场景1/2/3 的 20160/20000 段冲突。
    齐呼采用 threading.Barrier 发令枪: 全部就绪后同一时刻发起 INVITE, 保证并发真实性。
    """

    def __init__(self, callers: List[str], password: Optional[str] = None):
        self._callers = callers
        self._password = password or config.IVR_SOFTPHONE_PASSWORD
        self._clients: Dict[str, SipClient] = {}
        self._lock = threading.Lock()

    def _make_client(self, idx: int, username: str) -> SipClient:
        sip_port = config.CONCURRENT_SIP_PORT_BASE + idx * 2
        rtp_port = config.CONCURRENT_RTP_PORT_BASE + idx * 2
        return SipClient(username, password=self._password, backend="cli",
                         sip_port=sip_port, rtp_port=rtp_port)

    def start(self, max_workers: int = 20, timeout: Optional[float] = None) -> Tuple[int, List[str]]:
        """
        并发启动并注册全部主叫。

        :param max_workers: 并发启动线程数(默认 20, 避免 100 个进程同时拉起压力过大)
        :param timeout: 单个客户端注册超时(默认取 CONCURRENT_REGISTER_TIMEOUT)
        :return: (注册成功数, 失败账号清单)
        """
        timeout = timeout or config.CONCURRENT_REGISTER_TIMEOUT
        ok, failed = [], []
        with ThreadPoolExecutor(max_workers=min(max_workers, len(self._callers))) as pool:
            futures = {}
            for idx, username in enumerate(self._callers):
                client = self._make_client(idx, username)
                with self._lock:
                    self._clients[username] = client
                futures[pool.submit(self._start_and_register, client, timeout)] = username
            for future in as_completed(futures):
                username = futures[future]
                try:
                    if future.result():
                        ok.append(username)
                    else:
                        failed.append(username)
                except Exception as exc:  # noqa: BLE001
                    logger.error("[%s] 启动/注册异常: %s", username, exc)
                    failed.append(username)
        return len(ok), failed

    @staticmethod
    def _start_and_register(client: SipClient, timeout: float) -> bool:
        try:
            client.start()
            return client.register(timeout=timeout, retries=2)
        except Exception as exc:  # noqa: BLE001
            logger.error("[%s] 启动异常: %s", client.username, exc)
            try:
                client.stop()
            except Exception:  # noqa: BLE001
                pass
            return False

    def fire(self, target_uri: Optional[str] = None, dtmf: str = "1",
             dtmf_delay: float = 3.0, dtmf_delays: Optional[Tuple[float, ...]] = None,
             dtmf_gap: float = 2.0, dtmf_method: str = "auto") -> List[threading.Thread]:
        """
        发令枪齐发呼叫(每客户端一个监控线程)。

        flow101 主链需 DTMF '1' 命中收号节点才继续到转坐席组: 每路 CONNECTED(IVR 应答)
        后延迟 dtmf_delay 秒发送按键, 覆盖 receive 的 5s 收号窗口。并发下 IVR 处理
        时序漂移大, 单发可能早丢(在提示音播完前到达)导致流程卡死; dtmf_delays 传入
        多次发送时间点(如 (3.0, 5.0))时按序重发, 提高窗口命中率。dtmf 传空串则不发。
        dtmf_method: "auto"(RFC2833 优先) / "rfc2833" / "info"(SIP INFO, 走信令通道,
        不依赖媒体时序, 高并发时更可靠)。
        """
        uri = target_uri or INBOUND_TARGET_URI
        barrier = threading.Barrier(len(self._clients))
        delays: Tuple[float, ...] = ()
        if dtmf:
            delays = dtmf_delays if dtmf_delays is not None else (dtmf_delay,)
            if len(delays) > 1:
                # 多时间点: 后续时间点在前一基础上累加间隔, 保证相对 CONNECTED 的绝对时点
                fixed = [delays[0]]
                for idx in range(1, len(delays)):
                    fixed.append(fixed[-1] + dtmf_gap)
                delays = tuple(fixed)
        threads = []
        for client in list(self._clients.values()):
            t = threading.Thread(target=self._fire_one,
                                 args=(client, uri, barrier, dtmf, delays, dtmf_method),
                                 name="caller-%s" % client.username, daemon=True)
            t.start()
            threads.append(t)
        return threads

    @staticmethod
    def _fire_one(client: SipClient, uri: str, barrier: threading.Barrier,
                  dtmf: str, delays: Tuple[float, ...], dtmf_method: str) -> None:
        try:
            barrier.wait(timeout=30)
            client.call(uri)
            if dtmf and delays:
                state = client.wait_call_state(timeout=config.CONCURRENT_CALL_TIMEOUT,
                                               states=("CONNECTED", "DISCONNECTED"))
                if state == CallState.CONNECTED:
                    for delay in delays:
                        time.sleep(delay)
                        try:
                            client.send_dtmf(dtmf, method=dtmf_method)
                        except Exception as exc:  # noqa: BLE001 - 单路 DTMF 失败不影响整体
                            logger.warning("[%s] DTMF 发送失败: %s", client.username, exc)
        except threading.BrokenBarrierError:
            logger.error("[%s] 发令枪等待超时, 部分客户端未就绪", client.username)
        except Exception as exc:  # noqa: BLE001
            logger.error("[%s] 齐呼异常: %s", client.username, exc)

    def collect_states(self, wait_sec: float = 0.0) -> Dict[str, int]:
        """等待 wait_sec 后统计各客户端呼叫状态分布(状态名 -> 数量)"""
        if wait_sec > 0:
            time.sleep(wait_sec)
        counts: Dict[str, int] = {}
        for client in list(self._clients.values()):
            state = str(client.get_call_state() or CallState.NULL)
            counts[state] = counts.get(state, 0) + 1
        return counts

    def hangup_all(self) -> None:
        for client in list(self._clients.values()):
            try:
                client.hangup()
            except Exception:  # noqa: BLE001
                pass

    def stop_all(self) -> None:
        for client in list(self._clients.values()):
            try:
                client.stop()
            except Exception:  # noqa: BLE001
                pass
        self._clients.clear()


class ConcurrentReporter:
    """
    并发分级结果汇聚与报告输出。

    每级数据由场景脚本组装为 dict(发起点数/注册/接通/坐席分布/重复分配/轨迹摘要/缺陷),
    汇总后输出: 终端 summary_lines + reports/concurrent_report_{ts}.md + .json。
    """

    def __init__(self, out_dir: str = "reports"):
        self.out_dir = out_dir
        self.levels: List[dict] = []
        self.defects: List[dict] = []
        self.meta: dict = {}

    def add_level(self, level: int, data: dict) -> None:
        self.levels.append({"level": level, **(data or {})})

    def add_defect(self, title: str, detail: str) -> None:
        self.defects.append({"title": title, "detail": detail})

    def all_passed(self) -> bool:
        """所有分级 passed 且无阻断级失败(已记录缺陷不影响此项, 缺陷单独呈现)"""
        return bool(self.levels) and all(lv.get("passed", False) for lv in self.levels)

    def summary_lines(self) -> List[str]:
        lines = []
        for lv in self.levels:
            detail = lv.get("summary") or ""
            lines.append("  [%s] 并发%d: 发起=%d 注册=%d 接通=%d%s" % (
                "PASS" if lv.get("passed") else "FAIL", lv.get("level"),
                lv.get("started", 0), lv.get("registered", 0), lv.get("connected", 0),
                (" | " + detail) if detail else ""))
        return lines

    def trajectory_summary(self, trajectory: List[Tuple[float, str, int]]) -> str:
        """轨迹压缩: 连续相同状态合并为 状态名x次数, 便于报告阅读"""
        if not trajectory:
            return "(无采样)"
        parts, last = [], None
        for _, name, code in trajectory:
            key = (name, code)
            if last and last[0] == key:
                parts[-1] = (key, parts[-1][1] + 1)
            else:
                parts.append((key, 1))
                last = (key, 1)
        return " -> ".join("%sx%d" % (name, n) for (name, _), n in parts)

    def _markdown(self) -> str:
        lines = [
            "# 并发呼入测试报告",
            "",
            "- 生成时间: %s" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "- 分级: %s" % (self.meta.get("levels") or "-"),
            "- 呼叫目标: %s" % (self.meta.get("target_uri") or "-"),
            "- 总体结论: %s" % ("全部通过" if self.all_passed() else "存在失败级"),
            "",
            "## 分级结果",
            "",
            "| 级别 | 发起 | 注册成功 | 接通 | 状态分布 | 坐席接通分布 | 重复分配 | 结果 |",
            "|------|------|----------|------|----------|--------------|----------|------|",
        ]
        for lv in self.levels:
            lines.append("| %d | %d | %d | %d | %s | %s | %s | %s |" % (
                lv.get("level"), lv.get("started", 0), lv.get("registered", 0),
                lv.get("connected", 0), lv.get("states_text", "-"), lv.get("agent_dist", "-"),
                lv.get("duplication_text", "无"), "PASS" if lv.get("passed") else "FAIL"))
        for lv in self.levels:
            lines += ["", "### 并发 %d 级" % lv.get("level"),
                      "", lv.get("extra_text") or "(无额外记录)"]
        lines += ["", "## 已发现缺陷"]
        if not self.defects:
            lines += ["", "- 未发现缺陷"]
        else:
            for idx, d in enumerate(self.defects, start=1):
                lines += ["", "- [%d] %s: %s" % (idx, d["title"], d["detail"])]
        return "\n".join(lines)

    def write(self, tag: str = "concurrent_report") -> Dict[str, str]:
        """输出 .md 与 .json 报告, 返回 {扩展名: 绝对路径}"""
        os.makedirs(self.out_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        paths = {}
        for ext, content in (("md", self._markdown()),
                             ("json", json.dumps(
                                 {"meta": self.meta, "levels": self.levels,
                                  "defects": self.defects, "all_passed": self.all_passed()},
                                 ensure_ascii=False, indent=2))):
            path = os.path.join(self.out_dir, "%s_%s.%s" % (tag, ts, ext))
            with open(path, "w", encoding="utf-8") as fp:
                fp.write(content)
            paths[ext] = path
        return paths