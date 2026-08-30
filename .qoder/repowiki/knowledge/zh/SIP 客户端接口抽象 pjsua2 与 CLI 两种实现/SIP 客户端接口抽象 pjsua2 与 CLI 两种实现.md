---
kind: design
name: SIP 客户端接口抽象 pjsua2 与 CLI 两种实现
source: session
category: adr
---

# SIP 客户端接口抽象 pjsua2 与 CLI 两种实现

_来源：cf8c29b → 81b13a1 提交周期内记录的编码计划——内容为规划时意图，实现可能滞后或有出入。_

**状态：** accepted

## 背景
macOS 环境下 pjsua2 未安装（Python 3.9.6 venv / 系统 Python 3.11），是端到端测试的最大风险；需要一种可在不同环境运行的软电话客户端来驱动 IVR 测试。

## 决策驱动
- 跨平台可运行
- 能力等价（注册/呼叫/DTMF/通话统计）
- 最小改动面

## 备选方案
- **pjsua2 原生绑定** — 优点：性能最好、API 最完整；缺点：macOS 上可能无法安装 wheel，编译成本高
- **pjsua CLI 子进程方案** — 优点：brew 即可安装，无需编译；缺点：进程间通信开销略大
- **复制全场景测试 helper 文件到新目录** _（已否决）_ — 优点：独立；缺点：产生双份维护成本

## 决策
定义统一 SipClient 接口（register/call/answer/hangup/send_dtmf/get_rx_bytes/is_registered），优先尝试 pjsua2 实现，不可用时降级为 pjsua CLI 实现；测试脚本通过 sys.path 复用 ../全场景测试 的 helper，不在 ivr流程测试 目录复制副本。

## 影响
E2E 脚本可在无 pjsua2 的环境下运行；DTMF 优先 RFC2833 dialDtmf，SIP INFO 兜底；媒体字节统计通过 call.getStreamStat() 获取。