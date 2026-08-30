#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ESL 事件监控脚本
================
需求背景: 诊断内部呼叫场景下坐席 B 未收到来电的根因
预期结果: 监控 FS ESL 事件,捕获 originate/INVITE/channel 相关事件,输出到日志
处理逻辑:
    1. 连接 FS ESL,订阅所有事件
    2. 过滤并打印 CHANNEL/INVITE/ORIGINATE 相关事件
    3. 持续运行直到 Ctrl+C 或超时
"""

import os
import sys
import time
import logging
import socket
import threading

# 公共组件目录(common/) 路径装配: config.py 位于 ../common
_COMMON_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "common")
if _COMMON_DIR not in sys.path:
    sys.path.insert(0, _COMMON_DIR)
from config import ESL_HOST, ESL_PORT, ESL_PASSWORD

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(f'logs/esl_monitor_{time.strftime("%Y%m%d_%H%M%S")}.log'),
    ]
)
logger = logging.getLogger('EslMonitor')


def monitor_events(duration_seconds=180):
    """
    监控 FS ESL 事件

    :param duration_seconds: 监控持续时间(秒)
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(10.0)
    try:
        sock.connect((ESL_HOST, ESL_PORT))
        logger.info('ESL 监控连接成功 %s:%s', ESL_HOST, ESL_PORT)

        # 等待 auth/request
        buf = b''
        while b'\n\n' not in buf:
            buf += sock.recv(4096)
        logger.info('收到 auth/request')

        # 发送 auth
        password = ESL_PASSWORD
        sock.sendall(f'auth {password}\n\n'.encode())
        buf = b''
        while b'\n\n' not in buf:
            buf += sock.recv(4096)
        if b'+OK' in buf:
            logger.info('ESL 认证成功')
        else:
            logger.error('ESL 认证失败: %s', buf)
            return

        # 订阅所有事件
        sock.sendall(b'event plain all\n\n')
        buf = b''
        while b'\n\n' not in buf:
            buf += sock.recv(4096)
        logger.info('已订阅所有事件,开始监控(持续 %d 秒)...', duration_seconds)

        # 设置非阻塞读取
        sock.settimeout(1.0)
        start_time = time.time()
        event_count = 0
        originate_events = []
        invite_events = []
        channel_events = []

        while time.time() - start_time < duration_seconds:
            try:
                data = sock.recv(8192)
                if not data:
                    break
                buf += data
                # 解析事件: 以 \n\n 分隔
                while b'\n\n' in buf:
                    event_data, buf = buf.split(b'\n\n', 1)
                    event_text = event_data.decode('utf-8', errors='replace')
                    event_count += 1

                    # 解析事件字段
                    fields = {}
                    for line in event_text.split('\n'):
                        if ': ' in line:
                            k, v = line.split(': ', 1)
                            fields[k] = v

                    event_name = fields.get('Event-Name', '')
                    unique_id = fields.get('Unique-ID', '')
                    channel_name = fields.get('Channel-Name', '')

                    # 过滤关键事件: CHANNEL/ORIGINATE/INVOKE/CREATE
                    if any(kw in event_name for kw in ['CHANNEL', 'ORIGINATE', 'CODEC', 'REINVITE']):
                        logger.info('[EVENT %d] %s | uuid=%s | channel=%s',
                                    event_count, event_name, unique_id[:20] if unique_id else '', channel_name)

                        # 打印关键字段
                        if event_name in ('CHANNEL_CREATE', 'CHANNEL_PARK', 'CHANNEL_ANSWER',
                                          'CHANNEL_HANGUP', 'CHANNEL_HANGUP_COMPLETE',
                                          'ORIGINATE', 'BACKGROUND_JOB'):
                            if event_name == 'BACKGROUND_JOB':
                                job_cmd = fields.get('Job-Command', '')
                                job_args = fields.get('Job-Command-Arg', '')[:200]
                                logger.info('  [BG_JOB] cmd=%s args=%s', job_cmd, job_args)
                            elif event_name == 'ORIGINATE':
                                logger.info('  [ORIGINATE] fields=%s',
                                            {k: v for k, v in fields.items()
                                             if k in ('Originate-Response', 'Originate-Cause',
                                                      'Caller-Destination-Number', 'Channel-Name')})
                            elif event_name == 'CHANNEL_CREATE':
                                dest = fields.get('Caller-Destination-Number', '')
                                state = fields.get('Channel-State', '')
                                logger.info('  [CREATE] dest=%s state=%s', dest, state)
                            elif event_name == 'CHANNEL_HANGUP_COMPLETE':
                                cause = fields.get('Hangup-Cause', '')
                                logger.info('  [HANGUP] cause=%s', cause)

                        if event_name == 'ORIGINATE':
                            originate_events.append(fields)
                        elif event_name == 'CHANNEL_CREATE':
                            channel_events.append(fields)

            except socket.timeout:
                continue

        logger.info('监控结束,共收到 %d 个事件, ORIGINATE=%d, CHANNEL_CREATE=%d',
                    event_count, len(originate_events), len(channel_events))

    except Exception as e:
        logger.error('监控异常: %s', e, exc_info=True)
    finally:
        try:
            sock.close()
        except Exception:
            pass


if __name__ == '__main__':
    import os

    os.makedirs('logs', exist_ok=True)
    duration = int(sys.argv[1]) if len(sys.argv) > 1 else 180
    monitor_events(duration)
