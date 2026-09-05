#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
录音统一存储方案(演进档) 阶段0 FS 能力探针脚本
=================================================
需求背景: 演进档"媒体汇聚式录音"复用 mod_audio_fork 旁路录音 fork(role=recording),
        其架构前提是 FreeSWITCH 对同一通道(uuid)允许多个并发 fork(两条独立 WS)且互不挤占。
        本文档 5.1 的 T1-T6 探针即验证该事实,输出 R1(主路线,双 fork 并存成立)/
        R2(备选,单 fork 复用)判定,冻结架构后再进入阶段 1 开发。

预期结果:
    T1 同 uuid 双 fork(mono → stereo)并存且均持续推流 → R1 必要条件
    T2 关闭其中一条 WS 不影响另一条存活推流 → R1 必要条件
    T3 fork(stereo)与 uuid_record 同通道并存(shadow 期对拍前提)
    T4 bridge 后 stereo 声道归属/mixed 内容完整性(产物落盘,人工听感核对)
    T5 fork stop 与通道挂断的 WS 关闭时序(无悬挂)
    T6 8k/16k 帧计量(320B/640B 每 20ms)与长通话资源(soak 可选)

使用方式(无 venv,系统 python3.11 直跑;复用 ../common 公共组件):
    前置条件: 需要 FS 上存在一通"媒体活动"的呼叫通道(uuid),例如先执行
              cc_e2e_test.py --scenarios 1 建立内部通话后再运行本脚本;
              或自动选取: 不加 --uuid 时自动挑选 show channels 的第一个活动通道。
    WS 监听器必须运行在 FS 可回连的地址:
        本地不可达 FS 时,建议把 --listen-host 0.0.0.0 与 --listen-port 部署到
        FS 所在宿主机(ssh 远端执行),并把 --ws-url 前缀指到该地址。

    # 自动选通道完整跑 T1/T2/T3/T6(mono+stereo,16k)
    python3 fs_audio_fork_probe.py
    # 指定通道 + 只跑 T1/T2
    python3 fs_audio_fork_probe.py --uuid <fs-uuid> --steps T1,T2
    # 8k 采样与 30 分钟 soak(长通话资源观察)
    python3 fs_audio_fork_probe.py --uuid <fs-uuid> --sample-rate 8000 --soak-minutes 30
    # 人工分析 stereo 声道归属(T4)时把双声道样本落盘:
    python3 fs_audio_fork_probe.py --uuid <fs-uuid> --steps T4 --sample-out ./probe_samples

退出码约定:
    0 = 执行完成(含 R1/R2 判定输出);1 = 环境/通道不可用;2 = 参数错误

注意: 本脚本只读 FS 状态、下发 fork/record 命令并观察 WS,不修改任何 FS 配置;
      uuid_record 产物写入 FS 本地 /tmp 探针目录,结束后清理。

状态: 【待环境验证】 2026-09-04 落档时测试 FS 缺少媒体活动通道(CC FS 无自答通道,
      通道只能经完整呼叫链路产生),T1-T6 未实跑;本脚本已完整固化探针步骤与 R1/R2
      判定逻辑,待具备活动通话环境后执行(先 cc_e2e_test.py --scenarios 1 或指定 --uuid),
      输出 probe_report.json 存档后冻结架构;判定前按 R1 主路线推进(文档 5.2)。
"""

import argparse
import base64
import hashlib
import json
import logging
import os
import re
import socket
import struct
import sys
import threading
import time
from datetime import datetime

# ==================== 路径装配: 复用 ../common 公共组件(禁止复制) ====================
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_COMMON_DIR = os.path.join(_THIS_DIR, "..", "common")
if _COMMON_DIR not in sys.path:
    sys.path.insert(0, _COMMON_DIR)

import config  # noqa: E402
from esl_helper import EslHelper  # noqa: E402

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s")
logger = logging.getLogger("fs_audio_fork_probe")

# ==================== 常量 ====================
# WS 帧计量: 20ms/帧,L16 单声道(8k=320B / 16k=640B),stereo 翻倍
FRAME_MS = 20
BYTES_PER_SAMPLE = 2
WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
# 判定阈值: 观察窗口内至少收到帧数(低于则视为无推流)
MIN_FRAMES_WINDOW = 5
# fork 命令返回中的成功标记
REPLY_OK_MARKERS = ("+OK", "OK")


# ==================== 最小 WS 服务端(RFC6455,纯 socket,零依赖) ====================
class ForkWsConnection:
    """单条 FS fork WS 连接:握手解析 + 帧统计 + ping/pong + 样本落盘。"""

    def __init__(self, sock, addr, listener):
        self.sock = sock
        self.addr = addr
        self.listener = listener
        self.uuid = None
        self.role = None
        self.fs_address = None
        self.connected_at_ms = None
        self.closed_at_ms = None
        self.frame_count = 0
        self.byte_count = 0
        self.close_code = None
        self.sample_file = None
        self._sample_written = 0
        self._lock = threading.Lock()

    def handshake(self) -> bool:
        """解析 HTTP Upgrade 请求并应答 101;成功返回 True。"""
        try:
            self.sock.settimeout(5)
            req = b""
            while b"\r\n\r\n" not in req:
                chunk = self.sock.recv(4096)
                if not chunk:
                    return False
                req += chunk
                if len(req) > 65536:
                    return False
        except socket.timeout:
            return False
        text = req.decode("utf-8", errors="replace")
        # 解析请求行与头
        lines = text.split("\r\n")
        if not lines or not lines[0].startswith("GET "):
            logger.warning("[ws] 非 GET 请求: %s", lines[0] if lines else "")
            return False
        path = lines[0].split(" ", 2)[1]
        headers = {}
        for line in lines[1:]:
            if ":" in line:
                k, _, v = line.partition(":")
                headers[k.strip().lower()] = v.strip()
        key = headers.get("sec-websocket-key")
        if not key:
            return False
        # 解析 URL 查询参数(type/uuid/fs_address/role/recordId/callId/tenantId)
        query = path.split("?", 1)[1] if "?" in path else ""
        params = dict(p.split("=", 1) for p in query.split("&") if "=" in p)
        self.uuid = params.get("uuid")
        self.fs_address = params.get("fs_address")
        self.role = params.get("role", "playback")
        accept = base64.b64encode(
            hashlib.sha1((key + WS_GUID).encode()).digest()).decode()
        resp = ("HTTP/1.1 101 Switching Protocols\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Accept: {accept}\r\n"
                "\r\n")
        self.sock.sendall(resp.encode())
        self.connected_at_ms = int(time.time() * 1000)
        logger.info("[ws][CONNECT] uuid=%s role=%s fs_address=%s from=%s:%s",
                    self.uuid, self.role, self.fs_address, self.addr[0], self.addr[1])
        # T4 样本: stereo 双声道原始 PCM 落盘(便于人工分析声道归属)
        if self.listener.sample_out and self.uuid:
            name = f"fork_{self.uuid[:8]}_{self.role}_{self.listener.mix_type}_{self.listener.sample_rate}.pcm"
            self.sample_file = open(os.path.join(self.listener.sample_out, name), "wb")
        return True

    def serve(self):
        """帧读取循环: 统计 + 可选样本落盘 + 自动 pong;连接关闭时登记时序。"""
        try:
            self.sock.settimeout(2)
            while True:
                header = self._recv_exact(2)
                if header is None:
                    break
                b1, b2 = header
                opcode = b1 & 0x0F
                masked = b2 & 0x80
                length = b2 & 0x7F
                if length == 126:
                    ext = self._recv_exact(2)
                    if ext is None:
                        break
                    length = struct.unpack(">H", ext)[0]
                elif length == 127:
                    ext = self._recv_exact(8)
                    if ext is None:
                        break
                    length = struct.unpack(">Q", ext)[0]
                mask_key = None
                if masked:
                    mask_key = self._recv_exact(4)
                    if mask_key is None:
                        break
                payload = b""
                if length > 0:
                    payload = self._recv_exact(length)
                    if payload is None:
                        break
                    if mask_key:
                        payload = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))
                if opcode == 0x9:  # ping → pong
                    self.sock.sendall(b"\x8a" + bytes([len(payload)]) + payload)
                elif opcode == 0x8:  # close
                    self.close_code = struct.unpack(">H", payload[:2])[0] if len(payload) >= 2 else None
                    try:
                        self.sock.sendall(b"\x88\x00")
                    except OSError:
                        pass
                    break
                elif opcode == 0x2:  # binary(PCM 帧)
                    self.frame_count += 1
                    self.byte_count += len(payload)
                    if self.sample_file is not None and self._sample_written < 4 * 1024 * 1024:
                        self.sample_file.write(payload)
                        self._sample_written += len(payload)
        except socket.timeout:
            pass
        except OSError as exc:
            logger.debug("[ws] %s 读取异常: %s", self.uuid, exc)
        finally:
            self.closed_at_ms = int(time.time() * 1000)
            if self.sample_file:
                self.sample_file.close()
            self.sample_file = None
            try:
                self.sock.close()
            except OSError:
                pass
            duration_ms = (self.closed_at_ms - self.connected_at_ms) if self.connected_at_ms else -1
            logger.info("[ws][CLOSE] uuid=%s role=%s frames=%d bytes=%d conn_ms=%d close_code=%s",
                        self.uuid, self.role, self.frame_count, self.byte_count,
                        duration_ms, self.close_code)
            self.listener.on_conn_closed(self)

    def _recv_exact(self, n):
        buf = b""
        while len(buf) < n:
            try:
                chunk = self.sock.recv(n - len(buf))
            except socket.timeout:
                return None
            if not chunk:
                return None
            buf += chunk
        return buf

    def close_server_side(self, code=1000):
        """服务端主动关闭(探针 T2: 模拟旁路连接被踢/关闭,观察另一条 fork 是否存活)。"""
        try:
            self.sock.sendall(struct.pack("!BBH", 0x88, 0x02, code))
        except OSError:
            pass


class ForkWsListener:
    """fork WS 监听器: uuid → 连接列表(允许同 uuid 多连接,这正是探针对象)。"""

    def __init__(self, host="0.0.0.0", port=9876, sample_out=None,
                 mix_type="stereo", sample_rate=16000):
        self.host = host
        self.port = port
        self.sample_out = sample_out
        self.mix_type = mix_type
        self.sample_rate = sample_rate
        self.conns = []          # 全部(含已关闭,按时间序)
        self.active = {}         # uuid -> [ForkWsConnection]
        self._lock = threading.Lock()
        self._server = None
        self._thread = None

    def start(self):
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind((self.host, self.port))
        self._server.listen(16)
        self._thread = threading.Thread(target=self._accept_loop, daemon=True,
                                        name="fork-ws-accept")
        self._thread.start()
        logger.info("[ws] 监听器启动 %s:%d", self.host, self.port)

    def _accept_loop(self):
        while True:
            try:
                sock, addr = self._server.accept()
            except OSError:
                return
            conn = ForkWsConnection(sock, addr, self)
            if not conn.handshake():
                try:
                    sock.close()
                except OSError:
                    pass
                continue
            with self._lock:
                self.conns.append(conn)
                self.active.setdefault(conn.uuid or "?", []).append(conn)
            threading.Thread(target=conn.serve, daemon=True,
                             name=f"fork-ws-{conn.uuid}").start()

    def wait_conn(self, uuid, timeout_s=10.0, expect=1):
        """等待指定 uuid 出现 expect 条活跃连接(事件轮询,无帧阻塞)。"""
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            with self._lock:
                live = [c for c in self.active.get(uuid, [])
                        if c.closed_at_ms is None and c.connected_at_ms is not None]
            if len(live) >= expect:
                return live
            time.sleep(0.1)
        return live

    def conns_of(self, uuid):
        with self._lock:
            return [c for c in self.active.get(uuid, [])]

    def on_conn_closed(self, conn):
        with self._lock:
            live = [c for c in self.active.get(conn.uuid or "?", [])
                    if c.closed_at_ms is None]
            if not live and (conn.uuid or "?"):
                self.active.pop(conn.uuid, None)

    def stats(self, uuid):
        """返回 uuid 的所有连接统计与当前活跃连接数。"""
        conns = self.conns_of(uuid)
        return {
            "uuid": uuid,
            "total_conns": len(conns),
            "active_now": len([c for c in conns if c.closed_at_ms is None]),
            "conns": [{
                "role": c.role,
                "connected_at_ms": c.connected_at_ms,
                "closed_at_ms": c.closed_at_ms,
                "duration_ms": (c.closed_at_ms - c.connected_at_ms)
                                if c.closed_at_ms and c.connected_at_ms else None,
                "frames": c.frame_count,
                "bytes": c.byte_count,
                "close_code": c.close_code,
            } for c in conns],
        }

    def stop(self):
        if self._server:
            try:
                self._server.close()
            except OSError:
                pass


# ==================== 探针步骤 ====================
class AudioForkProbe:
    def __init__(self, args):
        self.args = args
        self.esl = None
        self.listener = None
        self.uuid = args.uuid
        self.results = {}
        # 探针记录目录(报告 + 样本),默认 probes/fs_audio_fork_probe_run_<ts>
        run_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.run_dir = os.path.join(_THIS_DIR, f"fs_audio_fork_probe_run_{run_ts}")
        os.makedirs(self.run_dir, exist_ok=True)

    # ------------------------------------------------------------------
    def connect_esl(self):
        """连接默认测试 FS(见 common/config.py),失败即退出(环境不可用)。"""
        self.esl = EslHelper(config.ESL_HOST, config.ESL_PORT, config.ESL_PASSWORD)
        if not self.esl.connect():
            logger.error("ESL 连接失败: %s:%s(环境不可达,探针无法执行)",
                         config.ESL_HOST, config.ESL_PORT)
            return False
        return True

    def pick_uuid(self):
        """自动挑选活动通道: 优先有 answer 状态的通道;失败提示先跑 cc_e2e_test.py。"""
        if self.uuid:
            return True
        channels = self.esl.show_channels()
        if not channels:
            logger.error("FS 当前无活动通道。探针需要一通媒体活动呼叫(参考文档 5.1),\n"
                         "请先执行 cc_e2e_test.py --scenarios 1 建立内部通话,再以 --uuid 指定通道 uuid")
            return False
        # 优先挑选已桥接(有 other-leg)或 CS_EXECUTE/CS_ANSWER 状态的通道
        def score(ch):
            st = (ch.get("state") or ch.get("Channel-State") or "").upper()
            if "EXECUTE" in st or "ANSWER" in st:
                return 0
            if "BRIDGE" in st:
                return 1
            return 2
        channels.sort(key=score)
        self.uuid = channels[0].get("uuid") or channels[0].get("Unique-ID")
        logger.info("自动选择通道 uuid=%s(共 %d 条活跃)",
                    self.uuid, len(channels))
        return True

    # ------------------------------------------------------------------
    def fork_cmd(self, mix, sample_rate, ws_port, tag, metadata=None, bugname=None):
        """下发 uuid_audio_fork start,返回 (ok, 原始回复)。

        注意: 模块以 bugname 为键在通道挂 media bug(同名重复 start 返回 -ERR
        "bug already attached"),同 uuid 多 fork 并存必须显式异名 bugname
        (2026-09-05 双 fork 冲突根因定位,见仓库 FsClient.startAudioFork javadoc)。
        """
        ws_url = (f"ws://{self.args.ws_url_host}:{ws_port}/cc/ws"
                  f"?type=audio_fork&key={self.args.auth_key}&uuid={self.uuid}"
                  f"&fs_address={self.args.fs_address}&role=recording&probe={tag}")
        if metadata is None:
            metadata = json.dumps({"probe": tag, "recordId": f"probe-{tag}-{int(time.time()*1000)}"})
        # 命令位置: uuid start <ws> <mix> <rate> [bugname] [metadata]
        args = f"{mix} {sample_rate}"
        if bugname:
            args += f" {bugname}"
        args += f" '{metadata}'"
        cmd = f"uuid_audio_fork {self.uuid} start {ws_url} {args}"
        resp = self.esl.send_command(cmd, timeout=10)
        body = resp.get("Body", "") or resp.get("Reply-Text", "")
        ok = any(m in body.upper() for m in REPLY_OK_MARKERS)
        logger.info("[fork] start %s %sHz bugname=%s → %s => %s", mix, sample_rate, bugname or "(默认)", ws_url, body.strip())
        return ok, body.strip()

    def fork_stop(self):
        resp = self.esl.send_command(f"uuid_audio_fork {self.uuid} stop", timeout=10)
        body = resp.get("Body", "") or resp.get("Reply-Text", "")
        logger.info("[fork] stop => %s", body.strip())
        return body.strip()

    def uuid_record_start(self, path):
        """shadow 期对照: FS 本地 uuid_record 落盘。"""
        self.esl.send_command(f"uuid_record {self.uuid} start {path}", timeout=10)

    def uuid_record_stop(self):
        self.esl.send_command(f"uuid_record {self.uuid} stop", timeout=10)

    # ------------------------------------------------------------------
    def observe(self, uuid, seconds):
        """观察窗口内该 uuid 的累计帧数增量,返回 (连接数, 帧增量)。"""
        before = sum(c.frame_count for c in self.listener.conns_of(uuid))
        time.sleep(seconds)
        after = sum(c.frame_count for c in self.listener.conns_of(uuid))
        active = len([c for c in self.listener.conns_of(uuid) if c.closed_at_ms is None])
        return active, after - before

    def run_step(self, name):
        method = getattr(self, f"step_{name}", None)
        if method is None:
            logger.error("未知探针步骤: %s", name)
            return False
        ok, detail = method()
        self.results[name] = {"passed": ok, "detail": detail}
        logger.info("==== 探针 %s 结果: %s ====", name, "PASS" if ok else "FAIL")
        return ok

    # ------------------------------------------------------------------
    def step_T1(self):
        """T1: 同 uuid 先后 mono → stereo 双 fork,验证并存且均持续推流。"""
        logger.info("[T1] 启动 fork#1(mono)")
        ok1, r1 = self.fork_cmd("mono", self.args.sample_rate, self.args.listen_port, "t1-mono")
        if not ok1:
            return False, {"start_mono": r1, "结论": "mono fork 启动失败,疑似同 uuid 已有 fork 或模块异常"}
        c1 = self.listener.wait_conn(self.uuid, timeout_s=10, expect=1)
        if not c1:
            return False, {"start_mono": r1, "结论": "fork#1 未建立 WS"}
        time.sleep(2)
        logger.info("[T1] fork#1 WS 已建立,启动 fork#2(stereo)")
        # 双 fork 必须异名 bugname(模块按 bugname 分键挂 media bug): 第二 fork 显式命名,验证 R1 前提
        ok2, r2 = self.fork_cmd("stereo", self.args.sample_rate, self.args.listen_port,
                                "t1-stereo", bugname="probe-recording")
        if not ok2:
            return False, {"start_mono": r1, "start_stereo": r2,
                           "结论": "stereo fork 启动失败(可能 mono 被覆盖或互斥)"}
        conns = self.listener.wait_conn(self.uuid, timeout_s=10, expect=2)
        time.sleep(1)
        # 双连接并存观察: 各 3 秒窗口
        active1, delta1 = self.observe(self.uuid, 3)
        conns_detail = [{"role": c.role, "frames": c.frame_count, "bytes": c.byte_count}
                        for c in self.listener.conns_of(self.uuid)]
        both_alive = active1 >= 2
        # 判定: 两条连接都持续收帧(允许 mono 连接仅收到静音帧时的低帧率,以 >0 为底线)
        live = [c for c in self.listener.conns_of(self.uuid) if c.closed_at_ms is None]
        got_frames = [c.frame_count > MIN_FRAMES_WINDOW for c in live]
        passed = both_alive and all(got_frames)
        return passed, {"双fork并存": both_alive, "连接明细": conns_detail,
                        "帧增量(3s)": delta1,
                        "结论": "双 fork 并存且均推流 → R1 前提成立" if passed
                        else "双 fork 未并存或某条无推流 → 需复测,疑似走 R2"}

    def step_T2(self):
        """T2: 服务端主动关闭其中一条 WS,确认另一条不受影响。"""
        live = [c for c in self.listener.conns_of(self.uuid) if c.closed_at_ms is None]
        if len(live) < 2:
            return False, {"原因": "需要 T1 双 fork 并存后才可执行 T2(请按 T1,T2 顺序运行)"}
        target = live[0]
        keeper = live[1]
        logger.info("[T2] 服务端主动关闭 %s(role=%s),观察 %s(role=%s)",
                    target.uuid, target.role, keeper.uuid, keeper.role)
        frames_before = keeper.frame_count
        target.close_server_side(code=1001)
        time.sleep(2)
        still = [c for c in self.listener.conns_of(self.uuid) if c.closed_at_ms is None]
        frames_after = keeper.frame_count
        target_closed = target.closed_at_ms is not None
        keeper_alive = keeper in still and frames_after > frames_before
        passed = target_closed and keeper_alive
        return passed, {"被关连接已关闭": target_closed,
                        "存活连接继续推流": keeper_alive,
                        "keeper 帧增量(2s)": frames_after - frames_before,
                        "结论": "旁路连接关闭不影响另一 fork → R1 必要条件成立" if passed
                        else "另一条 fork 受影响 → 双 fork 相互绑定,存疑"}

    def step_T3(self):
        """T3: fork(stereo)与 uuid_record 同通道并存(shadow 期双写前提)。"""
        rec_path = f"/tmp/fs_audio_fork_probe_{self.uuid[:8]}_{int(time.time())}.wav"
        self.uuid_record_start(rec_path)
        time.sleep(2)
        ok, r = self.fork_cmd("stereo", self.args.sample_rate,
                              self.args.listen_port, "t3-stereo", bugname="probe-rec")
        if not ok:
            self.uuid_record_stop()
            return False, {"uuid_record": rec_path, "fork_stereo": r,
                           "结论": "record 后 fork 启动失败"}
        conns = self.listener.wait_conn(self.uuid, timeout_s=10)
        time.sleep(3)
        # 帧统计与 fork 存活判定(record 文件大小留待人工核对 /tmp 下产物)
        frames = sum(c.frame_count for c in self.listener.conns_of(self.uuid))
        fork_alive = any(c.closed_at_ms is None for c in self.listener.conns_of(self.uuid))
        passed = fork_alive and frames > 0
        self.uuid_record_stop()
        logger.info("[T3] record 文件: %s(停止录制,留待核对大小)", rec_path)
        return passed, {"fork_alive": fork_alive, "fork_frames": frames,
                        "record_path": rec_path,
                        "结论": "fork 与 uuid_record 并存 → shadow 对拍前提成立" if passed
                        else "并存失败"}

    def step_T4(self):
        """T4: stereo 声道归属样本采集(双声道 L16 落盘,供人工/工具核对)。"""
        # 需要监听器带样本输出;重启监听器成本高,改为提示先建样本监听运行
        if not self.listener.sample_out:
            logger.info("[T4] 当前未开样本输出(--sample-out),自动将样本目录设为探针 run 目录")
            self.listener.sample_out = self.run_dir
        ok, r = self.fork_cmd("stereo", self.args.sample_rate,
                              self.args.listen_port, "t4-stereo")
        if not ok:
            return False, {"start_stereo": r}
        conns = self.listener.wait_conn(self.uuid, timeout_s=10)
        time.sleep(self.args.t4_seconds)
        conn = next((c for c in self.listener.conns_of(self.uuid)
                     if c.closed_at_ms is None), None)
        sample_path = None
        if conn and conn.sample_file:
            sample_path = conn.sample_file.name
        passed = conn is not None and conn.frame_count > MIN_FRAMES_WINDOW
        return passed, {"frames": conn.frame_count if conn else 0,
                        "sample_pcm": sample_path,
                        "说明": "stereo=L16 双声道帧交错(左=客户/右=坐席归属需听感核对,"
                                "见演进档 5.1 T4;mixed 混音验证另跑 --mix-seq mixed)"}

    def step_T5(self):
        """T5: fork stop 与挂断的 WS 关闭时序(无悬挂)。"""
        ok, r = self.fork_cmd("mono", self.args.sample_rate,
                              self.args.listen_port, "t5-mono")
        if not ok:
            return False, {"start_mono": r}
        conns = self.listener.wait_conn(self.uuid, timeout_s=10)
        time.sleep(1)
        t0 = time.time()
        self.fork_stop()
        deadline = time.time() + 10
        while time.time() < deadline:
            if all(c.closed_at_ms is not None for c in
                   self.listener.conns_of(self.uuid) if c.connected_at_ms):
                break
            time.sleep(0.2)
        close_delay_ms = None
        for c in self.listener.conns_of(self.uuid):
            if c.closed_at_ms and c.connected_at_ms:
                close_delay_ms = c.closed_at_ms - int(t0 * 1000)
        passed = close_delay_ms is not None and close_delay_ms < 5000
        return passed, {"stop→WS关闭时延(ms)": close_delay_ms,
                        "结论": "fork stop 后 WS 及时关闭,无悬挂" if passed
                        else "WS 未在 5s 内关闭,存在悬挂"}

    def step_T6(self):
        """T6: 采样率帧计量核对(8k/16k)与 soak 资源观察(可选)。"""
        rate = self.args.sample_rate
        expect_bytes = rate // 1000 * FRAME_MS * BYTES_PER_SAMPLE
        ok, r = self.fork_cmd("mono", rate, self.args.listen_port, "t6-mono")
        if not ok:
            return False, {"start_mono": r}
        conns = self.listener.wait_conn(self.uuid, timeout_s=10)
        if not conns:
            return False, {"原因": "fork WS 未建立"}
        time.sleep(5)
        conn = conns[0]
        bytes_per_frame = (conn.byte_count / conn.frame_count) if conn.frame_count else 0
        expect_frame_rate = 1000 / FRAME_MS
        actual_frame_rate = conn.frame_count / max(1, (time.time() - conn.connected_at_ms / 1000))
        passed = conn.frame_count > 0 and abs(bytes_per_frame - expect_bytes) <= 2
        detail = {
            "采样率": rate, "期望帧字节": expect_bytes, "实测均帧字节": round(bytes_per_frame, 1),
            "期望帧率(/s)": expect_frame_rate, "实测帧率(/s)": round(actual_frame_rate, 1),
            "soak_minutes": self.args.soak_minutes,
            "说明": "长通话(≥30min)资源表现需 --soak-minutes N 观察;本步骤只核对帧计量",
        }
        if self.args.soak_minutes > 0:
            logger.info("[T6] soak 观察 %d 分钟(期间记录帧节奏稳定性)...", self.args.soak_minutes)
            t0 = time.time()
            samples = []
            while time.time() - t0 < self.args.soak_minutes * 60:
                time.sleep(30)
                cur = next((c for c in self.listener.conns_of(self.uuid)
                            if c.closed_at_ms is None), None)
                if not cur:
                    detail["soak_early_close"] = True
                    break
                samples.append(cur.frame_count)
            detail["soak_frame_samples"] = samples
            detail["soak_连续无断流"] = len(samples) >= 2
        return passed, detail

    # ------------------------------------------------------------------
    def report(self, steps):
        """输出 JSON 探针报告(留档)并给出 R1/R2 判定建议。"""
        report_path = os.path.join(self.run_dir, "probe_report.json")
        t1 = self.results.get("T1", {}).get("passed")
        t2 = self.results.get("T2", {}).get("passed")
        r_verdict = ("R1(主路线): 同 uuid 双 fork 并存成立,演进档按 6-8 章执行"
                     if (t1 and t2) else
                     "R2(备选)或需复测: 双 fork 并存未成立,演进档 6-8 章不适用,另立专项")
        report = {
            "generated_at": datetime.now().isoformat(),
            "fs": f"{config.ESL_HOST}:{config.ESL_PORT}",
            "uuid": self.uuid,
            "sample_rate": self.args.sample_rate,
            "steps": self.results,
            "verdict": r_verdict,
            "注意": "本报告为阶段0决策门输出;若本次为环境不可达的'待环境验证'留档运行,"
                    "verdict 仅供参考,须在测试 FS 具备活动通话后复跑确认。",
        }
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        logger.info("探针报告: %s", report_path)
        logger.info("判定建议: %s", r_verdict)
        for s in steps:
            if s in self.results:
                logger.info("[%s] %s", s, json.dumps(self.results[s], ensure_ascii=False))


def parse_args():
    p = argparse.ArgumentParser(description="FS 能力探针(演进档阶段0,T1-T6)")
    p.add_argument("--uuid", default=None, help="被 fork 的活动通道 uuid(缺省自动选取)")
    p.add_argument("--steps", default="T1,T2,T3,T5,T6",
                   help="逗号分隔步骤,默认 T1,T2,T3,T5,T6(全跑用 T1,T2,T3,T4,T5,T6)")
    p.add_argument("--listen-port", type=int, default=9876, help="fork WS 监听端口")
    p.add_argument("--ws-url-host", default=None,
                   help="下发到 FS 的 ws 地址(FS 可回连);缺省取 --listen-host 值")
    p.add_argument("--listen-host", default="0.0.0.0",
                   help="监听地址(FS 回连;不可达时建议经 ssh 部署到 FS 宿主机运行)")
    p.add_argument("--auth-key", default="yudao-cc",
                   help="握手 key(与 cc.audio-fork.auth-key 一致,未改默认时用默认值)")
    p.add_argument("--fs-address", default=None,
                   help="URL 中 fs_address 参数(host:port),缺省取 ESL host")
    p.add_argument("--sample-rate", type=int, default=16000, choices=[8000, 16000])
    p.add_argument("--soak-minutes", type=int, default=0, help="T6 soak 分钟数(0=跳过)")
    p.add_argument("--t4-seconds", type=int, default=20, help="T4 样本采集时长(秒)")
    p.add_argument("--sample-out", default=None, help="PCM 样本输出目录(缺省=本次 run 目录)")
    return p.parse_args()


def main():
    args = parse_args()
    if args.ws_url_host is None:
        # 缺省: 与监听同址(部署到 FS 宿主机时用宿主内网/公网地址)
        args.ws_url_host = args.listen_host if args.listen_host != "0.0.0.0" \
            else socket.gethostname()
    if args.fs_address is None:
        args.fs_address = f"{config.ESL_HOST}:{config.ESL_PORT}"
    steps = [s.strip().upper() for s in args.steps.split(",") if s.strip()]

    probe = AudioForkProbe(args)
    if not probe.connect_esl():
        return 1
    if not probe.pick_uuid():
        return 1

    sample_out = args.sample_out or os.path.join(probe.run_dir, "samples")
    os.makedirs(sample_out, exist_ok=True)
    probe.listener = ForkWsListener(host=args.listen_host, port=args.listen_port,
                                    sample_out=sample_out,
                                    mix_type="stereo", sample_rate=args.sample_rate)
    probe.listener.start()
    time.sleep(0.5)

    try:
        for s in steps:
            if not probe.run_step(s):
                # 步骤失败不中断(独立判定),T4 人工分析尤其如此
                logger.warning("[%s] 未通过,继续后续步骤", s)
    finally:
        probe.listener.stop()
        probe.report(steps)
    return 0


if __name__ == "__main__":
    sys.exit(main())
