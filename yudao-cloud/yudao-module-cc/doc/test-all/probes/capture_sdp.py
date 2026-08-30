#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
通过 ESL 事件订阅捕获场景1内部呼叫的完整 SDP 流。
触发方式：脚本启动后，在浏览器中由 1001 拨打 1002 接听后挂断。
输出：每条腿的 remote/local SDP，以及关键事件流。
"""
import os
import sys
import time
import threading
import logging
import json

# 公共组件目录(common/) 路径装配: esl_helper.py / config.py 均位于 ../common
_COMMON_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "common")
if _COMMON_DIR not in sys.path:
    sys.path.insert(0, _COMMON_DIR)
from esl_helper import EslHelper
from config import ESL_HOST, ESL_PORT, ESL_PASSWORD

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('CaptureSdp')

# 关注的 SDP 字段
SDP_KEYS = [
    'variable_switch_r_sdp',  # 远端 SDP（对方发来的）
    'variable_switch_l_sdp',  # 本端 SDP（FS 生成的）
    'variable_epd_pre_answer_sdp',
    'variable_rtp_use_codec_string',
    'variable_rtp_audio_recv_pkt_count',
    'variable_rtp_audio_send_pkt_count',
    'variable_media_audio_mode',
    'variable_read_codec',  # 接收 codec
    'variable_write_codec',  # 发送 codec
    'variable_remote_media_ip',  # 远端媒体 IP
    'variable_remote_media_port',  # 远端媒体端口
    'variable_local_media_ip',  # 本端媒体 IP
    'variable_local_media_port',  # 本端媒体端口
    'variable_sip_2833_rx_payload',
    'variable_rtp_secure_media',  # SRTP 协商状态
    'variable_zrtp_secure_media',
    'variable_dtls_cert_fingerprint',  # DTLS 证书指纹
    'variable_webrtc_media',
    'variable_media_webrtc',
    'Caller-Caller-ID-Number',
    'Caller-Callee-ID-Number',
    'Other-Leg-Unique-ID',
    'Channel-State',
    'Answer-State',
]


def dump_event(evt):
    name = evt.get('Event-Name', '')
    uuid = evt.get('Unique-ID', '')[:8]
    caller = evt.get('Caller-Caller-ID-Number', '')
    callee = evt.get('Caller-Callee-ID-Number', '')
    state = evt.get('Channel-State', '')
    answer = evt.get('Answer-State', '')
    print(f'\n===== [{name}] uuid={uuid} caller={caller} callee={callee} state={state}/{answer} =====')
    for k in SDP_KEYS:
        v = evt.get(k)
        if v:
            if 'sdp' in k.lower() and len(v) > 100:
                print(f'  {k}:')
                for line in v.split('\n'):
                    print(f'    | {line}')
            else:
                print(f'  {k} = {v}')


def main():
    esl = EslHelper(ESL_HOST, ESL_PORT, ESL_PASSWORD)
    esl.connect()

    # 订阅详细事件
    esl.send_command(
        'event json CHANNEL_CREATE CHANNEL_PARK CHANNEL_ANSWER CHANNEL_BRIDGE CHANNEL_HANGUP CHANNEL_HANGUP_COMPLETE DTMF CUSTOM')
    print('[capture] 已订阅事件, 请在浏览器中操作 1001 呼叫 1002')
    print('[capture] 监听持续 120 秒...')

    end_time = time.time() + 120
    captured = []

    def reader():
        while time.time() < end_time:
            try:
                evt = esl.wait_for_event(timeout=2)
                if evt is None:
                    continue
                name = evt.get('Event-Name', '')
                if name in ('CHANNEL_PARK', 'CHANNEL_ANSWER', 'CHANNEL_BRIDGE', 'CHANNEL_HANGUP',
                            'CHANNEL_HANGUP_COMPLETE'):
                    captured.append(evt)
                    dump_event(evt)
                    # 桥接后立即 dump 两条腿的完整通道变量
                    if name == 'CHANNEL_BRIDGE':
                        uuid = evt.get('Unique-ID', '')
                        other = evt.get('Other-Leg-Unique-ID', '')
                        for u in [uuid, other]:
                            if u:
                                print(f'\n--- uuid_dump {u[:8]} ---')
                                r = esl.send_command(f'uuid_dump {u}')
                                body = r.get('Body', '') if isinstance(r, dict) else str(r)
                                # 仅打印媒体相关变量
                                for line in body.split('\n'):
                                    if any(k in line for k in
                                           ['sdp', 'codec', 'rtp_', 'media_', 'read_', 'write_', 'remote_',
                                            'local_media', 'webrtc', 'dtls', 'srtp', 'ice']):
                                        print(f'  {line}')
                elif name == 'CHANNEL_HANGUP_COMPLETE':
                    # 挂断时打印挂断原因和媒体统计
                    cause = evt.get('Hangup-Cause', '')
                    print(f'\n[hangup] uuid={evt.get("Unique-ID", "")[:8]} cause={cause}')
                    for k in SDP_KEYS:
                        v = evt.get(k)
                        if v and ('pkt_count' in k or 'codec' in k or 'media' in k):
                            print(f'  {k} = {v}')
            except Exception as e:
                logger.exception('reader error: %s', e)

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    t.join(timeout=125)

    print(f'\n[capture] 共捕获 {len(captured)} 个关键事件')
    esl.disconnect()


if __name__ == '__main__':
    main()
