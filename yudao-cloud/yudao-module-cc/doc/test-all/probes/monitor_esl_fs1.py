#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ESL 事件监控脚本(fs1: 18021)
监控 FS1 上的事件,因为内部呼叫的第一段会路由到 FS1(15560/18021)
"""
import sys, time, logging, socket, os

# 公共组件目录(common/) 路径装配: config.py 位于 ../common
_COMMON_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "common")
if _COMMON_DIR not in sys.path:
    sys.path.insert(0, _COMMON_DIR)
from config import ESL_HOST, ESL_HOST_2, ESL_PORT_2, ESL_PASSWORD_2

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s',
                    handlers=[logging.StreamHandler(sys.stdout),
                              logging.FileHandler(f'logs/esl_monitor_fs1_{time.strftime("%Y%m%d_%H%M%S")}.log')])
logger = logging.getLogger('EslMonitorFs1')


def monitor_events(host, port, password, duration_seconds=180):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(10.0)
    try:
        sock.connect((host, port))
        logger.info('ESL 监控连接成功 %s:%s', host, port)
        buf = b''
        while b'\n\n' not in buf:
            buf += sock.recv(4096)
        logger.info('收到 auth/request')
        sock.sendall(f'auth {password}\n\n'.encode())
        buf = b''
        while b'\n\n' not in buf:
            buf += sock.recv(4096)
        if b'+OK' in buf:
            logger.info('ESL 认证成功')
        else:
            logger.error('ESL 认证失败: %s', buf)
            return
        sock.sendall(b'event plain all\n\n')
        buf = b''
        while b'\n\n' not in buf:
            buf += sock.recv(4096)
        logger.info('已订阅所有事件,开始监控(持续 %d 秒)...', duration_seconds)
        sock.settimeout(1.0)
        start_time = time.time()
        event_count = 0
        while time.time() - start_time < duration_seconds:
            try:
                data = sock.recv(8192)
                if not data:
                    break
                buf += data
                while b'\n\n' in buf:
                    event_data, buf = buf.split(b'\n\n', 1)
                    event_text = event_data.decode('utf-8', errors='replace')
                    event_count += 1
                    fields = {}
                    for line in event_text.split('\n'):
                        if ': ' in line:
                            k, v = line.split(': ', 1)
                            fields[k] = v
                    event_name = fields.get('Event-Name', '')
                    unique_id = fields.get('Unique-ID', '')
                    if any(kw in event_name for kw in ['CHANNEL', 'ORIGINATE', 'BACKGROUND']):
                        if event_name == 'BACKGROUND_JOB':
                            job_cmd = fields.get('Job-Command', '')
                            job_args = fields.get('Job-Command-Arg', '')[:300]
                            logger.info('[BG_JOB] cmd=%s args=%s', job_cmd, job_args)
                        elif event_name == 'CHANNEL_CREATE':
                            dest = fields.get('Caller-Destination-Number', '')
                            state = fields.get('Channel-State', '')
                            logger.info('[CREATE] dest=%s state=%s uuid=%s', dest, state, unique_id[:20])
                        elif event_name == 'CHANNEL_PARK':
                            dest = fields.get('Caller-Destination-Number', '')
                            logger.info('[PARK] dest=%s uuid=%s', dest, unique_id[:20])
                        elif event_name == 'CHANNEL_HANGUP_COMPLETE':
                            cause = fields.get('Hangup-Cause', '')
                            logger.info('[HANGUP] cause=%s uuid=%s', cause, unique_id[:20])
                        elif event_name == 'CHANNEL_ANSWER':
                            logger.info('[ANSWER] uuid=%s', unique_id[:20])
                        elif event_name == 'ORIGINATE':
                            resp = fields.get('Originate-Response', '')
                            cause = fields.get('Originate-Cause', '')
                            logger.info('[ORIGINATE] resp=%s cause=%s uuid=%s', resp, cause, unique_id[:20])
            except socket.timeout:
                continue
        logger.info('监控结束,共收到 %d 个事件', event_count)
    except Exception as e:
        logger.error('监控异常: %s', e, exc_info=True)
    finally:
        try:
            sock.close()
        except Exception:
            pass


if __name__ == '__main__':
    os.makedirs('logs', exist_ok=True)
    duration = int(sys.argv[1]) if len(sys.argv) > 1 else 180
    # 使用 fs1 配置 (ESL_PORT_2=18021)
    monitor_events(ESL_HOST, ESL_PORT_2, ESL_PASSWORD_2, duration)
