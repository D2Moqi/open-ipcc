# -*- coding: utf-8 -*-
"""
聚焦验证脚本: 场景1 内部呼叫 (坐席A 1001 -> 坐席B 1002)
=========================================================
目的: 验证 cc_fs_config.ip=<A服务器内网> 时, sipproxy 能正确把坐席 INVITE
      转发到容器 IP(宿主机可达), 触发 FS park -> CHANNEL_PARK -> cc-server 路由 -> B 振铃接听。

说明: 本机(当前 Mac)无法直连云端 ESL/SIP 端口(18021/18121/5561 被安全组拦截),
      因此原 test_scenarios.py 的 setup() 会因 esl.connect() 失败而中止。
      本脚本不依赖 ESL, 仅用浏览器走真实链路:
        JsSIP(浏览器) -> <B服务器域名>(nginx) -> sipproxy(:5561) -> FS park(<A服务器内网>:15580)
        -> CHANNEL_PARK -> cc-server 路由 -> FS originate -> B 振铃 -> 接听 -> bridge
      并以 DB 中 call_type=3 的通话记录作为客观证据。

运行: cd doc/test-all && python3 probes/verify_scenario1_fix.py
"""
import os
import sys
import time
from datetime import datetime

# 公共组件目录装配
_COMMON_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "common")
if _COMMON_DIR not in sys.path:
    sys.path.insert(0, _COMMON_DIR)

from browser_test import BrowserTest
import pymysql
# 配置统一从 common/config.py 导入(凭据类支持 IPCC_* 环境变量覆盖), 避免本地硬编码重复
from config import LOCAL_FRONTEND_URL, MYSQL_HOST, MYSQL_PORT, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DATABASE, AGENT_A, \
    AGENT_B


def db_count_internal_calls_since(start_dt):
    conn = pymysql.connect(host=MYSQL_HOST, port=MYSQL_PORT, user=MYSQL_USER,
                           password=MYSQL_PASSWORD, db=MYSQL_DATABASE,
                           charset="utf8mb4", connect_timeout=15)
    try:
        with conn.cursor() as cur:
            sql = ("SELECT id, call_type, caller, called, create_time "
                   "FROM cc_call_record "
                   "WHERE call_type = 3 AND create_time >= %s "
                   "ORDER BY id DESC LIMIT 10")
            cur.execute(sql, (start_dt.strftime("%Y-%m-%d %H:%M:%S"),))
            rows = cur.fetchall()
        return rows
    finally:
        conn.close()


def main():
    print("########## 场景1 聚焦验证 (DB ip=<A服务器内网>) ##########")
    test_start = datetime.now()
    print(f"[时间] 测试开始: {test_start}")

    browser = BrowserTest(headless=True, slow_mo=0)
    if not browser.start():
        print("[结果] FAIL: 浏览器启动失败")
        return 1
    try:
        # ---- L1+L2: 坐席A 登录 + SIP签入 + 就绪 ----
        print("=== 坐席A 登录签入 ===")
        page_a = browser.new_page()
        browser.navigate_to_login(page_a, LOCAL_FRONTEND_URL)
        if not browser.login(page_a, AGENT_A["username"], AGENT_A["password"]):
            print("[结果] FAIL: 坐席A登录失败");
            browser.take_screenshot(page_a, "A_login_fail");
            return 1
        if not browser.signin(page_a):
            print("[结果] FAIL: 坐席A SIP签入失败");
            browser.take_screenshot(page_a, "A_signin_fail");
            return 1
        if not browser.set_ready(page_a, ready=True):
            print("[结果] FAIL: 坐席A 设置就绪失败");
            browser.take_screenshot(page_a, "A_ready_fail");
            return 1
        print("[OK] 坐席A 就绪")

        # ---- L1+L2: 坐席B 登录 + SIP签入 + 就绪 ----
        print("=== 坐席B 登录签入 ===")
        page_b = browser.new_context_page()
        browser.navigate_to_login(page_b, LOCAL_FRONTEND_URL)
        if not browser.login(page_b, AGENT_B["username"], AGENT_B["password"]):
            print("[结果] FAIL: 坐席B登录失败");
            browser.take_screenshot(page_b, "B_login_fail");
            return 1
        if not browser.signin(page_b):
            print("[结果] FAIL: 坐席B SIP签入失败");
            browser.take_screenshot(page_b, "B_signin_fail");
            return 1
        if not browser.set_ready(page_b, ready=True):
            print("[结果] FAIL: 坐席B 设置就绪失败");
            browser.take_screenshot(page_b, "B_ready_fail");
            return 1
        print("[OK] 坐席B 就绪")

        # ---- 场景1: A 发起内部呼叫到 B(1002) ----
        print(f"=== 坐席A 呼叫 {AGENT_B['sip_number']} (内部呼叫) ===")
        if not browser.make_call(page_a, AGENT_B["sip_number"]):
            print("[结果] FAIL: 坐席A 发起呼叫失败");
            browser.take_screenshot(page_a, "A_makecall_fail");
            return 1
        print("[OK] 坐席A 已发起呼叫")

        # ---- B 等待来电并接听 ----
        print("=== 坐席B 等待来电并接听 ===")
        if not browser.wait_for_incoming_call(page_b, timeout=60000):
            print("[结果] FAIL: 坐席B 未收到来电(B 未振铃 -> sipproxy 未把 INVITE 送到 FS park)");
            browser.take_screenshot(page_b, "B_no_incoming");
            # 额外诊断: 打印 A 当前状态
            print("[诊断] 坐席A 状态:", browser.get_status_text(page_a))
            return 1
        if not browser.answer_call(page_b):
            print("[结果] FAIL: 坐席B 接听失败");
            browser.take_screenshot(page_b, "B_answer_fail");
            return 1
        print("[OK] 坐席B 已接听")

        # ---- 验证双方通话建立 ----
        if not browser.wait_for_call_connected(page_a, timeout=60000):
            print("[结果] FAIL: 坐席A 通话未建立(桥接未完成)");
            browser.take_screenshot(page_a, "A_connect_fail");
            return 1
        status_a = browser.get_status_text(page_a)
        status_b = browser.get_status_text(page_b)
        print(f"[状态] A={status_a}  B={status_b}")
        if "通话中" not in status_a or "通话中" not in status_b:
            print("[结果] FAIL: 双方未全部进入通话中");
            browser.take_screenshot(page_a, "not_connected");
            return 1
        print("[OK] 双方通话建立")

        # 通话保持几秒, 让 CDR 有意义
        time.sleep(5)

        # ---- 挂断 ----
        print("=== 坐席A 挂断 ===")
        if not browser.hangup(page_a):
            print("[WARN] 坐席A 挂断失败, 跳过")
        browser.wait_for_call_ended(page_a, timeout=15000)
        browser.wait_for_call_ended(page_b, timeout=15000)
        print("[OK] 通话结束")

        # ---- DB 证据: call_type=3 记录 ----
        time.sleep(2)
        rows = db_count_internal_calls_since(test_start)
        print(f"[DB] call_type=3 记录数(自测试开始): {len(rows)}")
        for r in rows:
            print("   ", r)
        if len(rows) >= 1:
            print("\n########## 结果: PASS ##########")
            print("场景1 内部呼叫成功: sipproxy 已将 INVITE 转发到 <A服务器内网>:15580(FS park),")
            print("CHANNEL_PARK 触发, cc-server 路由到坐席B 并桥接, CDR(call_type=3) 已生成。")
            return 0
        else:
            print("\n########## 结果: FAIL ##########")
            print("通话界面显示已建立, 但 DB 未生成 call_type=3 记录(CDR 落库失败或字段不符)。")
            return 1
    except Exception as e:
        import traceback
        traceback.print_exc()
        return 1
    finally:
        try:
            browser.stop()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
