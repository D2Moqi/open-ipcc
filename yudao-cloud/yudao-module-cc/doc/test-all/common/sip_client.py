# -*- coding: utf-8 -*-
"""
SIP 软电话客户端封装(IVR 流程测试专用)
========================================
统一的 SipClient 接口,底层实现可切换:
- "pjsua2" : pjsua2 Python 绑定(单线程 libHandle 事件循环模型,
             所有 pjsua2 对象操作在同一线程,其他线程经队列转发)
- "cli"    : pjsua CLI 子进程方式(brew install pjproject 提供 pjsua 二进制,
             控制台模式支持 呼叫/接听/挂断/# RFC2833 DTMF / * SIP INFO DTMF / dq 通话质量转储)

需求背景: IVR 端到端测试需要 18600000000/18600000001 两个软电话注册到
第三方 FS(62.234.191.165:9988,域 1.com:1),支持呼叫、接听、DTMF、
真实 RTP 收流字节统计(供断言"收到了语音数据")。
预期结果: 测试脚本通过 SipClient 完成注册/呼叫/收号/语音校验。

环境结论: 当前 macOS(arm64) 无匹配 pjsua2 wheel(PyPI 仅 sdist 需本地
pjproject 库+swig 构建),默认使用 cli 后端;SipClient(backend="auto")
在 import pjsua2 成功时自动切换 pjsua2 后端。
"""

import enum
import logging
import os
import pty
import re
import shutil
import signal
import subprocess
import sys
import termios
import threading
import time
from collections import deque
from typing import Callable, List, Optional, Sequence, Tuple, Union

# config.py 与 sip_client.py 同居 common/ 目录,由主脚本 cc_e2e_test.py 将 common/ 加入 sys.path,
# 此处直接同级导入(无需在模块内再做 sys.path 装配)。
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))

import config  # noqa: E402

logger = logging.getLogger("sip_client")

# ==================== 常量(来自 config.py) ====================
# 第三方 FS 注册地址(62.234.191.165:9988)
REGISTRAR_HOST = config.THIRD_PARTY_FS_HOST
REGISTRAR_PORT = config.THIRD_PARTY_FS_SIP_PORT
# 注册域名与认证 realm: 实测第三方 FS 目录域名(realm)为 62.234.191.165
# (ESL list_users 核实, 账号 18600000000~18600000029 均在域 62.234.191.165;
#  用 1.com 域注册会被拒绝 403 Forbidden)。config.SIP_DOMAIN(1.com:1) 是
# CC 坐席域,不适用于第三方 FS 软电话。
THIRD_PARTY_SIP_DOMAIN = config.THIRD_PARTY_FS_HOST
AUTH_REALM = config.THIRD_PARTY_FS_HOST
# registrar URI: sip:62.234.191.165:9988
# 实测结论: 该 FS 9988 UDP 无响应(OPTIONS 探测超时), TCP 返回 200 OK,
# 故注册/呼叫统一使用 TCP 传输(AOR 与 registrar 均带 ;transport=tcp)
REGISTRAR_URI = "sip:%s:%s;transport=tcp" % (REGISTRAR_HOST, REGISTRAR_PORT)
# 场景1 呼叫目标: sip:4001234@39.107.224.184:5561
INBOUND_TARGET_URI = "sip:%s@%s:%s" % (
    config.IVR_INBOUND_ROUTE_NUM,
    config.SIP_PROXY_PUBLIC_IP,
    config.SIP_PROXY_PUBLIC_PORT,
)

# NAT 穿透服务(与前端 SoftPhone.vue 的 JsSIP iceServers 配置一致):
# 本地软电话在 NAT 后,FS 回程 RTP 无法直达私有地址;通过 STUN 反射候选
# + TURN 中继候选通告公网可达地址,保证媒体双向连通。pjsua CLI 参数格式
# 为 host:port(--stun-srv/--turn-srv 不接受 stun:/turn: 前缀),pjsua2 同理。
STUN_SERVER = config.STUN_SERVER
TURN_SERVER = config.TURN_SERVER
TURN_USERNAME = config.TURN_USERNAME
TURN_PASSWORD = config.TURN_PASSWORD

# pjsua 状态名 → 统一状态名映射(pjsua 用 CONFIRMED 表示通话建立)
_STATE_ALIAS = {"CONFIRMED": "CONNECTED"}

# dq(call dump)输出中 RTP 统计的解析(实测 pjsua 2.17 格式,多行):
#   Call time: 00h:00m:03s, 1st res in 514 ms, conn in 515ms
#   RX pt=0, last update:00h:00m:03.202s ago
#      total 100pkt 16.0KB (20.0KB +IP hdr) @avg=15.6Kbps/19.6Kbps
# RX 段与其后首个 total 行之间可能间隔 SRTP status 等行,用 [\s\S] 跨行匹配,
# 并限制在 TX 段出现之前;单位可能是 KB/MB/B。
# 注意 "total 100pkt" 数字与 pkt 之间可能无空格,\s* 兼容;锚点用 "RX pt" 而非裸 RX
_RX_TOTAL_RE = re.compile(
    r"RX\s+pt\s*=\s*\d+[\s\S]{0,300}?total\s+(\d+)\s*pkt\s+([\d.]+)\s*(KB|MB|B)?",
    re.IGNORECASE)
_CALL_TIME_RE = re.compile(r"Call time:\s*(\d+)h:(\d+)m:(\d+)s")


class CallState(str, enum.Enum):
    """统一呼叫状态(pjsua 原生状态名经 _STATE_ALIAS 归一化)"""

    NULL = "NULL"
    CALLING = "CALLING"
    INCOMING = "INCOMING"
    EARLY = "EARLY"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    DISCONNECTED = "DISCONNECTED"
    UNKNOWN = "UNKNOWN"


def normalize_state(raw: str) -> CallState:
    """把 pjsua/pjsua2 原始状态文本归一化为 CallState"""
    name = _STATE_ALIAS.get(raw.upper(), raw.upper())
    try:
        return CallState(name)
    except ValueError:
        return CallState.UNKNOWN


class SipError(RuntimeError):
    """SIP 客户端操作异常"""


class _BackendBase:
    """后端抽象接口(CLI / pjsua2 两种实现)"""

    backend_name = "base"

    def start(self) -> None:  # pragma: no cover - 抽象方法
        raise NotImplementedError

    def stop(self) -> None:  # pragma: no cover
        raise NotImplementedError

    def register(self, username: str, password: str, timeout: float) -> bool:
        raise NotImplementedError

    def is_registered(self, timeout: float) -> bool:
        raise NotImplementedError

    def call(self, target_uri: str) -> None:
        raise NotImplementedError

    def answer(self) -> None:
        raise NotImplementedError

    def hangup(self) -> None:
        raise NotImplementedError

    def send_dtmf(self, digits: str, method: str) -> None:
        raise NotImplementedError

    def play_wav(self, wav_path: str) -> None:
        """
        向当前通话播放 WAV 音频文件(供 ASR 语音注入测试,如 AI 对话中断词)

        预留能力：当前场景 10 走浏览器 --use-file-for-fake-audio-capture 假麦克风注入
        (见 cc_e2e_test.py main() 的 fake_audio_wav 参数)，本方法暂无调用方；
        后续如需经 SIP 软电话注入语音，可在此实现并接入场景。

        :param wav_path: WAV 文件绝对路径
        """
        raise NotImplementedError

    def get_call_state(self) -> CallState:
        raise NotImplementedError

    def poll_rx_stat(self) -> Tuple[int, float]:
        """返回 (累计接收字节数, 累计接收时长秒);实现方应尽量取实时值"""
        raise NotImplementedError


# ==================== CLI 子进程后端 ====================
class _PjsuaCliBackend(_BackendBase):
    """
    基于 pjsua CLI 子进程的后端实现。

    控制台模式命令(经 stdin 下发):
      m  -> 发起呼叫(提示 "Make call:" 后输入 URI)
      a  -> 接听(提示 "Answer with code (100-699):" 后输入 200)
      h  -> 挂断当前通话
      #  -> 发送 RFC2833 DTMF(提示输入按键串)
      *  -> 发送 SIP INFO DTMF(提示输入按键串)
      dq -> 转储当前通话质量(含 RTP 收/发字节统计)
      rr -> 重新发起注册

    日志事件(经 stdout 读取):
      "Call N state changed to X"      -> 呼叫状态变更
      "registration success/failed..."  -> 注册结果
    """

    backend_name = "cli"

    def __init__(self, username: str, password: str, rtp_port: int = 0,
                 sip_port: int = 0, pjsua_bin: Optional[str] = None, log_file: Optional[str] = None,
                 log_level: int = 5, use_ice: bool = False,
                 sip_domain: Optional[str] = None, registrar_uri: Optional[str] = None,
                 auth_realm: Optional[str] = None, transport: str = "tcp"):
        self._username = username
        self._password = password
        self._rtp_port = rtp_port
        self._sip_port = sip_port
        self._log_level = log_level
        # 注册域/服务器/realm 参数化: 默认沿用第三方 FS(18600000000 测试软电话),
        # AI 对话场景可作为坐席注册 sipproxy/CC FS
        self._sip_domain = sip_domain or THIRD_PARTY_SIP_DOMAIN
        self._registrar_uri = registrar_uri or REGISTRAR_URI
        self._auth_realm = auth_realm or AUTH_REALM
        self._transport = transport
        # 是否启用 ICE + STUN/TURN 穿透。默认关闭: 实测 pjsua 启用 ICE 后 INVITE 强制走
        # TCP,而 sipproxy 对 TCP 直连 INVITE 有缺陷(100 Trying 后无响应),呼叫必失败;
        # 关闭时走 UDP,FS 对称 RTP 学习机制已保证回程 RTP 可达(实测 31KB/5s)
        self._use_ice = use_ice
        self._pjsua_bin = pjsua_bin or shutil.which("pjsua") or "/opt/homebrew/bin/pjsua"
        # 事件解析读 stdout(实时);日志文件仅作归档转存
        # 注意: 不能用 --log-file 做事件源——pjsua 对文件日志是块缓冲(实测 4KB),
        # 事件会延迟到进程退出才落盘;stdout 是行缓冲,实时可见
        if log_file:
            self._log_file = log_file
        else:
            os.makedirs(os.path.join(_THIS_DIR, "logs"), exist_ok=True)
            self._log_file = os.path.join(_THIS_DIR, "logs", "pjsua_%s.log" % username)
        self._proc: Optional[subprocess.Popen] = None
        self._reader: Optional[threading.Thread] = None
        self._pty_master: Optional[int] = None
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        # 输出行事件流(供 wait_line 消费),游标之前的行定期裁剪
        self._lines: List[str] = []
        self._cursor = 0
        # 状态缓存
        self._registered: Optional[bool] = None
        self._call_state = CallState.NULL
        self._connected_at: Optional[float] = None
        self._rx_bytes_baseline = 0
        self._stop_flag = False

    # ---------- 进程管理 ----------
    def start(self) -> None:
        if not os.path.exists(self._pjsua_bin):
            raise SipError("pjsua 可执行文件不存在: %s (请先 brew install pjproject)"
                           % self._pjsua_bin)
        cmd = [
            self._pjsua_bin,
            "--null-audio",
            "--max-calls=1",
            "--id", "sip:%s@%s;transport=%s" % (self._username, self._sip_domain, self._transport),
            "--registrar", self._registrar_uri,
            "--realm", self._auth_realm,
            "--username", self._username,
            "--password", self._password,
            # log-level 必须 >=5: "registration success"/"Call N state changed"
            # 等关键状态行均为 verbosity 5 级别,低于 5 解析不到;
            # =6 时额外转储 SIP 消息全文(含 SDP),供抓取 c= 行验证 NAT 广告地址
            "--log-level", str(self._log_level),
            "--app-log-level", "4",
        ]
        if self._rtp_port:
            cmd += ["--rtp-port", str(self._rtp_port)]
        if self._sip_port:
            cmd += ["--local-port", str(self._sip_port)]
        # NAT 穿透: --use-turn 必须与 --use-ice 搭配(TURN 是 ICE 的 relay 候选来源),
        # STUN 反射候选 / TURN 中继候选随 SDP 通告,远端(FS)按 ICE 协商选择可达路径
        if self._use_ice:
            cmd += ["--use-ice",
                    "--stun-srv", STUN_SERVER,
                    "--use-turn",
                    "--turn-srv", TURN_SERVER,
                    "--turn-user", TURN_USERNAME,
                    "--turn-passwd", TURN_PASSWORD]
        else:
            # 非 ICE 模式仍加 STUN(auto-update-nat 默认开启): 让 pjsua 检测 NAT 后把
            # Contact/SDP 媒体地址更新为公网 IP(如 125.33.53.38), 否则 SDP 广告局域网 IP
            # (192.168.1.17)云端 FS 无法回发 RTP(媒体 rxBytes=0)。
            # 不启用 ICE 原因: ICE 模式会强制 INVITE 走 TCP, 而 sipproxy 对 TCP 直连
            # INVITE 存在缺陷(100 Trying 后无响应), 呼叫必失败; UDP 直连 + STUN 已足够。
            cmd += ["--stun-srv", STUN_SERVER]
        logger.info("[%s] 启动 pjsua: %s", self._username, " ".join(cmd))
        # 关键: stdout 必须接 PTY(伪终端)。实测 pjsua stdout 接 pipe 时是块缓冲,
        # 日志在 libc 缓冲中不实时落出(事件解析全部失效);接终端则行缓冲实时可见。
        master_fd, slave_fd = pty.openpty()
        # 回显关闭: 避免写入的命令被回显成额外输出行
        try:
            attrs = termios.tcgetattr(slave_fd)
            attrs[3] = attrs[3] & ~termios.ECHO
            termios.tcsetattr(slave_fd, termios.TCSANOW, attrs)
        except termios.error:
            pass
        self._pty_master = master_fd
        # start_new_session=True: 独立进程组,退出时可整组清理避免残留占用端口
        self._proc = subprocess.Popen(
            cmd, stdin=slave_fd, stdout=slave_fd, stderr=slave_fd,
            start_new_session=True)
        os.close(slave_fd)
        # reader 持续读 PTY 输出并转存日志文件: 必须不停消费,否则终端缓冲
        # 写满后 pjsua 会阻塞在日志写入上
        self._reader = threading.Thread(target=self._read_loop, name="pjsua-reader-%s" % self._username,
                                        daemon=True)
        self._reader.start()

    def stop(self) -> None:
        self._stop_flag = True
        proc = self._proc
        if proc and proc.poll() is None:
            try:
                self._write_cmd("q")
            except Exception:  # noqa: BLE001 - 退出命令失败时直接 kill
                pass
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except Exception:  # noqa: BLE001
                    proc.kill()
        self._proc = None
        if self._pty_master is not None:
            try:
                os.close(self._pty_master)
            except OSError:
                pass
            self._pty_master = None

    # ---------- 底层 IO ----------
    def _read_loop(self) -> None:
        """持续读 PTY 输出逐行解析事件,并同步转存到日志文件"""
        master = self._pty_master
        assert master is not None
        try:
            log_fp = open(self._log_file, "a", encoding="utf-8")
        except OSError:
            log_fp = None
        buffer = b""
        try:
            while not self._stop_flag:
                try:
                    chunk = os.read(master, 65536)
                except OSError:  # PTY 关闭(EIO)表示子进程退出
                    break
                if not chunk:
                    break
                buffer += chunk
                while b"\n" in buffer:
                    raw, buffer = buffer.split(b"\n", 1)
                    line = raw.decode(errors="replace").rstrip("\r")
                    if log_fp:
                        log_fp.write(line + "\n")
                    self._emit_line(line)
        finally:
            if log_fp:
                log_fp.close()
            with self._cond:
                self._cond.notify_all()

    def _emit_line(self, line: str) -> None:
        with self._cond:
            self._lines.append(line)
            self._parse_event(line)
            # 游标之前的行已消费完,定期裁剪避免无限增长
            if self._cursor > 2000:
                del self._lines[:self._cursor]
                self._cursor = 0
            self._cond.notify_all()

    def _parse_event(self, line: str) -> None:
        """从日志行提取注册/呼叫状态事件(仅在 reader 线程持有锁时调用)"""
        low = line.lower()
        if "registration success" in low:
            self._registered = True
        elif ("registration failed" in low or "registration error" in low
              or "code=401" in low or "code=403" in low
              or "code=408" in low or "code=502" in low):
            self._registered = False
        m = re.search(r"Call \d+ state changed to (\w+)", line)
        if m:
            state = normalize_state(m.group(1))
            self._set_call_state(state)
            return
        # 来电时 pjsua 不输出 "state changed to INCOMING",而是该行
        if "incoming call for account" in low:
            self._set_call_state(CallState.INCOMING)
            return
        # 挂断时输出 "Call N is DISCONNECTED [reason=...]"
        if re.search(r"Call \d+ is DISCONNECTED", line):
            self._set_call_state(CallState.DISCONNECTED)

    def _set_call_state(self, state: CallState) -> None:
        self._call_state = state
        if state == CallState.CONNECTED and self._connected_at is None:
            self._connected_at = time.time()
        if state == CallState.DISCONNECTED:
            self._connected_at = None

    def _write_cmd(self, text: str) -> None:
        proc = self._proc
        if proc is None or proc.poll() is not None:
            raise SipError("pjsua 进程未运行")
        if self._pty_master is None:
            raise SipError("pjsua PTY 未就绪")
        os.write(self._pty_master, (text + "\n").encode())

    def _wait_line(self, predicate: Callable[[str], Optional[object]],
                   timeout: float) -> Optional[object]:
        """等待满足 predicate 的日志行,返回 predicate 的非 None 结果"""
        deadline = time.time() + timeout
        with self._cond:
            while True:
                for idx in range(self._cursor, len(self._lines)):
                    ret = predicate(self._lines[idx])
                    if ret:
                        self._cursor = idx + 1
                        return ret
                self._cursor = len(self._lines)
                remaining = deadline - time.time()
                if remaining <= 0:
                    return None
                self._cond.wait(timeout=min(remaining, 1.0))

    # ---------- 业务接口 ----------
    def register(self, username: str, password: str, timeout: float) -> bool:
        # 进程启动时已通过 --registrar 发起注册;此方法用于等待结果/失败重试。
        # 启动竞态说明: 首次 REGISTER 可能在 TCP 连接建立完成前发出而被丢弃
        # (日志无任何 RX 响应),故无响应超过 8s 也主动触发 rr 重注册。
        deadline = time.time() + timeout
        last_retry = time.time()  # 首次注册已由进程启动发起,从当前时刻计时等待
        while time.time() < deadline:
            if self._registered is True:
                return True
            no_response = self._registered is None and time.time() - last_retry >= 8.0
            failed = self._registered is False and time.time() - last_retry >= 5.0
            if no_response or failed:
                logger.warning("[%s] 注册%s,重新触发注册", username,
                               "失败" if failed else "无响应")
                self._registered = None
                last_retry = time.time()
                try:
                    self._write_cmd("rr")
                except SipError:
                    return False
            time.sleep(0.5)
        return self._registered is True

    def is_registered(self, timeout: float) -> bool:
        if self._registered is not None:
            return self._registered
        # 状态未知时主动触发一次注册并等待结果
        try:
            self._write_cmd("rr")
        except SipError:
            return False
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._registered is not None:
                return self._registered
            time.sleep(0.3)
        return False

    def call(self, target_uri: str) -> None:
        self._call_state = CallState.NULL
        self._write_cmd("m")
        time.sleep(0.2)  # 等待 "Make call:" 提示
        self._write_cmd(target_uri)

    def answer(self) -> None:
        self._write_cmd("a")
        time.sleep(0.2)  # 等待 "Answer with code (100-699):" 提示
        self._write_cmd("200")

    def hangup(self) -> None:
        self._write_cmd("h")

    def send_dtmf(self, digits: str, method: str) -> None:
        cmd = "#" if method == "rfc2833" else "*"
        self._write_cmd(cmd)
        time.sleep(0.2)  # 等待 "DTMF strings to send" 提示
        self._write_cmd(digits)

    def play_wav(self, wav_path: str) -> None:
        """
        向当前通话播放 WAV 音频（pjsua CLI 的 pg 命令，供 ASR 语音注入）

        :param wav_path: WAV 文件绝对路径（16bit 单声道 PCM 最佳）
        :raises SipError: 无当前通话或命令发送失败时
        """
        if self._call_state not in (CallState.CONNECTED, CallState.EARLY):
            raise SipError("无有效通话可播放音频: %s" % self._call_state)
        self._write_cmd("pg %s" % wav_path)

    def get_call_state(self) -> CallState:
        return self._call_state

    def poll_rx_stat(self) -> Tuple[int, float]:
        """发送 dq 转储并解析 RTP 接收字节数与通话时长。

        实现要点: 不用逐行谓词收集(行缓冲裁剪会重置 _cursor 造成竞态漏采),
        而是固定等待 dump 输出完毕后直接截取游标之后的全部行拼接解析。
        """
        with self._cond:
            self._cursor = len(self._lines)  # 只看 dq 之后的输出
        try:
            self._write_cmd("dq")
        except SipError:
            return self._fallback_rx_stat()
        deadline = time.time() + 5.0
        while time.time() < deadline:
            time.sleep(0.5)
            with self._cond:
                text = "\n".join(self._lines[self._cursor:])
            # dump 结束标志: 实测以 "RTT msec" 行收尾;兼容旧版 "active call" 汇总行
            if ("RTT msec" in text or "active call" in text) and "total" in text:
                break
        with self._cond:
            text = "\n".join(self._lines[self._cursor:])
            self._cursor = len(self._lines)
        rx_bytes = self._parse_rx_bytes(text)
        duration = self._parse_duration(text)
        return rx_bytes, duration

    def _parse_rx_bytes(self, text: str) -> int:
        # 截取 TX 统计段之前的内容,避免误取发送侧统计;
        # 锚点用 "TX pt" 而非裸 TX(log-level 6 的 "TX msg ..." 日志行会误截作用域)
        tx_idx = re.search(r"TX\s+pt\s*=", text)
        scope = text[:tx_idx.start()] if tx_idx else text
        m = _RX_TOTAL_RE.search(scope)
        if m:
            val = float(m.group(2))
            unit = (m.group(3) or "B").upper()
            factor = {"B": 1, "KB": 1024, "MB": 1024 * 1024}[unit]
            return int(val * factor)
        return -1  # 解析失败,由上层走兜底

    def _parse_duration(self, text: str) -> float:
        # 实测格式: "Call time: 00h:00m:03s"
        m = _CALL_TIME_RE.search(text)
        if m:
            return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
        return -1.0

    def _fallback_rx_stat(self) -> Tuple[int, float]:
        duration = (time.time() - self._connected_at) if self._connected_at else 0.0
        return -1, duration

    def get_connected_duration(self) -> float:
        """内部计时兜底: 自 CONNECTED 起的时长"""
        if self._connected_at is None:
            return 0.0
        return time.time() - self._connected_at


# ==================== pjsua2 后端(单线程事件循环模型) ====================
class _Pjsua2Backend(_BackendBase):
    """
    pjsua2 Python 绑定后端。

    线程模型(重要): pjsua2 的 Endpoint/Account/Call 对象非线程安全,
    跨线程操作会导致段错误。本实现采用单线程 libHandle 事件循环:
    - 独立线程完成 ep.libCreate -> ep.libInit -> ep.libStart;
    - 该线程循环 ep.libHandleEvents(ms),同时消费任务队列;
    - 其他线程(测试主线程)通过 submit() 把操作封装为闭包投递到队列,
      等待结果,从而保证所有 pjsua2 对象操作都发生在同一线程。

    注: 当前 macOS arm64 无可用 pjsua2 wheel,本后端未经实机验证,
    保留实现以便安装 pjsua2 后无缝切换(SipClient backend="auto")。
    """

    backend_name = "pjsua2"

    def __init__(self, username: str, password: str, **kwargs):
        import pjsua2 as pj  # noqa: F401 - 缺失时抛出 ImportError 由上层降级
        self.pj = pj
        self._username = username
        self._password = password
        self._sip_port = kwargs.get("sip_port", 0)
        # 是否启用 ICE + STUN/TURN 穿透(与 CLI 后端保持一致,默认关闭原因见 _PjsuaCliBackend)
        self._use_ice = kwargs.get("use_ice", False)
        self._queue: "deque" = deque()
        self._queue_lock = threading.Lock()
        self._queue_event = threading.Event()
        self._stop_flag = False
        self._thread: Optional[threading.Thread] = None
        self._ep = None
        self._tp = None
        self._account = None
        self._call = None
        self._registered = False
        self._call_state = CallState.NULL
        self._rx_baseline = 0

    # ---------- 单线程事件循环 ----------
    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="pjsua2-loop-%s" % self._username,
                                        daemon=True)
        self._thread.start()
        # 在事件循环线程内完成 libCreate/libInit/libStart
        self.submit(self._init_endpoint, timeout=10)

    def _init_endpoint(self) -> None:
        pj = self.pj
        self._ep = pj.Endpoint()
        self._ep.libCreate()
        ep_cfg = pj.EpConfig()
        ep_cfg.logConfig.level = 4
        ep_cfg.uaConfig.maxCalls = 1
        ep_cfg.uaConfig.userAgent = "ivr-test-pjsua2"
        # STUN 服务器(与前端 SoftPhone.vue 一致),供 ICE 反射候选解析公网地址
        if self._use_ice:
            ep_cfg.uaConfig.stunServer.append(STUN_SERVER)
        self._ep.libInit(ep_cfg)
        # 无音频设备环境使用 null 媒体
        self._ep.audDevManager().setNullDev()
        self._ep.libStart()

    def _loop(self) -> None:
        while not self._stop_flag:
            # 消费任务队列
            while True:
                with self._queue_lock:
                    item = self._queue.popleft() if self._queue else None
                if item is None:
                    break
                func, done_evt, holder = item
                try:
                    holder["result"] = func()
                except Exception as exc:  # noqa: BLE001 - 转发异常给调用线程
                    holder["error"] = exc
                done_evt.set()
            # 驱动 pjsua 事件循环(10ms 一片)
            try:
                if self._ep:
                    self._ep.libHandleEvents(10)
            except Exception:  # noqa: BLE001 - 事件循环异常不应杀死线程
                logger.exception("[%s] libHandleEvents 异常", self._username)

    def submit(self, func: Callable, timeout: float = 10.0):
        """把闭包投递到事件循环线程执行并同步等待结果"""
        done_evt = threading.Event()
        holder = {}
        with self._queue_lock:
            self._queue.append((func, done_evt, holder))
        if not done_evt.wait(timeout):
            raise SipError("pjsua2 操作超时: %r" % func)
        if "error" in holder:
            raise holder["error"]
        return holder.get("result")

    def stop(self) -> None:
        def _shutdown():
            if self._call:
                try:
                    self._call.hangup(pj=self.pj)
                except Exception:  # noqa: BLE001
                    pass
            if self._account:
                self._account.shutdown()
            if self._ep:
                self._ep.libDestroy()

        try:
            self.submit(_shutdown, timeout=5)
        except Exception:  # noqa: BLE001
            pass
        self._stop_flag = True

    # ---------- 回调对象(均在事件循环线程内被调用) ----------
    def _make_account(self):
        pj = self.pj
        backend = self

        class _Account(pj.Account):
            def onRegState(self, prm):  # noqa: N802 - pjsua2 回调命名
                backend._registered = prm.code // 100 == 2

        return _Account()

    def _make_call(self, acc):
        pj = self.pj
        backend = self

        class _Call(pj.Call):
            def onCallState(self, prm):  # noqa: N802
                ci = self.getInfo()
                backend._call_state = normalize_state(ci.stateText)

            def onCallMediaState(self, prm):  # noqa: N802
                ci = self.getInfo()
                for mi in ci.media:
                    if mi.type == pj.PJMEDIA_TYPE_AUDIO:
                        aud = self.getAudioMedia(mi.index)
                        # 将通话音频连接到 null 设备,保证 RTP 真实收发
                        try:
                            aud.startTransmit(backend._ep.audDevManager().getPlaybackDevMedia())
                        except Exception:  # noqa: BLE001
                            pass

        return _Call(acc)

    # ---------- 业务接口 ----------
    def register(self, username: str, password: str, timeout: float) -> bool:
        def _do():
            pj = self.pj
            # 先创建 TCP 传输(第三方 FS 9988 UDP 无响应,仅 TCP 可用)
            tp_cfg = pj.TransportConfig()
            if self._sip_port:
                tp_cfg.port = self._sip_port
            self._tp = self._ep.transportCreate(pj.PJSIP_TRANSPORT_TCP, tp_cfg)
            acc_cfg = pj.AccountConfig()
            acc_cfg.idUri = "sip:%s@%s;transport=tcp" % (username, THIRD_PARTY_SIP_DOMAIN)
            acc_cfg.regConfig.registrarUri = REGISTRAR_URI
            cred = pj.AuthCredInfo("digest", AUTH_REALM, username, 0, password)
            acc_cfg.sipConfig.authCreds.append(cred)
            # 开启账号级 ICE + TURN 中继(对应 pjsua CLI 的 --use-ice/--use-turn),
            # 与前端 JsSIP iceServers 配置等效,解决本地 NAT 后回程 RTP 不通
            if self._use_ice:
                acc_cfg.sipConfig.iceEnabled = True
                acc_cfg.sipConfig.turnEnabled = True
                acc_cfg.sipConfig.turnServer = TURN_SERVER
                acc_cfg.sipConfig.turnUserName = TURN_USERNAME
                acc_cfg.sipConfig.turnPassword = TURN_PASSWORD
            self._account = self._make_account()
            self._account.create(acc_cfg)

        self.submit(_do, timeout=5)
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._registered:
                return True
            time.sleep(0.3)
        return self._registered

    def is_registered(self, timeout: float) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._registered:
                return True
            time.sleep(0.3)
        return False

    def call(self, target_uri: str) -> None:
        def _do():
            self._call = self._make_call(self._account)
            prm = self.pj.CallOpParam(True)
            self._call.makeCall(target_uri, prm)

        self.submit(_do, timeout=10)

    def answer(self) -> None:
        def _do():
            if self._call is None:
                raise SipError("无来电可接听")
            prm = self.pj.CallOpParam()
            prm.statusCode = 200
            self._call.answer(prm)

        self.submit(_do, timeout=5)

    def hangup(self) -> None:
        def _do():
            if self._call is None:
                raise SipError("无当前通话")
            prm = self.pj.CallOpParam()
            prm.statusCode = 603
            self._call.hangup(prm)

        self.submit(_do, timeout=5)

    def send_dtmf(self, digits: str, method: str) -> None:
        def _do():
            if self._call is None:
                raise SipError("无当前通话")
            if method == "rfc2833":
                # pjsua2 RFC2833: Call.dialDtmf
                self._call.dialDtmf(digits)
            else:
                # SIP INFO 兜底: Call.sendRequestParam
                prm = self.pj.CallSendRequestParam()
                prm.method = "INFO"
                prm.contentType = "application/dtmf-relay"
                prm.body = "Signal=%s\r\nDuration=160" % digits[0]
                self._call.sendRequestParam(prm)

        self.submit(_do, timeout=5)

    def play_wav(self, wav_path: str) -> None:
        # pjsua2 后端暂不支持向通话直接播放 WAV（需 AudioMedia 播放器接线），
        # AI 对话语音注入场景使用 cli 后端（pjsua pg 命令）
        raise NotImplementedError("pjsua2 后端暂不支持 play_wav，请使用 backend='cli'")

    def get_call_state(self) -> CallState:
        return self._call_state

    def poll_rx_stat(self) -> Tuple[int, float]:
        def _do():
            if self._call is None:
                return (-1, 0.0)
            stat = self._call.getStreamStat()
            rx = stat.getRxStat()
            return (rx.getBytes(), 0.0)

        try:
            return self.submit(_do, timeout=5)
        except Exception:  # noqa: BLE001
            return (-1, 0.0)


# ==================== 统一门面 ====================
class SipClient:
    """
    SIP 软电话客户端统一接口。

    一个实例对应一个 SIP 账号(一个 pjsua 进程 / pjsua2 Endpoint)。
    典型用法::

        client = SipClient("18600000000")
        client.start()
        client.register("18600000000", IVR_SOFTPHONE_PASSWORD)
        client.call(INBOUND_TARGET_URI)
        state = client.wait_call_state(timeout=30)
    """

    def __init__(self, username: str, password: Optional[str] = None,
                 backend: str = "auto", rtp_port: int = 0, sip_port: int = 0,
                 pjsua_bin: Optional[str] = None,
                 log_dir: Optional[str] = None, log_level: int = 5,
                 use_ice: bool = False,
                 sip_domain: Optional[str] = None, registrar_uri: Optional[str] = None,
                 auth_realm: Optional[str] = None, transport: str = "tcp"):
        """
        初始化软电话客户端。

        入参约束: username 必填;password 缺省取 config.IVR_SOFTPHONE_PASSWORD。
        sip_domain/registrar_uri/auth_realm/transport 缺省沿用第三方 FS 注册配置
        （模块级常量），注册目标需特化的场景（如 AI 对话以坐席身份注册 sipproxy）
        可显式传入。
        use_ice=True 时启用 ICE + STUN/TURN 穿透(与前端 SoftPhone.vue 的
        JsSIP iceServers 配置一致);默认 False: 实测启用 ICE 后 pjsua 的 INVITE 强制走
        TCP,触发 sipproxy 的 TCP INVITE 缺陷(100 Trying 后无响应)导致呼叫失败,
        关闭时走 UDP 呼叫正常且回程 RTP 可达。待 sipproxy 修复 TCP 缺陷后可默认开启。
        """
        self.username = username
        self._password = password if password is not None else config.IVR_SOFTPHONE_PASSWORD
        self._impl = self._create_backend(backend, rtp_port, sip_port, pjsua_bin,
                                          log_dir, log_level, use_ice,
                                          sip_domain, registrar_uri, auth_realm, transport)
        self._rx_bytes_baseline = 0
        self._rx_duration_baseline = 0.0

    def _create_backend(self, backend: str, rtp_port: int, sip_port: int,
                        pjsua_bin: Optional[str],
                        log_dir: Optional[str],
                        log_level: int = 5, use_ice: bool = False,
                        sip_domain: Optional[str] = None, registrar_uri: Optional[str] = None,
                        auth_realm: Optional[str] = None, transport: str = "tcp") -> _BackendBase:
        if backend == "auto":
            backend = "pjsua2" if self._pjsua2_available() else "cli"
        if backend == "pjsua2":
            return _Pjsua2Backend(self.username, self._password, sip_port=sip_port,
                                  use_ice=use_ice)
        if backend == "cli":
            log_file = None
            if log_dir:
                os.makedirs(log_dir, exist_ok=True)
                log_file = os.path.join(log_dir, "pjsua_%s.log" % self.username)
            return _PjsuaCliBackend(self.username, self._password, rtp_port=rtp_port,
                                    sip_port=sip_port,
                                    pjsua_bin=pjsua_bin, log_file=log_file,
                                    log_level=log_level, use_ice=use_ice,
                                    sip_domain=sip_domain, registrar_uri=registrar_uri,
                                    auth_realm=auth_realm, transport=transport)
        raise SipError("未知后端: %s" % backend)

    @staticmethod
    def _pjsua2_available() -> bool:
        try:
            import pjsua2  # noqa: F401
            return True
        except ImportError:
            return False

    @property
    def backend_name(self) -> str:
        return self._impl.backend_name

    # ---------- 生命周期 ----------
    def start(self) -> None:
        self._impl.start()

    def stop(self) -> None:
        self._impl.stop()

    def __enter__(self) -> "SipClient":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()

    # ---------- 注册 ----------
    def register(self, username: Optional[str] = None, password: Optional[str] = None,
                 timeout: float = 20.0, retries: int = 3) -> bool:
        """注册到第三方 FS(62.234.191.165:9988,域 1.com:1),带重试与超时"""
        uname = username or self.username
        pwd = password or self._password
        for attempt in range(1, retries + 1):
            logger.info("[%s] 注册尝试 %d/%d (timeout=%.0fs)", uname, attempt, retries, timeout)
            if self._impl.register(uname, pwd, timeout):
                logger.info("[%s] 注册成功", uname)
                return True
            logger.warning("[%s] 第 %d 次注册未成功", uname, attempt)
        return False

    def is_registered(self, timeout: float = 10.0) -> bool:
        """查询注册状态(带超时等待)"""
        return self._impl.is_registered(timeout)

    # ---------- 呼叫 ----------
    def call(self, target_uri: str) -> None:
        """发起呼叫,如 sip:4001234@39.107.224.184:5561"""
        logger.info("[%s] 呼叫 %s", self.username, target_uri)
        self._impl.call(target_uri)

    def wait_call_state(self, timeout: float = 30.0,
                        states: Sequence[Union[CallState, str]] = ("CONNECTED", "DISCONNECTED")) \
            -> Optional[CallState]:
        """轮询等待呼叫进入目标状态集合,返回命中的状态或 None(超时)"""
        wanted = {normalize_state(s) if isinstance(s, str) else s for s in states}
        deadline = time.time() + timeout
        while time.time() < deadline:
            state = self._impl.get_call_state()
            if state in wanted:
                return state
            time.sleep(0.3)
        return None

    def answer(self) -> None:
        """接听来电"""
        self._impl.answer()

    def hangup(self) -> None:
        """挂断当前通话"""
        self._impl.hangup()

    def play_wav(self, wav_path: str) -> None:
        """
        向当前通话播放 WAV 音频（cli 后端的 pjsua pg 命令）

        :param wav_path: WAV 文件绝对路径
        """
        logger.info("[%s] 播放音频 %s", self.username, wav_path)
        self._impl.play_wav(wav_path)

    def get_call_state(self) -> CallState:
        return self._impl.get_call_state()

    def wait_incoming(self, timeout: float = 30.0) -> bool:
        """等待来电(INCOMING 状态),供场景2 被叫使用"""
        state = self.wait_call_state(timeout, states=("INCOMING",))
        return state == CallState.INCOMING

    # ---------- DTMF ----------
    def send_dtmf(self, digits: str, method: str = "auto") -> None:
        """
        发送 DTMF 按键。method: "rfc2833" / "info" / "auto"(RFC2833 优先,失败降级 INFO)。
        """
        digits = digits.strip()
        if not digits:
            raise SipError("DTMF 按键串为空")
        if method == "auto":
            try:
                self._impl.send_dtmf(digits, "rfc2833")
                return
            except SipError:
                logger.warning("[%s] RFC2833 发送失败,降级 SIP INFO", self.username)
                self._impl.send_dtmf(digits, "info")
        else:
            self._impl.send_dtmf(digits, method)

    # ---------- RTP 收流统计 ----------
    def get_rx_bytes(self) -> int:
        """通话建立后累计接收的 RTP 音频字节数(增量,相对上次 reset_rx_stats)"""
        rx, _ = self._impl.poll_rx_stat()
        if rx < 0:
            return 0
        return max(0, rx - self._rx_bytes_baseline)

    def get_rx_duration(self) -> float:
        """通话建立后累计接收时长(秒,增量)"""
        _, dur = self._impl.poll_rx_stat()
        if dur < 0:
            # dump 解析失败时用内部计时兜底
            if isinstance(self._impl, _PjsuaCliBackend):
                dur = self._impl.get_connected_duration()
            else:
                dur = 0.0
        return max(0.0, dur - self._rx_duration_baseline)

    def reset_rx_stats(self) -> None:
        """清零统计基线,后续 get_rx_bytes/get_rx_duration 返回增量"""
        rx, dur = self._impl.poll_rx_stat()
        if rx >= 0:
            self._rx_bytes_baseline = rx
        if dur >= 0:
            self._rx_duration_baseline = dur
        else:
            self._rx_duration_baseline = 0.0

    def get_rx_stat(self) -> Tuple[int, float]:
        """一次性返回 (接收字节增量, 接收时长增量)"""
        return self.get_rx_bytes(), self.get_rx_duration()


# ==================== 自测入口 ====================
def _self_test(do_call: bool = False) -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    accounts = [config.IVR_SOFTPHONE_A, config.IVR_SOFTPHONE_B]
    log_dir = os.path.join(_THIS_DIR, "logs")
    clients: List[SipClient] = []
    exit_code = 0
    try:
        for idx, username in enumerate(accounts):
            client = SipClient(username, backend="cli",
                               sip_port=20160 + idx * 2,
                               rtp_port=20000 + idx * 2,
                               log_dir=log_dir)
            client.start()
            clients.append(client)
        # 并发等待注册
        results = {}
        for client in clients:
            results[client.username] = client.register(timeout=25, retries=2)
        for client in clients:
            ok = results.get(client.username, False)
            print("[自测] %s 注册状态: %s (backend=%s)"
                  % (client.username, "成功" if ok else "失败", client.backend_name))
            if not ok:
                exit_code = 1
        if do_call and results.get(config.IVR_SOFTPHONE_A):
            caller = clients[0]
            print("[自测] 发起呼叫: %s -> %s" % (caller.username, INBOUND_TARGET_URI))
            caller.call(INBOUND_TARGET_URI)
            state = caller.wait_call_state(timeout=30,
                                           states=("CONNECTED", "DISCONNECTED",
                                                   "EARLY", "CALLING"))
            print("[自测] 呼叫最终状态: %s" % (state,))
            if state == CallState.CONNECTED:
                time.sleep(3)
                print("[自测] RX 统计: %s" % (caller.get_rx_stat(),))
            caller.hangup()
    finally:
        for client in clients:
            client.stop()
    return exit_code


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="SIP 软电话客户端自测")
    parser.add_argument("--call", action="store_true",
                        help="注册成功后追加呼叫 %s 验证" % INBOUND_TARGET_URI)
    args = parser.parse_args()
    sys.exit(_self_test(do_call=args.call))
