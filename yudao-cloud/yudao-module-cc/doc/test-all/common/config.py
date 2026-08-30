# -*- coding: utf-8 -*-
"""
测试脚本环境配置
====================
集中管理测试脚本所需的所有环境配置,包括本地服务地址、远程服务认证、测试坐席信息。
所有配置以常量形式暴露,便于其他模块直接导入使用。

需求背景: 对齐当前部署环境(服务器 62.234.191.165 + 本地开发机 221.216.108.3)。
预期结果: 所有测试组件直接 import 本模块常量,修改配置只需调整本文件。
"""
import os

# 凭据类常量优先读环境变量,缺省回退现值(便于 CI/本地免明文暴露):
#   IPCC_LOGIN_PASSWORD / IPCC_ESL_PASSWORD / IPCC_ESL_PASSWORD_2 /
#   IPCC_MYSQL_PASSWORD / IPCC_REDIS_PASSWORD / IPCC_TP_FS_ESL_PASSWORD /
#   IPCC_TP_AGENT_PASSWORD / IPCC_SIP_PASSWORD / IPCC_IVR_SOFTPHONE_PASSWORD /
#   IPCC_SSH_PASSWORD

# ==================== 本地服务配置 ====================
# 本地 Java 后端地址(由 ij-debugger 启动 YudaoServerApplication,端口 48080)
# LOCAL_BACKEND_URL = "http://localhost:48080"
# 本地前端 Vue 服务地址(pnpm dev,端口 80;端口被占用时自动顺延至81/82/83)
# LOCAL_FRONTEND_URL = "http://localhost:80"

# 线上环境 Java 后端地址
LOCAL_BACKEND_URL = "https://cc.wenmoqi.top/admin-api"
# 线上环境前端 Vue 服务地址
# 注: www.cc.wenmoqi.top 的 HTTPS 证书不含 www SAN(访问报 CERTIFICATE_VERIFY_FAILED),
#     而同证书域 cc.wenmoqi.top 证书合法且托管同一套前端 SPA(与生产前端构建 VITE_BASE_URL 一致),
#     故测试统一走 cc.wenmoqi.top。
LOCAL_FRONTEND_URL = "https://cc.wenmoqi.top"

# 登录账号(管理员)
LOGIN_USERNAME = "admin"
LOGIN_PASSWORD = os.environ.get("IPCC_LOGIN_PASSWORD", "admin123")

# ==================== 远程 FreeSWITCH 配置 ====================
# CC 服务连接的两个 FS 实例(均部署在 62.234.191.165,使用 host 网络模式)
# fs1: docker freeswitch_15560_18021_sse9df, SIP 15560, ESL 18021
# fs2: docker freeswitch_16560_18121_vzgdfx, SIP 16560, ESL 18121
# 测试默认连接 fs2 的 ESL(CC 服务 fs_monitor 选举 fs2 为活动主实例,
#   且 selectFreeSwitchNode 的 hash 选择当前落在 fs2:16560 上)
ESL_HOST = "62.234.191.165"
ESL_PORT = 18121
ESL_PASSWORD = os.environ.get("IPCC_ESL_PASSWORD", "freeswitch@123321")
# 第二个 FS 实例(备用,故障转移测试使用)
ESL_HOST_2 = "62.234.191.165"
ESL_PORT_2 = 18021
ESL_PASSWORD_2 = os.environ.get("IPCC_ESL_PASSWORD_2", "freeswitch@123321")

# FS 宿主机 SSH(运维排查/容器内配置修改用,只增不改)
SSH_HOST = "62.234.191.165"
SSH_USER = "ubuntu"
SSH_PASSWORD = os.environ.get("IPCC_SSH_PASSWORD", "Moqi147852369")

# ==================== 远程 MySQL 配置 ====================
# 与 application-local.yaml 中 spring.datasource.dynamic.datasource.master 一致
MYSQL_HOST = "mysql6.sqlpub.com"
MYSQL_PORT = 3311
MYSQL_USER = "yudaocc"
MYSQL_PASSWORD = os.environ.get("IPCC_MYSQL_PASSWORD", "JOg7SjhZVMbONFg6")
MYSQL_DATABASE = "yudao_cc"

# ==================== 远程 Redis 配置 ====================
# 与 application-local.yaml 中 spring.data.redis 配置一致
# 用途: 场景7自动外呼需预先写入任务上下文(autocall:task:{taskId}),
#       对齐 AutocallServiceImpl.saveTaskContext() 的正常业务流程
REDIS_HOST = "39.107.224.184"
REDIS_PORT = 6379
REDIS_PASSWORD = os.environ.get("IPCC_REDIS_PASSWORD", "Moqi147852369")
REDIS_DATABASE = 0

# ==================== SIP 配置 ====================
# SIP 服务器地址(CC 服务部署在本机,监听 *:5561)
SIP_SERVER_PORT = 5561
# sipproxy 公网地址(对应 application-local.yaml 的 cc.sip-proxy.public-ip)
# FS originate 模拟外部呼入时需通过此地址呼叫到 sipproxy
SIP_PROXY_PUBLIC_IP = "62.234.191.165"
SIP_PROXY_PUBLIC_PORT = 5561
# SIP 域(与 cc_sys_agent.domain 字段一致)
SIP_DOMAIN = "1.com:1"

# ==================== 第三方 FS 网关模拟配置 ====================
# 第三方 FS 实例: docker freeswitch_9988_9966_9my6p4
# - internal profile SIP 端口: 9988(接收注册)
# - external profile SIP 端口: 9977(出局)
# - ESL 端口: 9966, 密码: 123321
# - 模拟坐席 18600000000(密码 123321),用于模拟手机呼叫 4001234
# 注意: 直连云端公网 IP(不依赖本地 SSH 隧道); 云端 fs3 的 9988 仅监听 10.2.0.14/[::1],
#       公网直连 62.234.191.165:9988 需云安全组放行 Mac 出口 IP(125.33.53.38)
THIRD_PARTY_FS_HOST = "62.234.191.165"
THIRD_PARTY_FS_SIP_PORT = 9988
THIRD_PARTY_FS_ESL_PORT = 9966
THIRD_PARTY_FS_ESL_PASSWORD = os.environ.get("IPCC_TP_FS_ESL_PASSWORD", "123321")
# 第三方 FS 上注册的模拟坐席(模拟手机号)
THIRD_PARTY_AGENT_NUMBER = "18600000000"
THIRD_PARTY_AGENT_PASSWORD = os.environ.get("IPCC_TP_AGENT_PASSWORD", "123321")
# 第三方 FS 呼入 CC 服务的测试号码(IVR 入口,路由101 呼入正则 ^(4001234).*)
INBOUND_TEST_NUMBER = "4001234"

# ==================== AI 对话场景配置（场景10，专用路由107） ====================
# 坐席1001（浏览器）拨号触发 AI 对话 IVR 流程的专用号码：命中 cc_call_route id=107 呼出路由
# 注意：只用于 AI 对话场景，不与其他路由（101-106）混用
AI_DIALOGUE_NUMBER = "00600"
# AI 对话路由/流程规格 id（对应 cc_call_route.id=107 + cc_flow_info.id=107）
AI_DIALOGUE_ROUTE_ID = 107
AI_DIALOGUE_FLOW_ID = 107
# 中断词语音文件: 场景10 启动浏览器时经 --use-file-for-fake-audio-capture 注入,
# Chrome 假麦克风循环播放该 WAV, 使坐席上行音频持续包含"转人工"供 ASR 识别命中中断词
AI_INTERRUPT_WAV = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "audio", "interrupt_zhuan_manual.wav")

# ==================== 测试坐席配置 ====================
# 坐席 A(主叫): admin 账号, SIP 账号 1001
AGENT_A = {
    "username": "admin",
    "password": "admin123",
    "sip_number": "1001",
    "user_id": 1,
}
# 坐席 B(被叫): yudao 账号, SIP 账号 1002
AGENT_B = {
    "username": "yudao",
    "password": "admin123",
    "sip_number": "1002",
    "user_id": 100,
}
# 坐席 C(第三方): test 账号, SIP 账号 1003
AGENT_C = {
    "username": "test",
    "password": "admin123",
    "sip_number": "1003",
    "user_id": 104,
}
# SIP 账号密码(与 cc_sys_agent.password 字段一致)
SIP_PASSWORD = os.environ.get("IPCC_SIP_PASSWORD", "123321")

# ==================== 测试场景配置 ====================
# 内部网关名称(用于出局呼叫测试,对应 cc_sipproxy_gateway.name)
INTERNAL_GATEWAY_NAME = "内部网关"
# 第三方网关名称(用于第三方 FS 出局测试)
THIRD_PARTY_GATEWAY_NAME = "第三方网关"
# 自动外呼任务 ID(测试用)
AUTOCALL_TASK_ID = "test-task-001"
# 呼叫拨号前缀(浏览器呼出为 direction=2,现库无 catch-all 路由 → 裸号呼出会被挂断,必须带前缀):
#   - 内部呼叫场景: 9# 前缀命中 route102(flow102) 转内部坐席
#   - 出局呼叫场景: 0# 前缀命中 route105(flow105) 转第三方网关
IVR_DIAL_PREFIX_INTERNAL = "9#"
IVR_DIAL_PREFIX_EXTERNAL = "0#"
# 自动外呼: 被叫号码 + 页面显式选择的呼叫路由 id(route103 → flow103)
AUTOCALL_TARGET_NUMBER = "18600000001"
AUTOCALL_ROUTE_ID = 103
# 坐席组 id(route101 flow101 转坐席组场景,组1 含坐席 1001/1002/1003)
AGENT_GROUP_ID = 1

# ==================== 测试超时配置(毫秒) ====================
# 页面操作超时
PAGE_TIMEOUT = 30000
# 等待元素超时
ELEMENT_TIMEOUT = 10000
# 通话建立超时(通话场景需要较长时间,涉及 SIP 信令往返 + B2BUA 两段对话 + ICE 协商)
# 改进: 从 300s 缩短到 60s
# 原值 300s 是为了等待租户编号缺失时的查询重试,租户上下文补全后场景1 平均 30s 通过,
# 60s 已足够余量。缩短后场景5单轮失败从 5min 降到 1min,避免 3 轮全失败时浪费 15min。
CALL_TIMEOUT = 60000
# SIP 签入超时
SIGNIN_TIMEOUT = 20000

# ==================== 截图与报告配置 ====================
# 截图保存目录
SCREENSHOT_DIR = "screenshots"
# 测试报告保存目录
REPORT_DIR = "reports"
# 日志保存目录
LOG_DIR = "logs"

# ==================== 浏览器配置 ====================
# 是否使用无头模式(默认 False,便于观察)
BROWSER_HEADLESS = False
# 浏览器启动慢动作(毫秒,便于观察)
BROWSER_SLOW_MO = 100
# 视口大小
BROWSER_VIEWPORT = {"width": 1920, "height": 1080}

# ==================== STUN/TURN 配置(与前端 SoftPhone.vue 一致) ====================
# 前端 JsSIP iceServers 使用 stun:39.107.224.184:3478 / turn:39.107.224.184:3478
# (username=yudao-cc, credential=yudao-cc);pjsua 参数为 host:port 格式(无 stun:/turn: 前缀)。
# 用途: 本地 NAT 后的软电话通过 STUN 反射候选 + TURN 中继解决 FS 回程 RTP 不通。
STUN_SERVER = "39.107.224.184:3478"
TURN_SERVER = "39.107.224.184:3478"
TURN_USERNAME = "yudao-cc"
TURN_PASSWORD = os.environ.get("IPCC_TURN_PASSWORD", "yudao-cc")

# ==================== AI 对话场景配置(场景10) ====================
# IVR AI 对话归属的系统用户 ID(与后端 cc.ai.system-user-id 配置保持一致, 默认 1)
AI_SYSTEM_USER_ID = int(os.environ.get("IPCC_AI_SYSTEM_USER_ID", "1"))

# ==================== IVR 流程测试扩展配置(ivr流程测试/ 专用,只增不改) ====================
# IVR 测试软电话账号(注册于第三方 FS 62.234.191.165:9988,域 1.com:1)
# 场景1 主叫 / 场景2 自动外呼被叫
IVR_SOFTPHONE_A = "18600000000"
IVR_SOFTPHONE_B = "18600000001"
# 软电话账号密码(第三方 FS 目录配置)
IVR_SOFTPHONE_PASSWORD = os.environ.get("IPCC_IVR_SOFTPHONE_PASSWORD", "123321")
# 场景3 入局呼叫目标: 4001234@CC sipproxy 公网地址(cc_call_route id=101 呼入路由 → flow101)
IVR_INBOUND_ROUTE_NUM = "4001234"
