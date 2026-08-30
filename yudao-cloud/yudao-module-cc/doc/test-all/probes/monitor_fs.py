# -*- coding: utf-8 -*-
"""
FS 通道与注册状态监控脚本
========================
需求背景: 场景1/5/6 坐席B未收到来电,需精确定位失败点
预期结果: 每2秒打印 FS 通道数 + internal profile 注册数,对照测试日志定位失败环节
"""
import os
import sys
import time
import datetime

# 公共组件目录(common/) 路径装配: esl_helper.py / config.py 均位于 ../common
# (原为绝对路径硬编码 /Users/wenjiaqi/Documents/yudao-cloud-cc/...，已改为相对路径)
_COMMON_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "common")
if _COMMON_DIR not in sys.path:
    sys.path.insert(0, _COMMON_DIR)
from esl_helper import EslHelper
from config import ESL_HOST, ESL_PORT, ESL_PASSWORD, ESL_HOST_2, ESL_PORT_2, ESL_PASSWORD_2


def query(esl, name):
    """查询通道数和注册数"""
    try:
        ch_count = esl.get_channel_count()
        resp = esl.send_command('sofia status profile internal reg', timeout=5.0)
        reg_count = 0
        if resp and isinstance(resp, dict):
            body = resp.get('Body', '') or resp.get('body', '') or ''
            for line in body.split('\n'):
                if 'Total items returned' in line:
                    reg_count = int(line.split(':')[1].strip()) if ':' in line else 0
        print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {name}: 通道数={ch_count}, 注册数={reg_count}")
    except Exception as e:
        print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {name}: 查询异常 {type(e).__name__}: {e}")


def main():
    esl1 = EslHelper(ESL_HOST, ESL_PORT, ESL_PASSWORD)
    esl2 = EslHelper(ESL_HOST_2, ESL_PORT_2, ESL_PASSWORD_2)
    if not esl1.connect():
        print("fs1 连接失败")
        return
    if not esl2.connect():
        print("fs2 连接失败")
        return
    print("监控启动,按 Ctrl+C 停止")
    try:
        while True:
            query(esl1, "fs1(18121)")
            query(esl2, "fs2(18021)")
            time.sleep(2)
    except KeyboardInterrupt:
        print("\n监控停止")
    finally:
        esl1.disconnect()
        esl2.disconnect()


if __name__ == "__main__":
    main()
