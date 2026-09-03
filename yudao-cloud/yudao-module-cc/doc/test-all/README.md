# yudao-cloud-cc 端到端测试套件

呼叫中心系统（yudao-module-cc）唯一端到端测试体系，覆盖内部呼叫、出局呼叫、入局 IVR、保持/恢复、咨询转接、自动外呼、客服组繁忙、满意度评价、AI
对话共 9 大业务场景，并提供并发呼入压测（场景 11）与注册模式 4G 网关呼入/呼出（场景 12/13）等扩展场景；独立并发压测脚本分级
10/20/…/100。

## 目录结构

```
test-all/
├── cc_e2e_test.py          # 唯一主脚本(L0 环境核对 + 场景 1/2/3/5/6/7/8/9/10/11/12/13 + L5 数据校验)
├── cc_concurrent_test.py   # 并发呼入压测脚本(独立运行, 分级 10~100, 可选 --queue-test)
├── requirements.txt        # Python 依赖
├── common/                 # 公共层
│   ├── config.py           # 环境配置(凭据优先读环境变量 IPCC_* 前缀)
│   ├── browser_test.py     # Playwright 浏览器封装(登录/签入/拨号/接听/挂断/转接)
│   ├── concurrent_helpers.py # 并发压测公共组件(主叫池/状态采样器/报告器)
│   ├── data_spec.py        # 路由/流程/坐席/网关规格与 L0 数据核对
│   ├── db_helper.py        # MySQL 辅助
│   ├── esl_helper.py       # FreeSWITCH ESL 辅助(事件订阅/命令/通道统计)
│   ├── redis_helper.py     # Redis 辅助(自动外呼任务上下文)
│   └── sip_client.py       # pjsua 软电话客户端(模拟外部主叫/被叫)
├── probes/                 # 诊断工具(ESL 事件监控/FS 通道检查/SDP 抓取等, 按需使用)
└── screenshots/            # 失败截图(自动生成)
```

## 环境准备

```bash
pip install -r requirements.txt
# 凭据通过环境变量注入(缺省回退 common/config.py 现值):
#   IPCC_LOGIN_PASSWORD / IPCC_ESL_PASSWORD / IPCC_ESL_PASSWORD_2 /
#   IPCC_MYSQL_PASSWORD / IPCC_REDIS_PASSWORD / IPCC_TP_FS_ESL_PASSWORD /
#   IPCC_TP_AGENT_PASSWORD / IPCC_SIP_PASSWORD / IPCC_IVR_SOFTPHONE_PASSWORD / IPCC_SSH_PASSWORD /
#   IPCC_TURN_PASSWORD
```

依赖外部环境（与 `common/config.py` 对齐）：

- 线上后端 `https://<B服务器域名>`（yudao-server 48080，sipproxy 内嵌）
- FreeSWITCH 双实例（fs1: SIP 15560/ESL 18021，fs2: SIP 16560/ESL 18121）+ 第三方 FS（SIP 9988/ESL 9966）
- MySQL / Redis / 浏览器（Playwright Chromium）

## 运行方式

```bash
# 全量场景(默认 1,2,3,5,6,7; 每场景最多 3 轮, 轮间退避 10s)
python3 cc_e2e_test.py

# 指定场景(场景 8/9/10/11 为可选项, 须显式指定)
python3 cc_e2e_test.py --scenarios 6
python3 cc_e2e_test.py --scenarios 8,9,10
python3 cc_e2e_test.py --scenarios 11 --rounds 1   # 并发呼入压测轻量版(10/20 两级)

# 只做 L0 环境/数据核对(不执行场景), 退出码 0=通过 2=失败
python3 cc_e2e_test.py --check-only

# CI 无头模式 + 单轮
python3 cc_e2e_test.py --headless --rounds 1

# 跳过 L0 核对 / L0 数据缺失时自动修复(白名单)
python3 cc_e2e_test.py --skip-l0
python3 cc_e2e_test.py --auto-fix
```

## 场景说明

| 编号 | 场景               | 入口/流程               | 验证要点                                                                 |
|------|--------------------|-------------------------|--------------------------------------------------------------------------|
| 1    | 内部呼叫           | 9#1002 / flow102        | A→B 通话建立、双方通话中、CDR                                            |
| 2    | 出局呼叫           | 0#18600000000 / flow105 | 经网关出局、对端应答、CDR                                                |
| 3    | 入局 IVR 全链路    | pjsua 4001234 / flow101 | IVR 放音(含 TTS)、收号、IF 分支、转坐席组、坐席接听、挂断联动、CDR       |
| 5    | 保持/恢复          | 通话中保持              | 保持成功轮 ≥1（3 轮中），降级通过                                        |
| 6    | 咨询转接           | REFER attended → 1003   | A-B 基线、hold、originate C、C 接听、A-C 咨询、A 挂断确认、B-C 桥接、CDR |
| 7    | 自动外呼           | flow103                 | 任务上下文预置、页面建任务、外呼接通、记录状态                           |
| 8    | 客服组繁忙(可选)   | 00300xxx / flow104      | 忙提示音、流程终态                                                       |
| 9    | 满意度评价(可选)   | 00100xxx / flow106      | 收号节点、DTMF、方法节点、流程终态                                       |
| 10   | AI 对话(可选)      | 00600 / flow107         | ASR/TTS、中断词转人工、AI 会话落库                                       |
| 11   | 并发呼入(可选)     | 独立脚本/场景11 入口    | 坐席状态更新、重复分配、排队/溢出行为、分级统计                          |
| 12   | 注册网关呼入(可选) | 4005678 / flow108       | REGISTER 绑定识别(网关46)、转坐席组、坐席接听、CDR                       |
| 13   | 注册网关呼出(可选) | 8#18600000000 / flow109 | 删除前缀 8#、注册 Contact 动态解析(网关46, address 空)、pjsua 接听、CDR  |

## 并发呼入压测（场景 11）

通过 pjsua 批量登录第三方网关（FS <A服务器公网>:9988）账户（18600000000~18600000099，共 100 个），发令枪并发呼叫
4001234（route101 → flow101 → 转坐席组1），分级验证：

1. **坐席状态更新正确性**：Redis `fs:agent:status` 轨迹 + DB `online_status` 一致性
2. **空闲坐席获取并发正确性**：同一坐席被重复分配（通话重复建立）检测
3. **排队逻辑**（`--queue-test`）：临时改坐席组1 为排队策略，测完自动还原
4. **溢出分支行为**：全忙走溢出（当前配置溢出目标 flow_id=1 不存在，会记为缺陷）

运行方式（独立脚本，推荐完整压测）：

```bash
# 默认分级 10,20,30,50,80,100(有头观察到无头优先)
python3 cc_concurrent_test.py
# 指定分级 + 无头
python3 cc_concurrent_test.py --headless --levels 10,20,50,100
# 排队子测试(坐席组1 临时改 full_busy_type=0, 测完还原)
python3 cc_concurrent_test.py --headless --levels 10 --queue-test
# 冒烟(单级 10 路)
python3 cc_concurrent_test.py --levels 10
```

主脚本轻量入口（场景 11，两级 10/20）：

```bash
python3 cc_e2e_test.py --scenarios 11 --rounds 1 --headless
```

报告产物：`reports/concurrent_report_*.md|json`（每级发起/注册/接通/坐席分配分布/状态轨迹摘要/重复分配 + 缺陷清单）。

**已发现缺陷与修复状态（2026-08-29 修复并部署回归验证）**：
- [P1] 排队分发失效（已修复）：根因有三——① `fsAcd()` 的 multiGet 用 `Collections.singleton(agentIds)` 抛 ClassCastException；② 空闲过滤用恒 null 的 `status` 字段；③ **调度线程无租户上下文，MyBatis 租户插件 NPE（`TenantContextHolder 不存在租户编号`）**，且队列条目挂断后残留、异步线程 `iterator.remove()` 与主线程遍历竞争。修复：multiGet 直接传 `List<Object>`、过滤改 `onlineStatus`、DB 查询包 `TenantUtils.executeIgnore`/`NoTenant` 方法、队列操作 `synchronized` 保护、挂断条目清理、remove 移出异步块。回归：扫描异常=0、释放坐席后排队分配成功
- [P2] 空闲坐席获取竞态（已修复）：选座后 Lua 原子 CAS 抢占（`occupyAgentAsRinging`，仅当 READY 时置 RINGING），并发选中同一坐席仅一个成功，失败方重新选座/走全忙分支。回归：10/20 级分配 1/1/1 无重复分配
- [P3] audioFork 放音瓶颈（部分改善）：fork/stream 线程池扩容（4→8/16→24）+ 启动命令失败重试 1 次。回归：20 级接通 20/20（修复前 0），20 级偶发失败仍存在
- [P4] 溢出目标配置无效（已修复）：前端"溢出IVR流程"下拉改用流程列表（`CcIvrApi.getPage`），value 绑定流程 ID（历史误绑路由正则）；DB 脏数据已修正为 104；后端 `Long.valueOf` 加非数字降级挂机保护。回归：下拉显示流程#101~#107
- [P5] 连续压测后系统不可恢复（已修复）：根因为 sipproxy 无会话 BYE 的 fallback 转发形成回弹循环——`SipByeRequestHandler` 在 SessionInfo 不存在时按 To 头注册状态转发 BYE（未注册用户按来源 IP 反查第三方网关），对端处理后 BYE 回弹代理，同一 callId 以 11 次/秒 无限弹跳，持续占用 `EventScannerThread` 导致新呼叫无人处理（业务层无日志即挂断）、系统不可用。修复：无会话 BYE 直接丢弃不转发（BYE 为终止性请求，会话不存在时转发无意义）。回归：30 级接通 30/30、压测后无僵尸 WARN、压测后单呼正常

## 退出码

- `0`：全部场景通过（L0 通过；check-only 模式下 L0 通过）
- `1`：存在场景失败（重试轮数用尽后仍失败）
- `2`：L0 环境/数据核对失败，或参数非法（未知场景编号）

## 验证流程（每轮）

1. **L0**：网络连通（后端/前端/ESL×2/MySQL/Redis/第三方 FS/sipproxy）+ 数据核对（6 路由/6 流程/坐席/组/网关）+ 软电话注册 +
   坐席登录签入
2. **场景**：按编号顺序执行，每场景多轮重试（`--rounds` 控制）
3. **L5**：通话记录生成数量、坐席在线状态
4. 汇总输出 PASS/FAIL 清单与退出码

## 已知边界

- 咨询转接 hold 音乐使用 `silence_stream://300000`（5 分钟静音）：该 FS 无 `local_stream://moh`
  媒体源，短时播放源（silence_stream://1、tone_stream）播放结束的 PLAYBACK_STOP 事件会被基线 IVR
  流程误判为"放音完成"导致流程提前终止；且 `uuid_bridge` 解除 hold 时播放器 STOP 上报的 FILE PLAYED 同样会误判推进流程（已由
  `FsChannelExecuteCompleteEslEventHandler` 过滤 hold 音乐播放完成/文件缺失事件，不参与流程流转）
- B-C 桥接（uuid_bridge）后客户端 BYE 会被 FS 回 481（B2BUA 透传模式下 dialog tag 不一致），场景 6 收尾改用 ESL 批量挂断
- 软电话心跳：sipproxy 空闲超时 90s，JsSIP 心跳 30s（`SoftPhone.vue` KEEP_ALIVE_INTERVAL）
