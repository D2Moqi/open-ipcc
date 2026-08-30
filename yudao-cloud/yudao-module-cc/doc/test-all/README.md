# yudao-cloud-cc 端到端测试套件

呼叫中心系统（yudao-module-cc）唯一端到端测试体系，覆盖内部呼叫、出局呼叫、入局 IVR、保持/恢复、咨询转接、自动外呼、客服组繁忙、满意度评价共
8 个业务场景。

## 目录结构

```
test-all/
├── cc_e2e_test.py       # 唯一主脚本(L0 环境核对 + 场景 1/2/3/5/6/7/8/9 + L5 数据校验)
├── requirements.txt     # Python 依赖
├── common/              # 公共层
│   ├── config.py        # 环境配置(凭据优先读环境变量 IPCC_* 前缀)
│   ├── browser_test.py  # Playwright 浏览器封装(登录/签入/拨号/接听/挂断/转接)
│   ├── data_spec.py     # 路由/流程/坐席/网关规格与 L0 数据核对
│   ├── db_helper.py     # MySQL 辅助
│   ├── esl_helper.py    # FreeSWITCH ESL 辅助(事件订阅/命令/通道统计)
│   ├── redis_helper.py  # Redis 辅助(自动外呼任务上下文)
│   └── sip_client.py    # pjsua 软电话客户端(模拟外部主叫/被叫)
├── probes/              # 诊断工具(ESL 事件监控/FS 通道检查/SDP 抓取等, 按需使用)
└── screenshots/         # 失败截图(自动生成)
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

- 线上后端 `https://cc.wenmoqi.top`（yudao-server 48080，sipproxy 内嵌）
- FreeSWITCH 双实例（fs1: SIP 15560/ESL 18021，fs2: SIP 16560/ESL 18121）+ 第三方 FS（SIP 9988/ESL 9966）
- MySQL / Redis / 浏览器（Playwright Chromium）

## 运行方式

```bash
# 全量场景(默认 1,2,3,5,6,7; 每场景最多 3 轮, 轮间退避 10s)
python3 cc_e2e_test.py

# 指定场景(场景 8/9 为可选项, 须显式指定)
python3 cc_e2e_test.py --scenarios 6
python3 cc_e2e_test.py --scenarios 6,8,9

# 只做 L0 环境/数据核对(不执行场景), 退出码 0=通过 2=失败
python3 cc_e2e_test.py --check-only

# CI 无头模式 + 单轮
python3 cc_e2e_test.py --headless --rounds 1

# 跳过 L0 核对 / L0 数据缺失时自动修复(白名单)
python3 cc_e2e_test.py --skip-l0
python3 cc_e2e_test.py --auto-fix
```

## 场景说明

| 编号 | 场景             | 入口/流程               | 验证要点                                                                 |
|------|------------------|-------------------------|--------------------------------------------------------------------------|
| 1    | 内部呼叫         | 9#1002 / flow102        | A→B 通话建立、双方通话中、CDR                                            |
| 2    | 出局呼叫         | 0#18600000000 / flow105 | 经网关出局、对端应答、CDR                                                |
| 3    | 入局 IVR 全链路  | pjsua 4001234 / flow101 | IVR 放音(含 TTS)、收号、IF 分支、转坐席组、坐席接听、挂断联动、CDR       |
| 5    | 保持/恢复        | 通话中保持              | 保持成功轮 ≥1（3 轮中），降级通过                                        |
| 6    | 咨询转接         | REFER attended → 1003   | A-B 基线、hold、originate C、C 接听、A-C 咨询、A 挂断确认、B-C 桥接、CDR |
| 7    | 自动外呼         | flow103                 | 任务上下文预置、页面建任务、外呼接通、记录状态                           |
| 8    | 客服组繁忙(可选) | 00300xxx / flow104      | 忙提示音、流程终态                                                       |
| 9    | 满意度评价(可选) | 00100xxx / flow106      | 收号节点、DTMF、方法节点、流程终态                                       |

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
