# SIP通信系统信令与话务流程方案

> **版本**：v3.0  **生效日期**：2026-07-22
> **适用范围**：yudao-cloud-cc 呼叫中心（cc）模块
> **核心设计原则**： **所有 INVITE 必须经过号码路由表正则匹配 → IVR 流程 → IVR 转接节点驱动后续行为**；网关 ID 仅作为 IVR
> 转接节点（routeType=2 外呼）的覆盖项。

***

## 一、文档目的与版本说明

本方案定义 yudao-cloud-cc 呼叫中心 SIP 通信系统的：

- 系统组件角色定位与架构模式
- 核心设计原则（号码分析驱动路由 + 网关 ID 覆盖）
- 7 类核心业务场景的端到端信令与媒体流程
- 异常场景处理与可靠性保障
- 生产环境必需的 SIP 补充机制
- 号码路由表配置规范
- 已知遗留问题与未来演进方向

阅读对象：cc 模块开发、测试、运维、SRE 工程师，以及对接运营商/第三方网关的集成方工程师。

***

## 二、系统组件角色定位

四个核心组件在系统中的职责：

| 组件                     | 角色                       | 关键职责                                                                                                                                                                                                               |
|--------------------------|----------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **JSSIP客户端**          | UA（User Agent）           | 浏览器/Web 端坐席软电话，发起/接收呼叫，处理本地媒体（WebRTC）。**所有坐席均注册在 SIP 代理服务上**                                                                                                                    |
| **SIP代理服务**          | B2BUA（背靠背用户代理）    | **系统信令核心与控制大脑**。负责坐席注册管理、认证鉴权、请求路由、协议转换（WebSocket↔UDP/TCP）、网关选路、**通过 ESL 全权控制 FreeSWITCH 的呼叫逻辑**。是所有信令的必经节点                                           |
| **FreeSWITCH服务器**     | Media Server（"哑"媒体层） | **仅负责媒体处理，是纯粹的被动执行者**。媒体协商、录音、转码、DTMF 收号、会议混音。收到 INVITE 后立即 park 住，等待 ESL 指令。**不配置任何 dialplan 业务逻辑**；系统中存在多台实例；不负责坐席注册，不参与信令路由决策 |
| **第三方FreeSWITCH网关** | 出局/入局网关              | 对接运营商/PSTN/外部 SIP 网络，完成内部 SIP 与外部电话网络的互通。由网关 ID（FsSipGatewayDO）标识                                                                                                                      |

### 关键架构说明

```
                    ┌──────────────────────────────────────────────┐
                    │              SIP 代理服务（信令核心+控制大脑）   │
                    │  ┌──────────────────────────────────────────┐ │
  WebSocket(WSS)    │  │ • 坐席注册管理（所有 JSSIP 坐席注册于此）  │ │
 ┌────────────┐     │  │ • 认证鉴权（Digest/Token/IP 白名单）     │ │
 │ JSSIP客户端│◄───►│  │ • 请求路由（号码路由匹配+IVR 驱动）       │ │     ESL
 │ (浏览器坐席)│     │  │ • ESL 全权控制 FS（originate/bridge/IVR） │ │◄──────►┌────────────────┐
 └────────────┘     │  │ • 协议转换（WebSocket↔UDP/TCP）         │ │  SIP   │ FreeSWITCH #1  │
                    │  │ • SDP 协商协调（指定 FS 作为媒体中继）     │ │◄──────►│  (哑媒体服务)   │
                    │  └──────────────────────────────────────────┘ │  RTP   └────────────────┘
                    │                      │ SIP                    │
                    │                      ▼                        │     ESL
                    │              ┌────────────────┐               │◄──────►┌────────────────┐
                    │              │ 第三方 FS 网关   │               │  SIP   │ FreeSWITCH #2  │
                    │              │ (出局/入局)    │               │◄──────►│  (哑媒体服务)   │
                    │              └────────────────┘               │  RTP   └────────────────┘
                    └──────────────────────────────────────────────┘
```

> **架构模式说明**：本系统采用 **SIP 代理独立信令层 + ESL 全权控制** 架构。SIP 代理服务作为唯一的信令入口与路由核心，所有坐席均注册在
> SIP 代理服务上。FreeSWITCH 仅作为"哑"媒体服务器——收到 INVITE 后立即 park 住，由 SIP 代理服务通过 ESL 监听 `CHANNEL_PARK`
> 事件后接管控制，通过 ESL 命令（originate/uuid\_bridge 等）驱动 FS 完成第二段呼叫和媒体桥接。FS **不配置任何 dialplan
业务逻辑**。系统中部署多台 FreeSWITCH 实例，每台通过地址（IP:port）标识。

### B2BUA 角色定位说明

SIP 代理服务在协议层面扮演的是 **B2BUA（Back-to-Back User Agent，背靠背用户代理）**，而非简单的 SIP Proxy。两者的本质区别如下：

| 维度             | SIP Proxy（代理）                        | B2BUA（背靠背用户代理）✅ 本系统角色                          |
|------------------|------------------------------------------|---------------------------------------------------------------|
| **对话模型**     | 透明转发请求，维护单一 SIP 对话          | 终结一侧对话，重新发起另一侧对话，形成**两段独立的 SIP 对话** |
| **From/To tag**  | 不修改 tag 值                            | 两段对话使用不同的 Call-ID 和 tag                             |
| **状态维护**     | 事务级状态（或无状态）                   | 维护完整对话状态（Dialog State）                              |
| **Record-Route** | 需添加自身到 Record-Route 以留在信令路径 | 天然位于两段对话中间，无需 Record-Route                       |
| **适用场景**     | 简单路由代理                             | 需要深度控制信令、媒体锚定、业务逻辑                          |

本系统的 B2BUA 特征体现为：

```
坐席A ←──SIP对话1（Call-ID-1）──→ SIP代理(B2BUA) ←──SIP对话2（Call-ID-2）──→ 坐席B/网关
                                      │
                                   ESL控制
                                      │
                                 FreeSWITCH(媒体)
```

- **第一段对话**：坐席A ↔ SIP 代理（INVITE 终结于 FS 的 park，Call-ID-1）
- **第二段对话**：SIP 代理 ↔ 坐席B/网关（通过 ESL originate 发起新 INVITE，Call-ID-2）
- **两段对话独立**：不同的 Call-ID、From/To tag，BYE/Re-INVITE 等请求分别在各自对话内处理

> **影响**：B2BUA 定位意味着 BYE 挂断、Re-INVITE（如 hold/unhold、Session Timer 刷新）等请求在两段对话中是 **独立事务**，由
> SIP 代理在中间协调，而非简单透传。

***

## 三、核心设计原则：号码分析驱动路由 + 网关 ID 覆盖

SIP 代理服务的路由决策 **以号码分析为核心**：所有到达 SIP 代理的 INVITE 请求（ **包括内部坐席间呼叫**）必须经过号码路由表的正则匹配，匹配到对应
IVR 流程后由 IVR 流程驱动后续呼叫行为。网关 ID 作为 IVR 转接节点的网关覆盖项。

### 3.1 三大设计要点

1. **所有呼叫（含内部坐席间呼叫）必须走号码路由 + IVR，**，所有呼叫统一走号码路由→IVR→IVR 转接节点。
2. **网关 ID 仅作为 IVR 转接节点的覆盖项**——优先级：`CallInfo.gatewayId`（来自 INVITE 头 `X-Gateway-Id`）>
   `IVR 转接节点 routeValue`（来自 IVR 配置）> 当前连接的 FS 兜底。
3. **当前连接的 FS**——指 CHANNEL\_PARK 事件来源的 FS 实例（即当前正在处理该呼叫腿的 FS，代码层面即
   `FsCallIRouteProcess.handler` 的 `address` 参数）。

### 3.2 统一呼叫控制流程

```
INVITE 到达 SIP 代理服务
│
├── 提取 INVITE 头中的 X-Gateway-Id（如有）存入 SessionInfo/CallInfo
│
├── 转发 INVITE 到内部 FS（负载均衡选择） → FS park 住 → ESL 监听到 CHANNEL_PARK 事件
│
├── ESL 处理器读取被叫号码 + gatewayId（来自事件 variable_sip_h_X-Gateway-Id）
│
├── 号码路由表正则匹配（按 callType=1 呼入 / callType=2 呼出 区分）:
│   ├── 调用 CallRouteService.getListByRouteNumberAndType(callee, direction)
│   ├── 取 level 最高的路由条目
│   └── 用其 flowId 驱动对应 IVR 流程
│
├── IVR 流程执行到转接节点（transfer-node）:
│   ├── routeType=1（转坐席）→ ESL originate 发起第二段呼叫到目标坐席
│   └── routeType=2（外呼）→ 按以下优先级确定出局网关 ID:
│       ├── 优先级 1: CallInfo.gatewayId（INVITE 头携带）非空 → 使用它作为出局网关 ID
│       ├── 优先级 2: IVR 转接节点 routeValue 非空 → 使用它作为出局网关 ID
│       └── 优先级 3: 两者都为空 → 使用当前连接的 FS（CHANNEL_PARK 事件来源 FS）作为出局目标
│
└── IVR 转接节点通过 ESL originate 驱动 FS 发起第二段呼叫（回注到 SIP 代理）
    └── 第二段 INVITE 回注到 SIP 代理 → 代理执行出局改写 → 转发到第三方网关
```

### 3.3 网关 ID 覆盖优先级

| 优先级  | 网关 ID 来源                                            | 说明                                                                                               |
|---------|---------------------------------------------------------|----------------------------------------------------------------------------------------------------|
| 1（高） | `CallInfo.gatewayId`                                    | 来自 INVITE 头 `X-Gateway-Id`，业务侧显式指定，覆盖 IVR 配置                                       |
| 2（中） | `IVR 转接节点 routeValue`（routeType=2 时）             | 来自 IVR 流程配置，作为兜底网关 ID                                                                 |
| 3（低） | 当前连接的 FS（CHANNEL\_PARK 事件来源 FS 的 `address`） | 上述两者都为空时，使用当前正在处理该呼叫腿的 FS 实例，由其本地 sofia profile external 配置路由出局 |

### 3.4 关键约束与告警

> **所有呼叫必须走号码路由 + IVR**：所有呼叫（包括内部坐席间呼叫、携带网关 ID
> 的出局呼叫、入局呼叫、自动外呼）统一经过号码路由表正则匹配 → IVR 流程 → IVR 转接节点驱动后续呼叫行为。这保证了系统路由策略的统一性、可追溯性，所有呼叫都经过
> IVR 流程的统一业务逻辑（录音、计费、CDR 等）。

> **网关 ID 职责定位**：网关 ID 作为"IVR 转接节点的覆盖项"，仅在 routeType=2 外呼时生效。INVITE 中携带的 `X-Gateway-Id`
> 会被存入 `CallInfo.gatewayId`，在 IVR 流程执行到转接节点时作为优先级最高的网关 ID 使用。

> **当前连接的 FS 语义**：当 `CallInfo.gatewayId` 与 IVR 转接节点 `routeValue` 均为空时，使用当前正在处理该呼叫腿的 FS
> 实例作为出局目标。具体指 **CHANNEL\_PARK 事件来源的 FS 实例**，代码层面即 `FsCallIRouteProcess.handler` 方法的 `address`
> 参数。通过该 FS 的本地 sofia profile external 配置发起出局呼叫（不指定具体 gateway，由 FS 自身路由）。

> **⚠️ 网关 ID 不能设置为内部 FS 地址**：该约束必须严格遵守。如果 `CallInfo.gatewayId` 或 IVR 转接节点 `routeValue`
> 恰好等于某台内部 FreeSWITCH 的服务地址（如 fs1=10.0.0.10:5060），会导致 **INVITE 回环死循环**：
>
> 1. IVR 转接节点通过 ESL originate 驱动 FS 发第二段 INVITE，携带 `X-Gateway-Id: fs1`
> 2. SIP 代理收到后查网关 ID 表 → 目标=10.0.0.10:5060（FS 自己）
> 3. SIP 代理把 INVITE 转发回 FS → FS 又收到 INVITE → 又 park 住 → 又触发 CHANNEL\_PARK 事件
> 4. SIP 代理又收到 park 事件 → 又走号码路由 → IVR → ESL originate → 无限循环
>
> 因此， **配置网关 ID 时必须确保其指向的是第三方出局网关（FsSipGatewayDO）而非内部 FS 实例**。系统应在网关配置与 IVR
> 转接节点配置时进行校验，拒绝将内部 FS 地址配置为网关 ID。

> **号码路由表配置要求**：由于所有呼叫必须经过号码路由匹配，号码路由表必须配置至少一条规则。推荐配置默认兜底规则 `.*` 指向默认
> IVR 流程，避免未匹配到规则的呼叫被挂断。详细配置规范见附录"号码路由表配置规范"。

### 3.5 三个豁免场景（保留 ESL originate 直接出局能力）

为避免 INVITE 回环与降低特殊场景的转接延迟，以下三种场景的 c-leg 保留"通过 gatewayId 直接出局"能力， **不走号码路由 +
IVR**：

| 场景   | 触发条件                                                | 走通路径                                                                                   |
|--------|---------------------------------------------------------|--------------------------------------------------------------------------------------------|
| 场景四 | 三方会议邀请外部手机（ESL originate 携 `X-Gateway-Id`） | SIP 代理收到 FS 源 INVITE + 携带 gw3 → `forwardToOutboundGateway` 直接出局改写             |
| 场景五 | 双向出局转接（ESL originate 携 `X-Gateway-Id`）         | 同上                                                                                       |
| 场景六 | 转接携带 `X-Gateway-Id`（折中方案）                     | 转接 携带 gw3 时，FS 通过 ESL originate 直出局（不回注 SIP 代理）                          |
| 场景七 | 自动外呼（ESL originate 直发）                          | ESL originate 直发（`sofia/external/{target}@{gateway.realm}`），不走 sipproxy INVITE 转发 |

实现关键点：`SipInviteRequestHandler.handleIncomingRequest` 中识别"`FREESWITCH` 源 + 携带 `X-Gateway-Id`"的组合，调用
`SipMessageForwarder.forwardToOutboundGateway` 走出局改写，跳过 FS park + 号码路由 + IVR 流程。详见各场景章节及"八、生产环境必需的
SIP 补充机制"中的代码说明。

***

## 四、高可用性（HA）设计

SIP 代理服务作为系统信令核心与控制大脑，是典型的 **单点故障（SPOF）**。为保证系统可用性，需从以下三个层面设计高可用方案：

### 4.1 SIP 代理服务自身 HA

| 方案                           | 说明                                                           | 适用场景             |
|--------------------------------|----------------------------------------------------------------|----------------------|
| **Active-Standby（主备）**     | 一主一备，备用节点通过心跳监控主节点，故障时 VIP 漂移接管      | 中小规模、呼叫量可控 |
| **Active-Active（双活/集群）** | 多个代理节点同时服务，前端通过负载均衡（DNS SRV / SIP LB）分发 | 大规模、高并发场景   |

**会话状态同步要求**：

```
SIP 代理集群状态同步:
├── 注册表同步：坐席注册信息需在所有代理节点间共享（Redis / 数据库 / 组播同步）
├── 对话状态同步：B2BUA 维护的两段对话映射关系需持久化（用于故障迁移后恢复控制）
├── ESL 连接状态：每个代理节点维护与各 FS 实例的 ESL 连接池
├── 号码路由表：全局共享，所有节点可见（路由决策核心）
└── 网关配置表（FsSipGatewayDO）：全局共享，所有节点可见（IVR 转接节点出局用）
```

### 4.2 FreeSWITCH 无状态化与故障切换

FreeSWITCH 本身设计为无状态媒体处理节点，天然支持水平扩展与故障切换：

```
FS 故障切换流程:
├── SIP 代理通过 ESL 心跳检测 FS 健康状态
├── FS 实例故障 → 代理将该实例从负载均衡池中摘除
├── 新呼叫不再分配到故障 FS
├── 故障 FS 上的在用呼叫:
│   ├── 媒体路径中断 → 终端检测到 RTP 超时 → 发起 Re-INVITE 或重连
│   └── SIP 代理检测到 ESL 断线 → 通过其他 FS 重新 originate 恢复（需业务层支持）
└── 故障 FS 恢复 → 重新加入负载均衡池
```

### 4.3 ESL 连接断线后的通话保持

ESL 连接断线（FS 容器重启、ESL 服务进程崩溃、网络闪断）时，已建立的通话不应中断：

```
ESL 断线处理策略:
├── FS 容器重启 → 已建立的 RTP/SDP 媒体会话保留 → FS 重启后自动恢复
├── 通话桥接保留: uuid_bridge 不依赖 ESL，断线时已 bridge 的通话继续
├── ESL 重连: FsClient.funtureConnect 自动重连，重连后恢复 ESL 控制（originate/bridge/IVR）
├── 重连期间产生的 CHANNEL_PARK/CHANNEL_HANGUP 等事件丢失 → 业务层需容忍（号码路由匹配失败兜底为挂断）
└── 关键状态持久化: CallInfo 通过 Redis SCAN 缓存，重连后可恢复关联
```

***

## 五、场景一：JSSIP 坐席A → JSSIP 坐席B（内部呼叫）

### 5.1 整体流程时序

> **关键说明**：FreeSWITCH 是"哑"媒体服务器， **不配置任何 dialplan 业务逻辑**。FS 收到 INVITE 后立即 park 住呼叫腿，由 SIP
> 代理服务通过 ESL 监听 `CHANNEL_PARK` 事件后接管控制。 **所有呼叫（含内部坐席间呼叫）强制走号码路由 → IVR → 转接节点**：SIP
> 代理读取 park 事件中的被叫号码 → 调用 `CallRouteService.getListByRouteNumberAndType` 按正则匹配号码路由表（type=2 呼出）→
> 用匹配到的 `flowId` 驱动对应 IVR 流程 → IVR 流程执行到转接节点（routeType=1 转坐席，routeValue=坐席B的 ID）→ 通过 ESL
> `originate` 命令驱动 FS 发起第二段呼叫（回注到 SIP 代理），代理查询坐席B 注册位置后转发给坐席B。最终通过 ESL `bridgeCall`
> 命令驱动 FS 完成两腿桥接。
>
> **号码路由表必须配置**：坐席分机号的正则规则（如 `^1\d{3}$`），指向包含转坐席节点的 IVR 流程，否则呼叫将被挂断。

```
坐席A(JSSIP)       SIP代理服务      FreeSWITCH        坐席B(JSSIP)
    │                  │      ┃ESL     │                  │
    │                  │      ┃        │                  │
    │                  │ 【第一段呼叫腿：坐席A → 代理 → FS】  │
    │①INVITE ─────────►│      ┃        │                  │
    │ (无网关ID)       │      ┃        │                  │
    │                  │②鉴权 ┃        │                  │
    │◄── 100 Trying ───│      ┃        │                  │
    │                  │③选FS ┃        │                  │
    │                  │④INVITE(A的SDP)►│                  │
    │                  │      ┃        │⑤FS锚定媒体       │
    │                  │      ┃        │  分配RTP端口      │
    │                  │      ┃        │  183 Progress    │
    │                  │◄── 183(FS SDP)│                  │
    │◄── 183(FS SDP)───│      ┃        │                  │
    │                  │      ┃        │⑥FS park住呼叫腿  │
    │                  │      ┃◄───────│ CHANNEL_PARK     │
    │                  │      ┃事件    │ 事件             │
    │                  │      ┃        │                  │
    │                  │ 【SIP代理ESL接管：号码路由匹配→IVR→转接节点(routeType=1)】
    │                  │⑦读取park事件  │                  │
    │                  │  号码路由匹配 │                  │
    │                  │  (type=2呼出)│                  │
    │                  │  →IVR流程    │                  │
    │                  │  →转接节点   │                  │
    │                  │  (转坐席B)   │                  │
    │                  │⑧ESL originate ┃►                 │
    │                  │  命令驱动FS    │                  │
    │                  │  发起第二段呼叫┃                  │
    │                  │      ┃        │                  │
    │                  │ 【第二段呼叫腿：FS → 代理 → 坐席B】│
    │                  │◄── INVITE(FS的SDP)                │ ⑨
    │                  │⑩查询B注册位置   │                  │
    │                  │── INVITE(FS的SDP)───────────────►│ ⑩
    │                  │      ┃        │              振铃 │
    │                  │◄── 180 Ringing───────────────────│
    │                  │── 180 ────────►│                  │ ⑪
    │                  │      ┃        │⑫FS收到第二段180  │
    │                  │      ┃◄───────│ CHANNEL_PROGRESS │
    │                  │      ┃        │ 事件             │
    │                  │◄── 180 ────────│                  │
    │◄── 180 ──────────│      ┃        │                  │
    │                  │      ┃        │          B接听   │
    │                  │◄── 200 OK(B的SDP)────────────────│
    │                  │── 200 OK ─────►│                  │ ⑬
    │                  │      ┃        │⑭FS两腿就绪       │
    │                  │⑮ESL bridgeCall┃►                 │
    │                  │  命令桥接a/b腿 ┃                  │
    │                  │      ┃        │⑯FS完成媒体桥接   │
    │                  │      ┃        │  锚定:A腿↔FS↔B腿 │
    │                  │◄── 200 OK(FS)──│                  │
    │◄── 200 OK(FS SDP)│      ┃        │                  │
    │  A发送ACK         │      ┃        │                  │
    │── ACK ──────────►│      ┃        │                  │
    │                  │── ACK ───────►│                  │
    │                  │      ┃        │                  │
    │  通话建立(媒体:RTP经FS中继)                  │
    │◄═══════════════════════════════════════════════►│
    │                  │      ┃        │                  │
```

### 5.2 SIP 代理服务的具体处理流程

1. **WsInviteRequestHandler.doHandle**：
    - 提取 From/To 头，发送 100 Trying，调用 `nodeManager.selectFreeSwitchNode` 选择 FS 节点。
    - 设置 `callType=OUTBOUND`（统一标记，不区分内部/外呼）。
    - 提取 `X-Gateway-Id`（如有）→ `SessionInfo.gatewayId`。本场景无网关 ID。
    - 缓存 SessionInfo，`messageForwarder.forwardToFreeSwitch` 转发到 FS。
2. **FS 收到 INVITE → 媒体锚定 → 183 Progress → park**。
3. **ESL** **`CHANNEL_PARK`** **事件 → FsChannelParkEslEventHandler.outboundCall**：
    - 读取 `variable_sip_h_X-Gateway-Id`（本场景为空）→ `CallInfo.gatewayId=null`。
    - 构造 `CallInfo(callType=IVR, direction=2, gatewayId=null)`。
    - `process=CALL_ROUTE` 提交到 `FsCallIRouteProcess`。
4. **FsCallIRouteProcess.handler**：
    - `getCallRouteNoTenant(callee=坐席B分机号, direction=2)` 正则匹配号码路由表。
    - 匹配到坐席分机号规则（如 `^1\d{3}$`）→ 取 `flowId` 驱动 IVR 流程。
5. **IVR 流程执行到转接节点（routeType=1 转坐席）**：
    - `FlowTransferHandler` 触发，调用 `fsClient.originate` 发起第二段呼叫，目标=坐席B 注册地址。
6. **FS 发第二段 INVITE → SIP 代理（SipInviteRequestHandler）**：
    - `source=FREESWITCH`、`gatewayId=null` → `callType=INTERNAL`。
    - `forwardToFreeSwitch` 转发到 FS park。
7. **SipDefaultRequestHandler / WsReferRequestHandler 不参与**：第二段 INVITE 后转为对坐席B 的 WebSocket 推送（
   `forwardToWebSocketByUser`）→ JsSIP 振铃 → 接听 → 200 OK。
8. **ESL** **`bridgeCall`** **桥接 a-leg（坐席A FS 通道）与 b-leg（坐席B FS 通道）** → FS 完成媒体锚定 → 通话建立。

> **注意**：内部坐席间呼叫通常不携带 `X-Gateway-Id`。`X-Gateway-Id` 仅在 IVR 流程执行到转接节点（routeType=2 外呼）时作为网关
> ID 覆盖项使用。

### 5.3 被叫为非坐席号码时的 IVR 处理流程

无论被叫是否是已注册坐席，所有呼叫都必须走号码路由匹配 → IVR 流程。当坐席A 发起 INVITE 到非坐席号码（如外部手机号、IVR
接入号等）时，SIP 代理服务通过号码路由表匹配到对应 IVR 流程后执行：

1. **号码路由匹配**：根据 `callee` 正则匹配 → 取 `flowId`。
2. **IVR 流程驱动**：执行 IVR 流程中的节点（播放欢迎语、收 DTMF、转接等）。
3. **转接节点（transfer-node）执行**：
    - `routeType=1`（转坐席）→ ESL originate 发起第二段呼叫到目标坐席。
    - `routeType=2`（外呼）→ 按"网关 ID 覆盖优先级"确定出局网关（详见 3.3 节）。
4. **后续流程**与场景一/场景二/场景六相同。

### 5.4 BYE 挂断流程

BYE 挂断需在两段对话中分别处理：

1. **坐席A 发起 BYE**（Call-ID-1）→ `WsDefaultRequestHandler` 透传到 FS → FS 触发 `CHANNEL_HANGUP` 事件。
2. **SIP 代理监听到 hangup 事件** → `FsChannelHangUpEslEventHandler`：
    - 从 `CallInfo.channelMap` 取 a-leg/b-leg UUID。
    - 调用 `fsClient.uuidKill(address, legUuid)` 释放另一侧（避免漏挂断）。
    - 清理 `CallInfo` 与 Redis 缓存。
3. **SIP 代理向坐席B 转发 BYE**（Call-ID-2）→ 坐席B 端 JsSIP 收到 BYE → 回 200 OK。

> **已实现**：`FsChannelHangUpEslEventHandler` 已实现 c-leg 清理逻辑——读取 `Other-Leg-Unique-ID` 后调用
> `fsClient.hangupCall` 释放关联腿，并更新 `CallInfo.channelMap`（`removeChannelInfoMap`）和 `uniqueIdList`（
> `removeUniqueIdList`），保证缓存与 FS 通道状态一致。`hangupCall` 失败不中断流程，后续由 `CHANNEL_HANGUP_COMPLETE` 事件兜底清理。

***

## 六、场景二：JSSIP 坐席A → 外部用户手机（出局呼叫）

### 6.1 整体流程时序

```
坐席A(JSSIP)        SIP代理服务       FreeSWITCH       第三方网关/运营商      手机
    │                  │      ┃ESL     │                  │              │
    │①INVITE ─────────►│      ┃        │                  │              │
    │ (X-Gateway-Id=gw3)    ┃        │                  │              │
    │◄── 100 Trying ───│      ┃        │                  │              │
    │                  │②③④⑤⑥ (同场景一)              │              │
    │                  │      ┃        │⑥FS park住呼叫腿  │              │
    │                  │      ┃◄───────│ CHANNEL_PARK     │              │
    │                  │      ┃        │ 事件             │              │
    │                  │      ┃        │                  │              │
    │                  │ 【号码路由匹配→IVR→转接节点(routeType=2)】
    │                  │⑦号码路由匹配 │                  │              │
    │                  │  (type=2呼出)│                  │              │
    │                  │  →IVR流程    │                  │              │
    │                  │  →转接节点   │                  │              │
    │                  │  (routeType=2)                  │              │
    │                  │⑧解析网关ID优先级:              │              │
    │                  │  CallInfo.gatewayId=gw3 ✓      │              │
    │                  │  →使用gw3作为出局网关            │              │
    │                  │⑨ESL originate ┃►                │              │
    │                  │  (sip_h_X-Gateway-Id=gw3)       │              │
    │                  │  sofia/gateway/gw3/13800138000@GW              │
    │                  │      ┃        │                  │              │
    │                  │ 【第二段呼叫腿：FS → 代理 → 第三方网关】
    │                  │      ┃        │⑩FS发INVITE给代理  │              │
    │                  │◄── INVITE(gw3)│                  │              │
    │                  │  (X-Gateway-Id=gw3)              │              │
    │                  │  (FREESWITCH源+携带gw3)          │              │
    │                  │      ┃        │                  │              │
    │                  │ 【SIP代理识别豁免场景：直接出局改写】
    │                  │⑪forwardToOutboundGateway(gw3)  │              │
    │                  │  →rewriteForOutbound           │              │
    │                  │  →forwardToThirdParty          │              │
    │                  │────────────────────────────────►│ ⑫INVITE       │
    │                  │  (From改DID, PAI注入)            │              │
    │                  │                  ◄── 183 ────────│              │
    │                  │◄── 183 ────────│                  │              │
    │◄── 183 ──────────│      ┃        │                  │              │
    │                  │                  ◄── 180 Ringing ─│              │
    │                  │◄── 180 ────────│                  │              │
    │◄── 180 ──────────│      ┃        │                  │              │
    │                  │                  ◄── 200 OK ─────│              │
    │                  │◄── 200 OK ─────│                  │              │
    │                  │      ┃        │                  │              │
    │                  │ 【ESL bridgeCall + 坐席A 200 OK】
    │                  │⑬ESL bridgeCall ┃►                │              │
    │                  │  →FS桥接a-leg和b-leg            │              │
    │                  │⑭ ── 200 OK ────────────────────►│ ⑭            │
    │◄── 200 OK(FS SDP)│      ┃        │                  │              │
    │  A发送ACK         │      ┃        │                  │              │
    │── ACK ──────────►│── ACK ──────────────────────────►│              │
    │                  │      ┃        │                  │              │
    │  通话建立(RTP:A↔FS(转码)↔网关↔手机)             │
    │◄═══════════════════════════════════════════════════════════════►│
```

### 6.2 SIP 代理服务处理流程详解

#### 6.2.1 第一段 INVITE 处理（同场景一）

1. `WsInviteRequestHandler.doHandle`：提取 `X-Gateway-Id=gw3` → `SessionInfo.gatewayId=gw3`。
2. 转发 INVITE 到 FS park。
3. ESL `CHANNEL_PARK` 事件 → `FsChannelParkEslEventHandler.outboundCall`（JsSIP UA 命中）。
4. 构造 `CallInfo(callType=IVR, gatewayId=gw3)`，`process=CALL_ROUTE`。
5. `FsCallIRouteProcess.handler`：号码路由匹配 → 匹配到手机号规则 → IVR 流程。
6. **IVR 转接节点（routeType=2 外呼）**：
    - `FlowCallOutRouteHandler.resolveOutboundGateway`（3 级优先级）：
        - 优先级 1：`CallInfo.gatewayId=gw3` 非空 → 使用 gw3。
    - 通过 gw3 查询 `FsSipGatewayDO` 配置（IP/端口/认证）。
    - 调用 `fsClient.makeCall(..., sipGateway=gw3)` 发起 ESL originate：
      `{sip_h_X-Gateway-Id=gw3}sofia/gateway/gw3/13800138000@代理地址`。

#### 6.2.2 第二段 INVITE 路由决策（关键：豁免场景识别）

FS 发第二段 INVITE 给代理，携带 `X-Gateway-Id=gw3`、`source=FREESWITCH`：

- `SipInviteRequestHandler.handleIncomingRequest` 检测到 `source=FREESWITCH && gatewayId 非空` → **走豁免分支**：
    - **不转发到 FS park**，直接调用 `messageForwarder.forwardToOutboundGateway(request, gw3)`。
    - 改写 From 头（DID）、注入 PAI、移除 Record-Route。
    - 转发到第三方网关（`FsSipGatewayDO` 中配置的 IP:port）。
- **如果未携带** **`X-Gateway-Id`**（依赖 IVR routeValue 兜底）：走 `forwardToFreeSwitch` 重新 park + 号码路由 +
  IVR（本场景不适用，因坐席A INVITE 已携带 gw3）。

#### 6.2.3 出局响应处理

1. 第三方网关 183/180/200 响应 → SIP 代理 `UnifiedResponseHandler`：
    - `source=THIRD_PARTY`、`callType=OUTBOUND` → 策略表命中"THIRD\_PARTY × OUTBOUND → FREESWITCH" → 转发到 FS。
2. 200 OK → FS → `bridgeCall` 桥接 a-leg/b-leg → FS 完成媒体锚定。
3. SIP 代理向坐席A 转发 200 OK → 坐席A 发送 ACK。

### 6.3 错误处理场景

| 错误场景                                    | 检测点                              | 处理策略                                                                               |
|---------------------------------------------|-------------------------------------|----------------------------------------------------------------------------------------|
| 号码路由表未匹配到手机号正则                | `FsCallIRouteProcess` 匹配失败      | `playFile(SYSTEM_ERROR)` + `hangupCall` + 告警日志 "号码 \[callee] 未匹配到路由规则"   |
| 匹配到路由但 flowId 为空                    | `CallRouteDO.flowId == null`        | 同上 + 告警 "号码路由 \[routeId] 的 flowId 为空"                                       |
| `FsSipGatewayDO` 不存在（gw3 无效）         | `FlowCallOutRouteHandler` 查询失败  | 回退到 `routeValue`；routeValue 也为空 → 当前 FS 兜底；告警 "网关 ID 无效"             |
| 第三方网关不可达                            | INVITE 超时 / 503 响应              | `playFile(SYSTEM_ERROR)` + `hangupCall`；ESL `uuidKill` 释放 a-leg；CDR 记录"出局失败" |
| 坐席挂断外呼中（早释）                      | `CHANNEL_HANGUP` 事件触发           | `uuidKill` 释放外呼 b-leg；CDR 记录"主叫早释"                                          |
| 第二段 INVITE 网关 ID 仍指向内部 FS（违规） | `forwardToOutboundGateway` 前置校验 | 阻断并返回 500 Server Error，告警 "网关 ID 指向内部 FS，疑似回环"                      |
| 第三方网关返回 407 Proxy Auth               | `SipInviteRequestHandler` 响应路径  | 重新注入 Authorization 头并重发 INVITE（去除旧 To tag，参照 RFC 3261 流程）            |

***

## 七、场景三：外部用户手机 → JSSIP 坐席A（入局呼叫）

### 7.1 整体流程时序

```
手机→运营商→第三方网关      SIP代理服务       FreeSWITCH        坐席A(JSSIP)
    │              │              │      ┃ESL     │              │
    │              │①INVITE ──────►│      ┃        │              │
    │              │ (无网关ID)     │      ┃        │              │
    │              │              │      ┃        │              │
    │              │②识别 source=THIRD_PARTY  ┃        │              │
    │              │  callType=INBOUND       ┃        │              │
    │              │  thirdPartyNode=网关地址  ┃        │              │
    │              │              │③选FS ┃        │              │
    │              │              │④INVITE(FS的SDP)►              │
    │              │              │      ┃        │⑤FS park      │
    │              │              │      ┃        │  CHANNEL_PARK│
    │              │              │      ┃        │              │
    │              │              │ 【号码路由匹配→IVR→ACD选坐席】
    │              │              │⑥号码路由匹配(type=1呼入)        │
    │              │              │  →IVR流程(入局)              │
    │              │              │  →ACD策略选坐席A             │
    │              │              │  (routeType=1转坐席)         │
    │              │              │⑦ESL originate ┃►             │
    │              │              │  到坐席A(回注到代理)          │
    │              │              │      ┃        │              │
    │              │              │ 【第二段呼叫腿：FS → 代理 → 坐席A】
    │              │              │      ┃        │              │
    │              │              │◄── INVITE(FS的SDP)            │
    │              │              │ (source=FREESWITCH)          │
    │              │              │ (无X-Gateway-Id)              │
    │              │              │  callType=INTERNAL           │
    │              │              │  →forwardToFreeSwitch        │
    │              │              │── INVITE ──────────────────►│ ⑧
    │              │              │      ┃        │              │
    │              │              │◄── 180 Ringing─────────────  │
    │              │              │── 180 ──────►│              │
    │              │              │      ┃        │              │
    │              │              │◄── 200 OK────  │ ⑨A接听     │
    │              │              │── 200 OK ────►│              │
    │              │              │      ┃        │              │
    │              │              │ 【ESL bridgeCall + 向第三方网关转发200 OK】
    │              │              │⑩ESL bridgeCall ┃►            │
    │              │              │      ┃        │              │
    │              │              │── 200 OK ──────────────────►│ ⑪
    │              │              │      ┃        │              │
    │              │              │      ┃        │              │
    │              │              │      ┃        │              │
    │  通话建立(媒体:手机↔网关↔FS(转码)↔坐席A)
    │◄═══════════════════════════════════════════════════►│
```

### 7.2 SIP 代理服务处理流程详解

1. **SipInviteRequestHandler.handleIncomingRequest**：
    - `source=THIRD_PARTY`（通过 `SipMessageForwarder.identifyMessageSource` 识别）→ `callType=INBOUND`。
    - 缓存 `thirdPartyNode`（用于响应转发方向）。
    - `forwardToFreeSwitch` 转发到 FS park。
2. **ESL** **`CHANNEL_PARK`** **事件 → FsChannelParkEslEventHandler.inboundCall**（非 JsSIP UA）：
    - 构造 `CallInfo(callType=IVR, direction=1)`。
    - 走 `handleIvrRoute` → `FsCallIRouteProcess`。
3. **FsCallIRouteProcess**：
    - `getCallRouteNoTenant(callee=DID号码, direction=1)` 匹配入局号码路由表。
    - 匹配到 DID 规则 → IVR 流程（播放欢迎语、收 DTMF、转人工坐席）。
4. **IVR ACD 选坐席** → `routeType=1 转坐席` → ESL originate 到坐席A。
5. **第二段 INVITE 同场景一**（`source=FREESWITCH, gatewayId=null, callType=INTERNAL`）→ `forwardToFreeSwitch` → FS park →
   `forwardToWebSocketByUser` 推到 JsSIP。
6. **坐席A 接听 → 200 OK** → ESL `bridgeCall` + SIP 代理向第三方网关转发 200 OK（策略表：`THIRD_PARTY × INBOUND` → 200 OK
   回到网关）。

### 7.3 呼叫转移/盲转场景

入局呼叫到达坐席A 后，坐席A 可通过 IVR 转接节点（routeType=1）转接到其他坐席，或通过 routeType=2 转接到外部手机：

- **转坐席（routeType=1）**：ESL originate 到目标坐席，重复场景一/二流程。
- **转外部手机（routeType=2）**：ESL originate 携 `X-Gateway-Id` → 走场景二第二段流程。
- **转接**：见场景六。

> **入局必须匹配呼入路由表**：入局呼叫的被叫号码为运营商分配的 DID 号码，需在号码路由表中配置 DID 号码的正则规则（type=1
> 呼入），指向对应的 IVR 流程。若未配置呼入路由规则，呼叫将被挂断。

***

## 八、场景四：坐席A + 坐席B + 外部手机（三方会议）

### 8.1 整体流程时序

```
坐席A        坐席B        SIP代理         FreeSWITCH      第三方网关       手机
  │             │          │      ┃ESL       │              │              │
  │             │          │      ┃          │              │              │
  │  ①坐席A与坐席B已建立通话(参见场景一)                            │
  │═════════════╪═══════════╡      ┃          │              │              │
  │             │          │      ┃          │              │              │
  │  ②坐席A发起"邀请外部手机加入会议"操作(坐席API)                   │
  │── API ─────►│          │      ┃          │              │              │
  │             │          │      ┃          │              │              │
  │             │          │ 【SIP代理ESL驱动:创建会议+迁移腿+originate c-leg】
  │             │          │ ③ESL conference 3000 创建         │
  │             │          │  ④uuid_转移: A、B 腿从 bridge 状态迁移到 conf 3000
  │             │          │  ⑤ESL originate ┃► (sip_h_X-Gateway-Id=gw3) │
  │             │          │   sofia/gateway/gw3/13800138000@代理              │
  │             │          │      ┃          │              │              │
  │             │          │ 【第二段INVITE: FS→代理→第三方网关(豁免场景)】
  │             │          │      ┃          │              │              │
  │             │          │      ┃◄─────────│ INVITE(gw3)  │              │
  │             │          │      ┃          │              │              │
  │             │          │ 【SIP代理识别FREESWITCH+gw3 → 豁免分支】
  │             │          │ ⑥forwardToOutboundGateway(gw3)  │              │
  │             │          │  →rewriteForOutbound            │              │
  │             │          │ ────────────────────────────────► ⑦INVITE      │
  │             │          │                ◄── 183 ──────────│              │
  │             │          │                ◄── 180 ──────────│              │
  │             │          │                ◄── 200 OK ──────│ ⑧手机接听    │
  │             │          │      ┃          │  c-leg 已加入 conf 3000         │
  │             │          │      ┃          │              │              │
  │  通话建立(三方会议: A↔FS会议桥↔B, 手机↔FS会议桥↔c-leg)
  │═══════════════════════════════════════════════════════════════►│
```

### 8.2 SIP 代理服务处理流程详解

#### 8.2.1 三方会议由业务 API 触发（不在 SIP 代理信令路径内）

1. 坐席A 通过业务 API 发起"邀请外部手机加入会议"请求（携带目标手机号 + 选中的网关 ID）。
2. SIP 代理（业务层）调用 ESL：
    - `conference 3000 create`：创建会议。
    - `uuid_transfer A_leg, B_leg to conference:3000`：将 A、B 两条腿从 bridge 状态迁移到会议。
    - `originate {sip_h_X-Gateway-Id=gw3}sofia/gateway/gw3/13800138000@代理`：发起 c-leg。

#### 8.2.2 c-leg INVITE 走豁免场景（关键）

FS 发出的 c-leg INVITE 携带 `X-Gateway-Id=gw3`、`source=FREESWITCH`：

- `SipInviteRequestHandler.handleIncomingRequest` 检测到 `source=FREESWITCH && gatewayId 非空` → **走豁免分支**：
    - 直接 `forwardToOutboundGateway(request, gw3)`， **跳过 FS park + 号码路由 + IVR**。
    - **不构造 CallInfo、不触发 CHANNEL\_PARK 事件**。
- 改写出局头域（From 改 DID、注入 PAI）后转发到第三方网关。
- 200 OK 响应 → 策略表 `FREESWITCH × OUTBOUND → WS/THIRD_PARTY` → 转回网关（`forwardToThirdParty`）。
- c-leg 接通后，FS 自动将其加入 `conference:3000`， **无需 SIP 代理参与 IVR 流程**。

#### 8.2.3 未携带 Gateway-Id 时的处理（不能走号码路由 + IVR）

当坐席A 发起"邀请外部手机加入会议"操作但 **未指定网关 ID** 时， **不能让 c-leg 走号码路由 + IVR 流程**，原因如下：

1. **IVR 流程会创建新腿，而非 c-leg 直接出局**：`FsCallIRouteProcess.handler` 匹配号码路由后调用 `FsIvrRouteHandler` →
   `flowNoticeService.notice` 驱动 IVR 流程。IVR 转接节点（routeType=2 外呼）通过 ESL `originate` **创建一条全新的腿**
   出局，而非将当前 c-leg 直接出局。这会导致 c-leg 被 park 住等待 IVR 指令，同时新建的 d-leg 与外部手机通话后桥接到 c-leg，但
   c-leg 仍不在 `conference:3000` 中。
2. **IVR 业务逻辑不适合三方会议 c-leg**：IVR 流程通常包含播放欢迎语、收 DTMF 等节点，这些业务逻辑会打断三方会议的实时性。即使配置一个仅含
   routeType=2 外呼节点的 IVR 流程（无语音播放），仍然存在"创建新腿"的问题。
3. **会议加入时序被破坏**：三方会议要求 c-leg 接通后 **立即加入会议**。如果走 IVR，时序变为：park c-leg → IVR 流程加载 → ESL
   originate 新腿 → 新腿接通 → bridge (c-leg, 新腿) → 但 c-leg 仍未加入会议。FS 会议需要 c-leg 本身作为会议成员，而非通过
   bridge 间接关联。

**正确做法**：未携带 Gateway-Id 时，业务层在发起 originate **之前**自行查询号码路由表确定出局网关 ID，然后用确定的网关 ID
构造携带 `X-Gateway-Id` 的 originate 命令，c-leg 仍走豁免场景（直接出局 + 加入会议）：

```
业务层未携带 Gateway-Id 时的处理流程:
├── 1. 业务层调用 CallRouteService.getListByRouteNumberAndType(手机号, 2) 匹配号码路由表
├── 2. 取匹配到的 flowId → 查询 IVR 流程中 routeType=2 转接节点的 routeValue（兜底网关 ID）
├── 3. 确定出局网关 ID:
│   ├── routeValue 非空 → 使用 routeValue 作为网关 ID
│   └── routeValue 为空 → 使用当前连接的 FS 兜底（通过 FS 本地 sofia profile external 出局）
├── 4. 用确定的网关 ID 构造 originate 命令:
│   └── originate {sip_h_X-Gateway-Id=gwX}sofia/gateway/gwX/手机号@代理 &park()
└── 5. c-leg 仍走豁免场景 → forwardToOutboundGateway → 直接出局 → 接通后加入 conference:3000
```

> **设计约束**：三方会议 c-leg **必须走豁免场景**（携带 `X-Gateway-Id` 直接出局）， **不能走号码路由 + IVR 流程**。业务层负责在
> originate 前确定网关 ID，而非依赖 SIP 代理的号码路由机制。这保证了 c-leg 接通后立即加入会议的时序不被 IVR 业务逻辑打断。

### 8.3 挂断流程

- 任意一方挂断：ESL `CHANNEL_HANGUP` 事件 → `FsChannelHangUpEslEventHandler` 清理会议成员：
    - 如果是 A 或 B 挂断：将对应腿从会议移除，挂断 c-leg（`uuidKill`）。
    - 如果是手机（c-leg）挂断：会议自动从 conf 3000 移除 c-leg，剩余 A、B 继续通话（若剩余 2 方，FS 可能自动桥接回 1-to-1）。
    - 清理 `CallInfo` 与 Redis 缓存。

> **设计要点**：c-leg 不走 IVR 业务逻辑（不播放欢迎语、不收 DTMF），直接加入会议，保证三方通话的实时性与业务纯粹性。

### 8.4 通话记录与录音绑定

三方会议 c-leg 走豁免场景（不构造 CallInfo、不触发 `FsCallIRouteProcess`），而当前录音和 CDR 分别依赖：

- **录音**：`FsCallIRouteProcess.handler` L51-52 调用 `fsClient.record` 触发，依赖 `CallInfo` 存在
- **CDR**：`FsChannelHangUpCompleteEslEventHandler` L93-94 从 `CallInfo` 构造 `CallRecordDO` 并保存，录音路径从
  `callInfo.getRecord()` 取（L140）

因此 c-leg 走豁免场景时， **当前架构下无法自动录音、无法生成 CDR**。需通过"ESL 通道变量注入 +
挂断事件读取"机制补全，详见"十、通话记录与录音绑定机制"。

***

## 九、场景五：外部手机A → 外部手机B（转接/中继透传）

### 9.1 整体流程时序

```
外部系统/SIP代理业务层       SIP代理         FreeSWITCH        第三方网关1       第三方网关2       手机A       手机B
    │                       │      ┃ESL        │              │              │              │         │
    │ ①业务层发起"双向出局转接"请求                          │
    │ (指定手机A + gw1, 手机B + gw3)                        │
    │                       │      ┃          │              │              │              │         │
    │ 【SIP代理ESL驱动: a-leg + b-leg 并发起局】            │
    │                       │ ②ESL originate a-leg ┃►        │              │              │         │
    │                       │  {sip_h_X-Gateway-Id=gw1}      │              │              │         │
    │                       │  sofia/gateway/gw1/13800138001@代理              │              │         │
    │                       │  &park()        │              │              │              │         │
    │                       │ ③ESL originate b-leg ┃►        │              │              │         │
    │                       │  {sip_h_X-Gateway-Id=gw3}      │              │              │         │
    │                       │  sofia/gateway/gw3/13800138002@代理              │              │         │
    │                       │  &park()        │              │              │              │         │
    │                       │      ┃          │              │              │              │         │
    │ 【a-leg INVITE 回注: 走豁免场景】                       │
    │                       │      ┃◄─────────│ INVITE(gw1)  │              │              │         │
    │                       │ ④forwardToOutboundGateway(gw1)│              │              │         │
    │                       │ ──────────────────────────────► ⑤INVITE       │              │         │
    │                       │                ◄── 200 OK ──────│              │ ⑥A接听      │         │
    │                       │      ┃          │              │              │              │         │
    │ 【b-leg INVITE 回注: 走豁免场景】                       │
    │                       │      ┃◄─────────│ INVITE(gw3)  │              │              │         │
    │                       │ ④forwardToOutboundGateway(gw3)│              │              │         │
    │                       │ ──────────────────────────────────────────────► ⑦INVITE      │         │
    │                       │                ◄── 200 OK ──────────────────── │              │ ⑧B接听 │
    │                       │      ┃          │              │              │              │         │
    │ 【SIP代理ESL bridge】                                  │
    │                       │ ⑨ESL bridgeCall(a_leg, b_leg) ┃►              │              │         │
    │                       │      ┃          │              │              │              │         │
    │  通话建立(媒体:手机A↔网关1↔FS↔网关2↔手机B)
    │                       │      ┃          │              │              │              │         │
    │◄═══════════════════════════════════════════════════════════════════════════════════════►│
```

### 9.2 SIP 代理服务处理流程详解

#### 9.2.1 业务层触发

业务层调用 SIP 代理业务接口（不在 sipproxy 模块）发起双向出局转接：

- 输入：手机A、手机B、网关 ID 1、网关 ID 3。
- 行为：
    1. ESL `originate` a-leg（手机A）：`{sip_h_X-Gateway-Id=gw1}sofia/gateway/gw1/13800138001@代理 &park()`。
    2. ESL `originate` b-leg（手机B）：`{sip_h_X-Gateway-Id=gw3}sofia/gateway/gw3/13800138002@代理 &park()`。
    3. 等待两条腿 200 OK。
    4. ESL `bridgeCall(a_leg, b_leg)` 桥接。

#### 9.2.2 两条腿的 INVITE 都走豁免场景

a-leg 与 b-leg 的 INVITE 携带 `X-Gateway-Id`（gw1 与 gw3）、`source=FREESWITCH`：

- `SipInviteRequestHandler.handleIncomingRequest` 对两条腿均识别为 `FREESWITCH + 携带 gatewayId` → **走豁免分支**：
    - a-leg → `forwardToOutboundGateway(gw1)` → 转第三方网关1。
    - b-leg → `forwardToOutboundGateway(gw3)` → 转第三方网关2。
- **不走 IVR、不走号码路由**。

#### 9.2.3 为什么两条腿不能走号码路由 + IVR

双向出局转接的两条腿（a-leg、b-leg） **必须走豁免场景**，不能走号码路由 + IVR 流程，原因如下：

1. **IVR 流程会创建新腿，破坏双向桥接结构**：`FsCallIRouteProcess.handler` 匹配号码路由后调用 `FsIvrRouteHandler` →
   `flowNoticeService.notice` 驱动 IVR 流程。IVR 转接节点（routeType=2 外呼）通过 ESL `originate` **创建全新的腿**出局，而非将当前
   a-leg/b-leg 直接出局。这会导致：
    - a-leg 被 park 住等待 IVR 指令 → IVR originate 出新腿 a'-leg → a'-leg 接通后 bridge (a-leg, a'-leg)
    - b-leg 同理被 park → IVR originate 出新腿 b'-leg → bridge (b-leg, b'-leg)
    - 最终 `uuid_bridge(a-leg, b-leg)` 桥接的是两条 park 中的腿，实际通话路径变为 a-leg ↔ a'-leg ↔ 网关1 ↔ 手机A、b-leg ↔
      b'-leg ↔ 网关2 ↔ 手机B， **多出两条中间腿**，媒体路径不必要的跳数翻倍。
2. **双向桥接要求两条腿直接出局**：`uuid_bridge(a_leg, b_leg)` 要求 a-leg 和 b-leg 是两条独立的、已接通的出局腿，直接在 FS
   内部桥接 RTP 通道。如果走 IVR，a-leg 和 b-leg 都被 park 住，`uuid_bridge` 桥接的是两条等待中的腿，无法完成媒体桥接。
3. **IVR 业务逻辑不适合纯转接场景**：双向出局转接是"内部无坐席参与"的纯中继透传场景，不需要播放欢迎语、收 DTMF、ACD 选坐席等
   IVR 业务逻辑。强制走 IVR 会增加转接延迟（IVR 流程加载 + 节点执行 + originate 新腿），且可能错误触发业务逻辑（如 IVR
   中配置了转人工节点）。
4. **两条腿需要并行发起、对称处理**：双向出局转接要求 a-leg 和 b-leg 几乎同时 originate，任意一条腿接通后等待另一条腿，最终
   `uuid_bridge`。走 IVR 会让两条腿各自独立走号码路由 → IVR → originate 新腿，时序不可控，难以保证并行性。

**正确做法**：业务层在发起 originate **之前**自行确定两条腿各自的出局网关 ID，然后用确定的网关 ID 构造携带 `X-Gateway-Id`
的 originate 命令，两条腿均走豁免场景（直接出局 + uuid\_bridge）：

```
业务层确定网关 ID 的处理流程:
├── 1. 对手机A: 调用 CallRouteService.getListByRouteNumberAndType(手机A, 2) 匹配号码路由表
│   ├── 取匹配到的 flowId → 查询 IVR 流程中 routeType=2 转接节点的 routeValue（兜底网关 ID）
│   ├── 确定 a-leg 出局网关 ID:
│   │   ├── 业务侧显式指定网关 ID → 使用它
│   │   ├── routeValue 非空 → 使用 routeValue
│   │   └── 两者为空 → 使用当前连接的 FS 兜底（通过 FS 本地 sofia profile external 出局）
│   └── 用确定的网关 ID 构造 originate: {sip_h_X-Gateway-Id=gwX}sofia/gateway/gwX/手机A@代理 &park()
├── 2. 对手机B: 同上流程确定 b-leg 出局网关 ID
├── 3. 并行发起两条腿的 originate
└── 4. 两条腿均走豁免场景 → forwardToOutboundGateway → 直接出局 → bridgeCall(a_leg, b_leg)
```

> **设计约束**：双向出局转接的两条腿（a-leg、b-leg） **必须走豁免场景**（携带 `X-Gateway-Id` 直接出局）， **不能走号码路由 +
IVR 流程**。业务层负责在 originate 前确定两条腿各自的网关 ID，而非依赖 SIP 代理的号码路由机制。这保证了：
>
> - 两条腿直接出局，无中间腿，媒体路径最短
> - 两条腿可并行发起，时序可控
> - `uuid_bridge` 桥接的是两条已接通的出局腿，媒体桥接可靠完成
> - 不触发 IVR 业务逻辑，避免转接延迟和错误触发

#### 9.2.4 媒体桥接

ESL `bridgeCall(a_leg, b_leg)` 由 SIP 代理通过 ESL 连接发送，FS 内部桥接 a-leg 与 b-leg 的 RTP 通道， **两条腿不经过 SIP
代理的媒体层**，媒体路径为：

```
手机A ↔ 第三方网关1 ↔ FS（FS1 的 a-leg RTP）↔ FS（FS1 的 b-leg RTP）↔ 第三方网关2 ↔ 手机B
```

> **设计要点**：双向出局转接用于"内部没有坐席参与"的纯转接场景（如客服外呼转人工转接到另一条线路），豁免号码路由 + IVR
> 流程，提升转接效率并避免错误触发业务逻辑。

### 9.3 错误处理

| 错误场景              | 处理策略                                                                   |
|-----------------------|----------------------------------------------------------------------------|
| a-leg 出局失败        | `uuidKill(b_leg)` 释放 b-leg；CDR 记录"a-leg 出局失败"                     |
| b-leg 出局失败        | `uuidKill(a_leg)` 释放 a-leg；CDR 记录"b-leg 出局失败"                     |
| 网关 ID 1/3 失效      | `forwardToOutboundGateway` 前置校验；阻断并告警"网关 ID 无效或指向内部 FS" |
| 业务层发起时无网关 ID | 阻断发起；要求业务侧必须显式指定两端网关 ID                                |

### 9.4 通话记录与录音绑定

双向出局转接的 a-leg 和 b-leg 均走豁免场景（不构造 CallInfo、不触发 `FsCallIRouteProcess`），与场景四同理，当前架构下无法自动录音、无法生成
CDR。需通过"ESL 通道变量注入 + 挂断事件读取"机制补全，详见"十、通话记录与录音绑定机制"。

***

## 十、通话记录与录音绑定机制

> **适用范围**：全部 7 个场景。场景一/二/三走号码路由 + IVR，由 `FsCallIRouteProcess` 驱动录音 + `transfer(CallInfo)` 构造
> CDR；场景四/五/六/七走豁免场景，由 ESL 通道变量注入 + `transferFromEslEvent(EslEvent)` 构造 CDR。两条路径最终都写入同一张
> `cc_call_record` 表。

### 10.1 数据表结构：cc\_call\_record

通话记录统一存储在 `cc_call_record` 表中，对应的 DO
为 [CallRecordDO](file:///Users/wenjiaqi/Documents/yudao-cloud-cc/yudao-cloud/yudao-module-cc/yudao-module-cc-server/src/main/java/cn/iocoder/yudao/module/cc/dal/dataobject/call/CallRecordDO.java)。

| 字段                | 类型     | 说明                    | IVR 场景来源           | 豁免场景来源                                |
|---------------------|----------|-------------------------|------------------------|---------------------------------------------|
| `call_id`           | varchar  | 呼叫唯一 ID             | `CallInfo.callId`      | ESL 变量 `cc_call_id`                       |
| `caller_number`     | varchar  | 主叫号码                | `CallInfo.caller`      | ESL 标准字段 `Caller-Caller-ID-Number`      |
| `callee_number`     | varchar  | 被叫号码                | `CallInfo.callee`      | ESL 标准字段 `Caller-Destination-Number`    |
| `agent_id`          | bigint   | 坐席 ID                 | `CallInfo.agentId`     | ESL 变量 `cc_agent_id`                      |
| `direction`         | tinyint  | 呼叫方式(1-呼出 2-呼入) | `CallInfo.direction`   | 固定 1(呼出)                                |
| `call_start_time`   | datetime | 呼叫开始时间            | `CallInfo.callTime`    | ESL 标准字段 `Caller-Channel-Created-Time`  |
| `answer_time`       | datetime | 接通时间                | `CallInfo.answerTime`  | ESL 标准字段 `Caller-Channel-Answered-Time` |
| `call_end_time`     | datetime | 呼叫结束时间            | `LocalDateTime.now()`  | ESL 标准字段 `Caller-Channel-Hangup-Time`   |
| `hangup_cause_code` | int      | 挂机原因                | `CallInfo.hangupCause` | ESL 标准字段 `Hangup-Cause`                 |
| `file_path`         | varchar  | 录音文件地址            | `CallInfo.record`      | ESL 变量 `cc_record_path`                   |
| `gateway_id`        | varchar  | **网关 ID**(新增)       | `CallInfo.gatewayId`   | ESL 变量 `variable_sip_h_X-Gateway-Id`      |
| `call_type`         | int      | **呼叫类型**(新增)      | `CallInfo.callType`    | ESL 变量 `cc_call_type`                     |
| `tenant_id`         | bigint   | 租户 ID                 | `CallInfo.tenantId`    | ESL 变量 `cc_tenant_id`                     |

`call_type` 取值规范：

| 取值 | 含义     | 对应场景           | 路由方式                 |
|------|----------|--------------------|--------------------------|
| 1    | IVR 呼叫 | 场景一/二/三       | 号码路由 + IVR           |
| 2    | 出局呼叫 | 场景三中外呼节点   | 号码路由 + IVR           |
| 3    | 内部呼叫 | 场景一/二          | 号码路由 + IVR           |
| 4    | 三方会议 | 场景四 c-leg       | 豁免（直接出局）         |
| 5    | 双向出局 | 场景五 a-leg/b-leg | 豁免（直接出局）         |
| 6    | 转接     | 场景六 c-leg       | 豁免（直接出局）         |
| 7    | 自动外呼 | 场景七 a-leg       | ESL originate 直发 → IVR |

### 10.2 两条 CDR 构建路径

CDR
构建统一在 [FsChannelHangUpCompleteEslEventHandler](file:///Users/wenjiaqi/Documents/yudao-cloud-cc/yudao-cloud/yudao-module-cc/yudao-module-cc-server/src/main/java/cn/iocoder/yudao/module/cc/esl/handler/esl/FsChannelHangUpCompleteEslEventHandler.java)
的 `handleEslEvent` 方法中，根据 `CallInfo` 是否存在分两条路径：

```
FsChannelHangUpCompleteEslEventHandler.handleEslEvent(address, event):
│
├── String uniqueId = EslEventUtil.getUniqueId(event)
├── handleConferenceHangup(address, uniqueId)                          ← 会议挂断处理（通用）
│
├── CallInfo callInfo = fsCallCacheService.getCallInfoByUniqueId(uniqueId)
│
├── if (callInfo != null):
│   ├── 【路径 A: IVR 场景】
│   ├── 更新 channelInfo 挂断信息
│   ├── 最后一个通道挂断时(count == 1):
│   │   ├── changeAgentStatus(callInfo)                                ← 坐席状态变更
│   │   ├── CallRecordDO callRecord = transfer(callInfo)               ← 从 CallInfo 构造 CDR
│   │   ├──   ├── callRecord.setGatewayId(callInfo.getGatewayId())     ← 网关 ID 从 CallInfo 取
│   │   ├──   ├── callRecord.setCallType(callInfo.getCallType())       ← 呼叫类型从 CallInfo 取
│   │   ├──   └── callRecord.setFilePath(callInfo.getRecord())         ← 录音路径从 CallInfo 取
│   │   ├── callRecordService.saveAssignTenantId(callRecord)           ← 保存到 cc_call_record
│   │   ├── handleAutoCallResult(event, callInfo, callRecord)          ← 自动外呼结果回写
│   │   └── fsCallCacheService.removeCallInfo(callInfo.getCallId())    ← 清理缓存
│   └── fsCallCacheService.saveCallInfo(callInfo)
│
└── if (callInfo == null):
    └── 【路径 B: 豁免场景兜底】
        └── handleExemptionCdr(event, uniqueId)
            ├── String ccCallId = EslEventUtil.getCcCallId(event)      ← 读取通道变量 cc_call_id
            ├── if (ccCallId 为空) → 非业务 originate 的腿,跳过
            ├── CallRecordDO callRecord = transferFromEslEvent(event)  ← 从 ESL 事件构建 CDR
            │   ├── callRecord.setCallId(EslEventUtil.getCcCallId(event))
            │   ├── callRecord.setCallType(EslEventUtil.getCcCallType(event))
            │   ├── callRecord.setTenantId(EslEventUtil.getCcTenantId(event))
            │   ├── callRecord.setAgentId(EslEventUtil.getCcAgentId(event))
            │   ├── callRecord.setCallerNumber(EslEventUtil.getCallerCallerIdNumber(event))
            │   ├── callRecord.setCalleeNumber(EslEventUtil.getCallerDestinationNumber(event))
            │   ├── callRecord.setGatewayId(EslEventUtil.getGatewayId(event))
            │   ├── callRecord.setCallStartTime(convertEpochMicrosToLocalDateTime(CreatedTime))
            │   ├── callRecord.setAnswerTime(convertEpochMicrosToLocalDateTime(AnsweredTime))
            │   ├── callRecord.setCallEndTime(convertEpochMicrosToLocalDateTime(HangupTime))
            │   ├── callRecord.setRingingTime(convertEpochMicrosToLocalDateTime(ProgressTime))
            │   ├── callRecord.setHangupCauseCode(FsHangupCauseEnum.getByValue(Hangup-Cause))
            │   ├── callRecord.setFilePath(EslEventUtil.getCcRecordPath(event))
            │   ├── callRecord.setCallState(正常挂机→1, 否则→2)
            │   ├── callRecord.setDirection(1)                          ← 豁免场景均为出局
            │   └── callRecord.setAnswerFlag(0)
            └── callRecordService.saveAssignTenantId(callRecord)        ← 保存到 cc_call_record
```

### 10.3 路径 A：IVR 场景（号码路由 + IVR）

**适用场景**：场景一/二/三（内部坐席间呼叫、外部呼入、坐席外呼）。

**录音触发**：`FsCallIRouteProcess.handler` 在匹配号码路由后、驱动 IVR 之前，调用 `fsClient.record` 触发录音，录音路径存入
`CallInfo.record`：

```
CHANNEL_PARK 事件
  → FsCallIRouteProcess.handler
    ├── fsClient.record(address, callInfo.getCallId(), uniqueId, filePath)  ← 录音触发
    ├── callInfo.setRecord(filePath)                                         ← 录音路径存入 CallInfo
    └── routeFactory.factory(IVR).handler(...)                               ← 驱动 IVR
```

**CDR 构造**：`transfer(CallInfo callInfo)` 方法（L112-150）从 `CallInfo` 构造 `CallRecordDO`，录音路径从
`callInfo.getRecord()` 取。新增的 `gatewayId` 和 `callType` 字段也从 `CallInfo` 对应字段填入。

**特点**：

- `CallInfo` 在 SIP 代理层构造 INVITE 时创建，并缓存到 Redis
- 录音由 `FsCallIRouteProcess` 主动触发，文件路径由代码生成
- CDR 在最后一个通道挂断时生成（`count == 1`），保证一次通话只生成一条 CDR
- 支持坐席状态变更、自动外呼结果回写等后处理

### 10.4 路径 B：豁免场景（ESL 通道变量注入 + 挂断事件读取）

**适用场景**：场景四/五/六（三方会议 c-leg、双向出局 a/b-leg、REFER 转接 c-leg）。

这些场景的腿不经过 `FsCallIRouteProcess`（不 park、不构造 `CallInfo`），路径 A 无法生效。

> **场景七例外**：场景七（自动外呼）的 a-leg 由 `AutocallServiceImpl` 构造 `CallInfo` 并保存到缓存，挂断时走路径 A（
> `transfer(CallInfo)`），不使用路径 B。

#### 10.4.1 业务层 originate 时注入通道变量

业务层在发起 ESL originate 命令时，除了携带 `sip_h_X-Gateway-Id`，还需注入以下业务变量：

```
originate {
  sip_h_X-Gateway-Id=gw3,
  cc_call_id=T001,                              ← 业务层生成的全局唯一通话 ID
  cc_call_type=4,                               ← 呼叫类型:4-三方会议 5-双向出局 6-转接 7-自动外呼
  cc_tenant_id=1,                               ← 租户 ID
  cc_agent_id=1001,                             ← 关联坐席 ID(三方会议为发起坐席,双向出局可为空)
  cc_record_path=/recordings/1/2026-07-22/R001.wav,  ← 录音文件路径(业务层预先确定)
  execute_on_answer='record_session /recordings/1/2026-07-22/R001.wav'  ← 接通后自动录音
} sofia/gateway/gw3/13800138000@代理 &park()
```

#### 10.4.2 EslEventUtil 中的变量定义

[EslEventUtil](file:///Users/wenjiaqi/Documents/yudao-cloud-cc/yudao-cloud/yudao-module-cc/yudao-module-cc-server/src/main/java/cn/iocoder/yudao/module/cc/esl/utils/EslEventUtil.java)
中新增的常量和 getter 方法：

| 常量                      | 值                        | getter 方法              | 说明              |
|---------------------------|---------------------------|--------------------------|-------------------|
| `VARIABLE_CC_CALL_ID`     | `variable_cc_call_id`     | `getCcCallId(event)`     | 全局唯一通话 ID   |
| `VARIABLE_CC_CALL_TYPE`   | `variable_cc_call_type`   | `getCcCallType(event)`   | 呼叫类型(4/5/6/7) |
| `VARIABLE_CC_TENANT_ID`   | `variable_cc_tenant_id`   | `getCcTenantId(event)`   | 租户 ID           |
| `VARIABLE_CC_AGENT_ID`    | `variable_cc_agent_id`    | `getCcAgentId(event)`    | 坐席 ID           |
| `VARIABLE_CC_RECORD_PATH` | `variable_cc_record_path` | `getCcRecordPath(event)` | 录音文件路径      |

同时复用已有的 `VARIABLE_SIP_GATEWAY_ID`（`variable_sip_h_X-Gateway-Id`）读取网关 ID。

#### 10.4.3 录音机制：execute\_on\_answer + record\_session

豁免场景的录音由 FS 内置变量 `execute_on_answer` 驱动：

- 业务层在 originate 时注入 `execute_on_answer='record_session /path/to/file.wav'`
- FS 在通道接通（answer）后自动执行 `record_session` APP，开始录制
- 录音文件路径由业务层预先确定，通过 `cc_record_path` 通道变量同时注入
- 挂断事件中 `variable_cc_record_path` 可读回，用于 CDR 的 `filePath` 字段

> **与 IVR 场景录音的区别**：IVR 场景由 `FsCallIRouteProcess` 调用 `fsClient.record` 触发，文件路径由代码生成（
> `{recordFile}/{tenantId}/{yyyy-MM-dd}/{agentNumber}_{callId}_{timestamp}.wav`，路径包含 tenantId 子目录用于租户隔离，文件名包含
> agentNumber 用于坐席识别，agentNumber 为空时使用 "unknown" 兜底，tenantId 为空时使用 "default" 兜底）；豁免场景由
> `execute_on_answer` 自动触发，文件路径由业务层预先确定。两种方式最终都通过 CDR 的 `filePath` 字段关联录音文件。

#### 10.4.4 transferFromEslEvent 方法：从 ESL 事件构建 CDR

`FsChannelHangUpCompleteEslEventHandler.transferFromEslEvent(EslEvent event)` 方法从 ESL 事件的标准字段和业务通道变量构建
`CallRecordDO`：

| CallRecordDO 字段 | 数据来源                  | EslEventUtil 方法                                          |
|-------------------|---------------------------|------------------------------------------------------------|
| `callId`          | 通道变量 `cc_call_id`     | `getCcCallId(event)`                                       |
| `callType`        | 通道变量 `cc_call_type`   | `getCcCallType(event)`                                     |
| `tenantId`        | 通道变量 `cc_tenant_id`   | `getCcTenantId(event)`                                     |
| `agentId`         | 通道变量 `cc_agent_id`    | `getCcAgentId(event)`                                      |
| `callerNumber`    | ESL 标准字段              | `getCallerCallerIdNumber(event)`                           |
| `calleeNumber`    | ESL 标准字段              | `getCallerDestinationNumber(event)`                        |
| `gatewayId`       | SIP 头透传变量            | `getGatewayId(event)`                                      |
| `callStartTime`   | ESL 标准字段(微秒时间戳)  | `getCallerChannelCreatedTime(event)`                       |
| `answerTime`      | ESL 标准字段(微秒时间戳)  | `getCallerChannelAnsweredTime(event)`                      |
| `callEndTime`     | ESL 标准字段(微秒时间戳)  | `getCallerChannelHangupTime(event)`                        |
| `ringingTime`     | ESL 标准字段(微秒时间戳)  | `getCallerChannelProgressTime(event)`                      |
| `hangupCauseCode` | ESL 标准字段              | `getHangupCause(event)` → `FsHangupCauseEnum.getByValue()` |
| `filePath`        | 通道变量 `cc_record_path` | `getCcRecordPath(event)`                                   |
| `callState`       | 挂断原因判断              | 正常挂机→1, 否则→2                                         |
| `direction`       | 固定值                    | 1(呼出)                                                    |
| `answerFlag`      | 固定值                    | 0(接通)                                                    |

> **时间转换**：FS 时间戳为微秒精度，`convertEpochMicrosToLocalDateTime(String epochMicros)` 方法将其除以 1000 转为毫秒，再通过
> `LocalDateTime.ofInstant(new Date(millis).toInstant(), ZoneId.systemDefault())` 转换为 `LocalDateTime`。

### 10.5 录音与 CDR 绑定关系

```
业务层 originate 前:
├── 生成 cc_call_id=T001 (全局唯一)
├── 确定录音文件路径: /recordings/1/2026-07-22/R001.wav
└── 注入 ESL 通道变量: {cc_call_id=T001, cc_call_type=4, cc_record_path=/recordings/1/2026-07-22/R001.wav,
                         execute_on_answer='record_session /recordings/1/2026-07-22/R001.wav', ...}

FS 接通后:
├── execute_on_answer 触发 record_session → 生成录音文件 /recordings/1/2026-07-22/R001.wav
└── 通话过程中变量 cc_call_id/cc_call_type/cc_record_path 始终保留在通道上

FS 挂断后:
├── CHANNEL_HANGUP_COMPLETE 事件携带:
│   ├── variable_cc_call_id = T001
│   ├── variable_cc_call_type = 4
│   ├── variable_cc_record_path = /recordings/1/2026-07-22/R001.wav
│   ├── Caller-Caller-ID-Number = 13800138000
│   ├── Caller-Destination-Number = ...
│   ├── variable_sip_h_X-Gateway-Id = gw3
│   ├── Caller-Channel-Created-Time / Answered-Time / Hangup-Time
│   └── Hangup-Cause = NORMAL_CLEARING
│
└── FsChannelHangUpCompleteEslEventHandler (callInfo == null → 路径 B):
    ├── handleExemptionCdr(event, uniqueId)
    │   ├── 读回 cc_call_id=T001 → 作为 CDR.callId
    │   ├── 读回 cc_record_path=/recordings/1/2026-07-22/R001.wav → 作为 CDR.filePath
    │   ├── transferFromEslEvent(event) → 构造 CallRecordDO
    │   └── callRecordService.saveAssignTenantId(callRecord) → 写入 cc_call_record 表
    │
    └── cc_call_record 表记录:
        ├── call_id = T001
        ├── file_path = /recordings/1/2026-07-22/R001.wav  ← 录音文件路径
        ├── call_type = 4                                    ← 三方会议
        ├── gateway_id = gw3
        └── ...

查询时:
├── 按 call_id=T001 查 cc_call_record → 取 file_path → 播放/下载录音文件
└── 录音与 CDR 通过 call_id 关联
```

### 10.6 各场景适配矩阵

| 场景              | 路由方式               | CDR 路径                                         | 录音触发            | call\_type | 需注入变量                                                                |
|-------------------|------------------------|--------------------------------------------------|---------------------|------------|---------------------------------------------------------------------------|
| 场景一(内部坐席)  | 号码路由+IVR           | A: transfer(CallInfo)                            | FsCallIRouteProcess | 3          | 无(CallInfo 由 SIP 代理构造)                                              |
| 场景二(外部呼入)  | 号码路由+IVR           | A: transfer(CallInfo)                            | FsCallIRouteProcess | 1          | 无(CallInfo 由 SIP 代理构造)                                              |
| 场景三(坐席外呼)  | 号码路由+IVR           | A: transfer(CallInfo)                            | FsCallIRouteProcess | 2          | 无(CallInfo 由 SIP 代理构造)                                              |
| 场景四(三方会议)  | 豁免                   | B: transferFromEslEvent                          | execute\_on\_answer | 4          | cc\_call\_id/cc\_call\_type/cc\_tenant\_id/cc\_agent\_id/cc\_record\_path |
| 场景五(双向出局)  | 豁免                   | B: transferFromEslEvent                          | execute\_on\_answer | 5          | 两条腿各注入独立变量                                                      |
| 场景六(REFER转接) | 豁免                   | B: transferFromEslEvent                          | execute\_on\_answer | 6          | cc\_call\_id/cc\_call\_type/cc\_tenant\_id/cc\_agent\_id/cc\_record\_path |
| 场景七(自动外呼)  | ESL originate 直发→IVR | A(CallInfo 由 AutocallServiceImpl 构造)+A(IVR段) | execute\_on\_answer | 7          | cc\_call\_id/cc\_call\_type/cc\_tenant\_id/cc\_record\_path               |

> **场景七特殊处理**：场景七的 a-leg 由 `AutocallServiceImpl` 构造 `CallInfo` 并注入 `execute_on_answer` 录音变量（ESL
> originate 直发，不走 sipproxy），接通后 `FsChannelParkEslEventHandler.autocallPark` 走 IVR 流程时 `FsCallIRouteProcess`
> 会再次触发 `fsClient.record`。需在 `FsCallIRouteProcess` 中增加判断：如果 `callInfo.getRecord()` 已有值（说明
> `execute_on_answer` 已启动录音），则跳过 `fsClient.record` 调用，避免重复录音。CDR 方面，a-leg 走路径 A（`CallInfo` 由
> `AutocallServiceImpl` 构造），后续 IVR 创建的新腿走路径 A，最终生成两条 CDR 记录，通过 `call_id` 关联。

### 10.7 对现有 IVR 场景的影响

此方案 **不影响**现有走号码路由 + IVR 的场景（场景一/二/三）：

- 录音仍由 `FsCallIRouteProcess` 调用 `fsClient.record` 触发
- CDR 仍由 `transfer(CallInfo)` 构造，`callInfo != null` → 走路径 A（现有逻辑）
- 新增的 `transferFromEslEvent(EslEvent)` 方法仅在 `callInfo == null` 时触发（路径 B）
- `CallRecordDO` 新增的 `gatewayId` 和 `callType` 字段对 IVR 场景也生效（从 `CallInfo` 对应字段填入），IVR 场景的 CDR
  记录将更完整

> **演进建议**：长期来看，建议将录音和 CDR 逻辑 **统一从** **`FsCallIRouteProcess`** **中抽离**，所有场景（包括 IVR 场景）都通过
> `execute_on_answer` + 通道变量注入 + 挂断事件读取的方式实现，实现录音/CDR 与路由方式的完全解耦。此重构属于 v3.1 紧急修复范围（CDR
> 持久化和录音文件命名规范已修复，详见十、通话记录与录音绑定机制）。

***

## 十一、场景六：坐席间通话中转接到外部手机

### 11.1 咨询转接（Attended Transfer）

```
坐席A        坐席B         SIP代理          FreeSWITCH        第三方网关       手机
  │             │            │      ┃ESL        │              │              │
  │  ①A-B 通话中(参见场景一)                                  │
  │═════════════╪═════════════╡      ┃          │              │              │
  │             │            │      ┃          │              │              │
  │── 转接 (Refer-To:手机号)─►│      ┃          │              │              │
  │   X-Transfer-Type: attended       ┃          │              │              │
  │   X-Gateway-Id: gw3              ┃          │              │              │
  │             │            │ ②WsReferRequestHandler:        │
  │             │            │  findAgentChannel(A分机)        │
  │             │            │  →取a-leg/b-leg UUID            │
  │             │            │  →uuidHold(a_leg)              │
  │             │            │  ③ESL originate (sip_h_X-Gateway-Id=gw3)            │
  │             │            │  sofia/gateway/gw3/138@代理      │
  │             │            │  →直接出局(走makeCall)         │
  │             │            │      ┃          │              │              │
  │             │            │  ④B与外部手机通话(FS bypass)                   │
  │             │            │      ┃          │ INVITE(gw3)→forwardToOutboundGateway  │
  │             │            │      ┃          │              │              │
  │             │            │      ┃          │              │ INVITE ────►│ ⑤
  │             │            │      ┃          │              │  ◄─ 200 OK ──│ ⑥
  │             │            │      ┃          │  c-leg 已加入 B的桥接             │
  │             │            │      ┃          │              │              │
  │  通话结构: A(hold) + B↔手机(bridge)                          │
  │═══════════════════════════════════════════════════════════════►│
```

### 11.2 盲转（Blind Transfer）

```
坐席A        坐席B         SIP代理          FreeSWITCH        第三方网关       手机
  │             │            │      ┃          │              │              │
  │  ①A-B 通话中(参见场景一)                                  │
  │═════════════╪═════════════╡      ┃          │              │              │
  │             │            │      ┃          │              │              │
  │── 转接 (Refer-To:手机号)─►│      ┃          │              │              │
  │   X-Transfer-Type: blind          ┃          │              │              │
  │   X-Gateway-Id: gw3              ┃          │              │              │
  │             │            │ ②WsReferRequestHandler:        │
  │             │            │  findAgentChannel(A分机)        │
  │             │            │  ③ESL originate (sip_h_X-Gateway-Id=gw3)            │
  │             │            │  sofia/gateway/gw3/138@代理      │
  │             │            │  →直接出局(走makeCall)         │
  │             │            │      ┃          │              │              │
  │             │            │  ④ESL bridgeCall(B_leg, c_leg) ┃►              │
  │             │            │  →挂断A_leg(REPLACES语义)        │
  │             │            │      ┃          │ INVITE(gw3)→forwardToOutboundGateway  │
  │             │            │      ┃          │              │              │
  │             │            │      ┃          │              │ INVITE ────►│ ⑤
  │             │            │      ┃          │              │  ◄─ 200 OK ──│ ⑥
  │             │            │      ┃          │              │              │
  │  通话结构: B↔手机(bridge)                                  │
  │             │═══════════════════════════════════════════►│
```

### 11.3 SIP 代理服务处理流程详解

#### 11.3.1 WsReferRequestHandler.doHandle

1. 解析 `Refer-To`、`X-Transfer-Type`、`X-Gateway-Id`。
2. **`findChannelByAgentNumber(agentNumber, domain)`**：
    - 调用 `sysAgentService.listByNameAndDomainNoTenant` 获取坐席 DO。
    - 遍历 `FsCallCacheService.getAllCallInfos()` 中所有 CallInfo 的 `channelMap`，匹配
      `agentNumber.equals(channelInfo.getAgentNumber())` 的 ChannelInfo。
    - 返回该 ChannelInfo（含 `uniqueId` / `otherUniqueId` / `channelName`）。
3. **提取 FS 地址**：通过 `nodeManager.getSessionNode(callId)` 取会话绑定的 FS 节点，避免 `System.currentTimeMillis()`
   随机选错 FS。
4. 发送 202 Accepted。
5. 分发处理：
    - `attended` → `handleAttendedTransfer`：`uuidHold(a_leg)` → `makeCall` 发起外部目标。
    - `blind` → `handleBlindTransfer`：`makeCall` 发起外部目标 → `bridgeCall(B_leg, c_leg)` → 挂断 a-leg。

#### 11.3.2 makeCall 路径（携带/未携带 X-Gateway-Id 折中方案）

- **携带** **`X-Gateway-Id=gw3`**（`WsReferRequestHandler.originateTarget` L238-247）：
    - `fsSipGatewayService.getFsSipGateway(Long.valueOf(gatewayId))` + `fsClient.makeCall(..., sipGateway=gw3)`。
    - **FS 直接走 gateway 出局（不回注到 SIP 代理）** → 不触发 `CHANNEL_PARK` → 不走 IVR。
    - 通过 `bridgeCall` 桥接 B 腿与 C 腿。
- **未携带** **`X-Gateway-Id`**（L248-256）：
    - `fsClient.makeInternalCall(..., sipProxyAddr)`，FS 发 INVITE 给 SIP 代理。
    - SIP 代理 `SipInviteRequestHandler`（`source=FREESWITCH, gatewayId=null`）→ `forwardToFreeSwitch` → park →
      走号码路由 → IVR。
    - 适用于"未指定出局网关、依赖号码路由匹配"的转接场景。

#### 11.3.3 转接上下文缓存

- `cacheTransferContext`：缓存 `transfer:{type}:{aLeg}:{bLeg}[:{gatewayId}]` 到 `CallInfo.transferContext`（ **不污染**
  `CallInfo.gatewayId` 字段，与"网关 ID 覆盖"语义解耦）。

> **设计要点**：转接的目标号码（外部手机）原则上应走号码路由 → IVR 流程 → IVR 转接节点（routeType=2 外呼）→ 使用
> `CallInfo.gatewayId` 覆盖网关 ID → 出局。但考虑到 转接场景对延迟敏感（多一次 IVR 流程加载会增加转接延迟），且业务侧通过 转接
> 携带 `X-Gateway-Id` 已显式指定出局网关，因此采用 **折中方案**：
>
> - 携带 `X-Gateway-Id` → 走 `makeCall` 直接出局，跳过 IVR（最低延迟）。
> - 未携带 `X-Gateway-Id` → 走号码路由 + IVR（兜底逻辑）。

***

## 十二、场景七：机器人自动外呼（指定 IVR 流程）

### 12.1 整体流程时序

```
外呼任务模块           SIP代理         FreeSWITCH        第三方网关       手机
    │                  │      ┃ESL        │              │              │
    │ ①业务侧发起"机器人外呼"任务                                │
    │ (指定手机号 + ivr_flow + 选中的网关 gw3)                    │
    │                  │      ┃          │              │              │
    │ ②缓存任务上下文:  task_id → ivr_flow (Redis)              │
    │                  │      ┃          │              │              │
    │ ③ESL originate ┃► (task_id=T001, ivr_flow=flow_01)      │
    │   sofia/external/13800138000@{gateway.realm} &park()     │
    │                  │      ┃          │              │              │
    │ 【FS 直接向第三方网关发起 INVITE，不走 sipproxy】            │
    │                  │      ┃          │ INVITE       │              │
    │                  │      ┃          │─────────────►│ ⑤INVITE      │
    │                  │      ┃          │◄── 200 OK ──│ ⑥手机接听    │
    │                  │      ┃          │              │              │
    │ 【ESL IVR 驱动】                                          │
    │                  │ ⑦ESL IVR (flow_01) 流程启动          │
    │                  │  →播放欢迎语、收DTMF、按键路由等         │
    │                  │  →可由 IVR 节点触发"转人工坐席"          │
    │                  │      ┃          │              │              │
    │  通话建立(IVR 媒体流程 + 机器人语音)                        │
    │◄═══════════════════════════════════════════════════════════════►│
```

### 12.2 SIP 代理服务处理流程详解

#### 12.2.1 外呼任务模块（业务侧）

1. 业务侧发起"机器人外呼"任务，参数：手机号、`ivr_flow`、`gatewayId`。
2. 缓存任务上下文到 Redis（`autocall:task:{taskId}`）：`task_id → ivr_flow`。
3. `AutocallServiceImpl` 通过 `fsClient.sendAsyncMsg` 直接调用 FS 发起 `originate`， **不走 sipproxy INVITE 转发**：
   ```
   originate {return_ring_ready=true,sip_contact_user=callerId,...,
              task_id=T001,ivr_flow=flow_01}
   sofia/external/13800138000@{gateway.realm} &park()
   ```
    - 使用 `sofia/external` profile（非 `sofia/gateway`），目标为 `target@gateway.realm`。
    - `gatewayId` 用于查询网关配置获取 `realm`，构造出局目标地址；不注入 `sip_h_X-Gateway-Id` 通道变量。
    - `gatewayId` 为空时，目标为 `target`，由 FS 本地 `sofia profile external` 兜底出局。

#### 12.2.2 a-leg INVITE 直发网关（ESL originate 直发，不走 sipproxy）

`AutocallServiceImpl` 通过 `fsClient.originate` 直接调用 FS 发起呼叫，FS 使用 `sofia/external` profile 直接向第三方网关（
`gateway.realm`）发起 INVITE， **不经过 sipproxy INVITE 转发**：

- 不涉及 `SipInviteRequestHandler`、不触发 `forwardToOutboundGateway`、不走豁免分支。
- 不注入 `sip_h_X-Gateway-Id` 通道变量，a-leg INVITE 不携带 `X-Gateway-Id` 头。
- **不走号码路由**（由 `task_id` + `ivr_flow` 显式指定 IVR 流程）。

#### 12.2.3 第三方网关接通后，IVR 启动

接通后，SIP 代理通过 ESL 驱动 IVR 流程：

```
FsChannelParkEslEventHandler.autocallPark
├── 读取 variable_task_id → Redis 取 ivr_flow
├── 优先级1: ivr_flow 显式指定 → 直接 FlowNoticeService.notice(... ivrFlow)
│   └── 跳过号码路由匹配（不依赖 getCallRouteNoTenant）
├── 优先级2: ivr_flow 为空 → 走 FsCallIRouteProcess 号码路由匹配
└── IVR 流程节点: 播放欢迎语、收DTMF、转人工坐席 (routeType=1)
```

> **ivr\_flow 显式指定优先**：当外呼任务携带 `ivr_flow` 时， **优先**走指定的 IVR
> 流程（跳过号码路由），保证机器人外呼的"按预设流程执行"特性。 **未指定** `ivr_flow` 时， **兜底**走号码路由 → IVR（适用"按号码动态选
> IVR"场景）。

#### 12.2.4 IVR 转人工坐席

IVR 流程执行到 `routeType=1 转坐席` 节点：

1. ACD 选坐席（按技能、上次坐席、空闲时长等策略）。
2. ESL `originate` 到目标坐席（携带 `transfer_context=autocall:{taskId}`）。
3. `bridgeCall` 桥接外呼 c-leg 与坐席 b-leg。
4. 坐席接听 → IVR 退出 → 通话建立。

### 12.3 错误处理

| 错误场景           | 检测点                              | 处理策略                                                                    |
|--------------------|-------------------------------------|-----------------------------------------------------------------------------|
| 网关 ID 失效       | `forwardToOutboundGateway` 前置校验 | 阻断并告警；外呼任务标记"失败"                                              |
| 第三方网关不可达   | INVITE 超时                         | `uuidKill(c_leg)`；任务标记"出局失败"；CDR 记录"外呼失败"                   |
| ivr\_flow 不存在   | `FlowNoticeService.notice` 异常     | 挂断 c-leg；任务标记"IVR 流程无效"；告警"ivr\_flow \[flowId] 不存在"        |
| 第三方网关返回 407 | SipInviteRequestHandler 响应路径    | 重新注入 Authorization 头并重发 INVITE                                      |
| 坐席不在线         | IVR routeType=1 无可选坐席          | IVR 节点继续播放"请等待"语音；定期重试选坐席；超过阈值则挂断                |
| CPS 限流           | SIP 代理外呼并发超限                | 任务排队等待（令牌桶/漏桶），不直接拒绝；超过等待阈值则挂断并标记"系统繁忙" |

### 12.4 批量外呼的并发控制

批量外呼需控制 ESL originate 的并发速率，避免 FS 和网关过载：

```
批量外呼并发控制策略:
├── 令牌桶限流: 配置文件配置 cps（每秒呼叫数）、maxConcurrent（最大并发呼叫数）
├── 超限处理: 任务排队等待 → 超过 maxWait（最大等待时长，如 30s）则挂断
├── 实时监控: 通过 Micrometer 暴露 cps 指标、当前并发数、等待队列长度
└── 告警: cps 持续超过阈值 80% 触发告警，运维可手动调整速率
```

> **遗留优化点**：CPS 限流的 Micrometer 指标尚未实现。详见"十五、遗留问题与未来演进"。

***

## 十三、异常场景与可靠性

### 13.1 异常场景处理矩阵

| 异常场景                                     | 检测点                               | 处理策略                                                                                                                |
|----------------------------------------------|--------------------------------------|-------------------------------------------------------------------------------------------------------------------------|
| **号码路由表未匹配到任何规则**               | `FsCallIRouteProcess` 匹配失败       | `playFile(SYSTEM_ERROR)` + `hangupCall` + 告警 "号码 \[callee] 未匹配到路由规则"                                        |
| **号码路由匹配但 flowId 为空**               | `CallRouteDO.flowId == null`         | 同上 + 告警 "号码路由 \[routeId] 的 flowId 为空"                                                                        |
| **IVR 流程不存在（flowId 无效）**            | `FlowNoticeService.notice` 异常      | 同上                                                                                                                    |
| **网关 ID 指向内部 FS（违规配置）**          | `forwardToOutboundGateway` 前置      | 阻断并返回 500；告警 "网关 ID 指向内部 FS，疑似回环"                                                                    |
| **网关 ID 在 FsSipGatewayDO 中不存在**       | `GatewayRouteServiceImpl` 查询       | 回退到 routeValue；都为空则用当前 FS 兜底；告警 "网关 ID 无效"                                                          |
| **第三方网关不可达（INVITE 超时）**          | INVITE 32s 超时 / 503 响应           | `playFile(SYSTEM_ERROR)` + `hangupCall`；ESL `uuidKill` 释放 a-leg；CDR 记录"出局失败"                                  |
| **第三方网关返回 407 Proxy Auth**            | `SipInviteRequestHandler` 响应       | ACK 后重发 INVITE（去除旧 To tag，参照 RFC 3261 流程）                                                                  |
| **第三方网关返回 401 Unauthorized**          | 同上                                 | 注入 Authorization 头并重发 INVITE                                                                                      |
| **主叫挂断（早释）**                         | `CHANNEL_HANGUP` 事件触发            | `uuidKill` 释放对端；CDR 记录"主叫早释"                                                                                 |
| **被叫忙/无应答/拒接**                       | 486/480/603 响应                     | `playFile(BUSY)` + `hangupCall`；CDR 记录"被叫忙/无应答/拒接"                                                           |
| **ESL 连接断开（FS 重启/网络闪断）**         | `funtureConnect` 重连                | 自动重连；已 bridge 通话继续；重连期间事件丢失由业务层容忍（号码路由匹配失败兜底为挂断）                                |
| **SIP 代理服务自身故障**                     | SPOF                                 | 通过 HA 方案（主备/集群）保障；已 bridge 通话可继续（FS 媒体层独立）                                                    |
| **FS 在 bridge 后故障**                      | 通话中 FS 宕机 → RTP 流中断          | 终端检测 RTP 超时（默认 30s）后挂断重拨；SIP 代理通过 ESL 心跳摘除故障 FS                                               |
| **re-INVITE 超时（Session Timer 刷新失败）** | `Session-Expires` 超时               | 依赖 Session Timer 机制，超时方发送 BYE 释放；SIP 代理作为 B2BUA 协调两侧释放                                           |
| **ACK 丢失（200 OK 重传）**                  | `ACK Timeout` 32s                    | FS 在 64×T1 后仍未收到 ACK 则释放呼叫；SIP 代理应正确转发 ACK 不吞没                                                    |
| **CPS（每秒呼叫数）过载**                    | 令牌桶/漏桶超限                      | 代理层返回 503 Service Unavailable + Retry-After；坐席客户端指数退避重试                                                |
| **转接坐席 A 通道查找失败**                  | `findChannelByAgentNumber` 返回 null | 返回 500 Server Error；CDR 记录"转接失败：找不到坐席 A 通道"（P0 已修复）                                               |
| **转接 FS 地址选择错误**                     | `extractFsAddress` 随机选错          | 改用 `nodeManager.getSessionNode(callId)` 取会话绑定的 FS（P0 已修复）                                                  |
| **BYE 挂断 c-leg 残留**                      | `FsChannelHangUpEslEventHandler`     | 已修复：读取 `Other-Leg-Unique-ID` 后调用 `fsClient.hangupCall` 释放关联腿，并清理 `CallInfo.channelMap`/`uniqueIdList` |
| **CDR 丢失（无持久化）**                     | 通话结束后无 CDR 记录                | 已修复：通过 `transferFromEslEvent` / `transfer(CallInfo)` 构建并持久化 CDR（详见第十章）                               |

### 13.2 B2BUA 错误协调策略

作为 B2BUA，SIP 代理需在两段对话中独立处理错误，并通过 ESL 协调 FS 端资源：

```
错误协调策略:
├── 主叫挂断（早释）:
│   ├── 收到 BYE → 回 200 OK
│   ├── ESL uuidKill 释放对端
│   └── CDR 记录 "主叫早释"
├── 媒体协商失败:
│   ├── 收到 488 Not Acceptable Here
│   ├── SIP 代理在两段对话中分别回 488
│   └── ESL uuidKill 释放两端
├── Timer B 超时:
│   ├── 在 FS 端超时（默认 32s）→ 触发 CHANNEL_HANGUP_COMPLETE 事件
│   ├── SIP 代理在另一段对话中回 504 Server Timeout
│   └── 清理 CallInfo 与 Redis 缓存
├── 网络中断:
│   ├── Keepalive 检测到离线 → 标记离线
│   ├── 释放该 callId 的所有通道
│   └── 通知业务侧 "网络中断"
```

### 13.3 Timer B 可配置性

不同运营商网关对 Timer B 有差异化要求（部分国际长途要求 60s，运营商内网可能 15s），SIP 代理应支持按网关 ID 维度配置 Timer B：

```java
// 伪代码
public long getTimerB(String gatewayId) {
    FsSipGatewayDO gateway = fsSipGatewayService.getFsSipGateway(gatewayId);
    return gateway != null ? gateway.getTimerB() : 32_000L; // 默认 32s
}
```

***

## 十四、SIP 代理服务核心能力总结

### 14.1 请求路由能力

| 能力                 | 实现要点                                                                                                                                                                                                                                                                 |
|----------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| 号码路由匹配（核心） | 所有 INVITE 到达后统一转发到内部 FS park → ESL 读取被叫号码 → 调用 `CallRouteService.getListByRouteNumberAndType` 按正则匹配号码路由表（type=1 呼入 / type=2 呼出）→ 用 `flowId` 驱动 IVR 流程。**所有呼叫（含内部坐席间呼叫）必须走号码路由 + IVR，不保留任何快速路径** |
| IVR 流程驱动         | 号码路由匹配成功后，用 `flowId` 驱动对应 IVR 流程；IVR 执行到转接节点（routeType=1 转坐席 / routeType=2 外呼）时通过 ESL originate 发起第二段呼叫                                                                                                                        |
| 网关 ID 覆盖         | IVR 转接节点（routeType=2 外呼）执行时按优先级确定出局网关 ID：`CallInfo.gatewayId`（INVITE 头携带）> `IVR 转接节点 routeValue`（IVR 配置）> 当前连接的 FS（CHANNEL\_PARK 事件来源 FS）兜底。详见 13.7 节"网关 ID 覆盖能力"                                              |
| 路由表查询           | 主备路由、负载均衡、按时间段路由                                                                                                                                                                                                                                         |
| 注册位置管理         | 所有 JSSIP 坐席均注册在 SIP 代理服务，维护 Contact 地址、GRUU 支持（待启用）                                                                                                                                                                                             |
| 网关选路             | 多台 FreeSWITCH/网关间 Failover、按主叫/被叫选路                                                                                                                                                                                                                         |
| 号码路由豁免场景     | 三方会议邀请外部手机、双向出局转接、转接（携带 X-Gateway-Id）三种场景豁免号码路由，直接通过 `forwardToOutboundGateway` 改写出局；自动外呼（场景七）通过 ESL originate 直发，不走 sipproxy                                                                                |

### 14.2 认证鉴权能力

```
请求到达
├── IP 白名单检查（第三方网关 IP）
├── Digest 认证（坐席用户名密码）
├── Token/Session 校验（业务系统集成）
├── 呼叫权限校验（内呼/外呼/国际权限）
└── 防盗打机制（频率限制、异常检测）
```

### 14.3 ESL 全权控制能力（核心）

SIP 代理服务通过 ESL（Event Socket Library） **全权控制** FreeSWITCH 的呼叫行为，FS 是纯粹的被动执行者：

```
ESL 控制能力:
├── 呼叫腿控制: originate（发起呼叫）、uuid_bridge（桥接两腿）、uuid_kill（挂断）
├── 媒体播放: uuid_broadcast/playback（播放语音）
├── DTMF 收号: play_and_get_digits（收集按键）
├── 录音控制: uuid_record（录音）
├── 会议控制: conference（创建/管理会议）
├── 事件监听: 订阅 CHANNEL_PARK/PROGRESS/ANSWER/BRIDGE/HANGUP 等事件
├── 变量操作: uuid_setvar（设置 channel 变量）
└── 全局控制: 通过 park 事件全局代理所有呼叫逻辑
```

**ESL 驱动的工作模式（所有场景统一）**：

```
统一呼叫控制流程（号码路由 + IVR 驱动）:
① FS 收到 INVITE → park 住 → 触发 CHANNEL_PARK 事件
② SIP 代理监听到 park 事件 → 读取被叫号码 + gatewayId（来自 variable_sip_h_X-Gateway-Id）
   → 调用 CallRouteService.getListByRouteNumberAndType 按正则匹配号码路由表:
   ├── 匹配成功 → 用 flowId 驱动 IVR 流程
   │   └── IVR 执行到转接节点:
   │       ├── routeType=1（转坐席）→ ESL originate 发第二段呼叫到坐席
   │       └── routeType=2（外呼）→ 按优先级确定出局网关 ID:
   │           ├── CallInfo.gatewayId 非空 → 用它作为出局网关 ID
   │           ├── IVR 转接节点 routeValue 非空 → 用它作为出局网关 ID
   │           └── 两者都为空 → 用当前连接的 FS（CHANNEL_PARK 事件来源 FS）兜底
   │           → ESL originate 发第二段呼叫（携网关 ID）到第三方网关
   └── 匹配失败 → 挂断呼叫并告警 "号码路由未匹配"
③ SIP 代理通过 ESL originate 驱动 FS 发起第二段呼叫
④ 第二段呼叫腿响应回传 → FS 两腿就绪
⑤ SIP 代理通过 ESL bridgeCall 驱动 FS 桥接两腿
⑥ FS 完成媒体锚定 → 通话建立

注：以下三种场景豁免号码路由，直接通过 forwardToOutboundGateway 改写出局:
- 三方会议邀请外部手机（c-leg 直接加入会议）
- 双向出局转接（坐席显式指定两端号码+网关 ID）
- 转接携带 X-Gateway-Id（折中方案，降低转接延迟）
- 机器人自动外呼（ESL originate 直发，不走 sipproxy，不经过 forwardToOutboundGateway）
```

### 14.4 协议转换能力

| 转换类型 | 说明                                                           |
|----------|----------------------------------------------------------------|
| 传输层   | WebSocket(JSSIP) ↔ UDP/TCP/TLS(FreeSWITCH/网关)                |
| 媒体协议 | WebRTC(SRTP/DTLS) ↔ 传统 RTP/SDES-SRTP（由 FreeSWITCH 完成）   |
| 编解码   | Opus/VP8 ↔ G.711/G.729（由 FreeSWITCH 转码）                   |
| SDP 协调 | SIP 代理服务协调 SDP 媒体锚定，确保媒体流经过指定的 FreeSWITCH |

### 14.5 媒体处理协调

SIP 代理服务虽不直接处理 RTP，但负责协调媒体路径决策：

- **所有媒体流必须经过 FreeSWITCH 中继**（系统设计原则）
- 通过负载均衡选择内部 FreeSWITCH 实例处理媒体（不再通过网关 ID 指定，网关 ID 仅作为 IVR 转接节点的出局覆盖项）
- 当 IVR 转接节点最终网关 ID 为空时，使用当前连接的 FS（CHANNEL\_PARK 事件来源 FS）作为出局目标
- 通过 ESL originate/uuid\_bridge 确保 FreeSWITCH 作为媒体锚点参与两段呼叫腿
- 协调录音、监听、转码等媒体能力的开启

### 14.6 错误处理与可靠性

```
错误场景                    代理处理策略
─────────────────────────────────────────────────────────────
FreeSWITCH 无响应            Timer B 超时 → 尝试备选 FS 实例
坐席未注册                   返回 404 → 可转语音信箱或手机
媒体协商失败                 488 Not Acceptable Here → 降级编解码重试
主叫挂断（早释）               487 Request Terminated → 通过 ESL uuidKill 通知 FS 清理资源
网络中断                     Keepalive 检测 → 标记离线 → 释放呼叫
ESL 连接断开                  重连机制 → 重新建立 ESL 连接 → 恢复呼叫控制
```

**补充异常场景**：

| 异常场景                                     | 影响分析                                                                    | 处理策略                                                                                                                                 |
|----------------------------------------------|-----------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------|
| **SIP 代理服务自身故障**                     | 作为信令核心（SPOF），全局呼叫受影响，新呼叫无法建立，park 中呼叫腿超时释放 | 通过 HA 方案（主备/集群）保障。故障期间已 bridge 的通话可继续（FS 媒体层独立），但无法执行转接等控制操作                                 |
| **FreeSWITCH 在 bridge 后故障**              | 通话中 FS 宕机，RTP 流中断，坐席听到静音或忙音，对话状态不一致              | 终端检测 RTP 超时（默认 30s）后主动挂断重拨；SIP 代理通过 ESL 心跳检测 FS 故障，将该 FS 摘除并尝试在其他 FS 重建媒体路径（需业务层支持） |
| **re-INVITE 超时（Session Timer 刷新失败）** | 会话保活失败，一方认为通话已断，另一方仍保持媒体                            | 依赖 Session Timer 机制，超时方发送 BYE 释放；SIP 代理作为 B2BUA 需在两侧分别处理超时，协调释放整个呼叫                                  |
| **ACK 丢失（200 OK 重传）**                  | 主叫未回 ACK，FS 重传 200 OK，可能导致重复应答或资源悬挂                    | 依赖 SIP T1/T2 重传定时器，FS 在 64×T1（默认 32s）后仍未收到 ACK 则触发 `ACK Timeout` 释放呼叫；SIP 代理应正确转发 ACK，不吞没           |
| **CPS（每秒呼叫数）过载**                    | 高并发下 SIP 代理 CPU/内存过载，呼叫处理延迟增大甚至崩溃                    | 代理层实现 CPS 限流（令牌桶/漏桶），超过阈值时返回 `503 Service Unavailable` + `Retry-After`；坐席客户端指数退避重试                     |

> **Timer B 可配置性**：文档中 Timer B 默认 32 秒（RFC 3261），实际部署中应对不同网关支持独立配置——部分运营商网关要求更短超时（如
> 15 秒），国际长途可能需要更长（如 60 秒）。SIP 代理应支持按网关 ID 维度配置 Timer B。

### 14.7 网关 ID 覆盖能力

网关 ID 作为 IVR 转接节点的网关覆盖项。该能力由 `FlowTransferHandler` 和 `FlowCallOutRouteHandler` 实现。

**覆盖优先级（高到低）**：

| 优先级  | 网关 ID 来源                                              | 说明                                                                                                                                                                     |
|---------|-----------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| 1（高） | `CallInfo.gatewayId`                                      | 来自 INVITE 头 `X-Gateway-Id`（由 SIP 代理层 `WsInviteRequestHandler` / `SipInviteRequestHandler` 提取并存入 `SessionInfo` / `CallInfo`），业务侧显式指定，覆盖 IVR 配置 |
| 2（中） | `FlowTransferNodeProperties.routeValue`（routeType=2 时） | 来自 IVR 流程配置，作为兜底网关 ID                                                                                                                                       |
| 3（低） | 当前连接的 FS（CHANNEL\_PARK 事件来源 FS 的 `address`）   | 上述两者都为空时，使用当前正在处理该呼叫腿的 FS 实例，由其本地 sofia profile external 配置路由出局（不指定具体 gateway）                                                 |

**处理逻辑（`FlowCallOutRouteHandler.handler`）**：

```
IVR 执行到转接节点（routeType=2 外呼）
├── 读取 FlowDataContext / CallInfo 中的 gatewayId
├── 网关 ID 确定优先级:
│   ├── CallInfo.gatewayId 非空 → 使用它（忽略 properties.routeValue）
│   ├── CallInfo.gatewayId 为空且 properties.routeValue 非空 → 使用 properties.routeValue
│   └── 两者都为空 → 使用当前连接的 FS（FlowDataContext 中的 address）作为出局目标
├── 通过网关 ID 查询 FsSipGatewayDO 配置（若使用具体网关 ID）
├── 调用 fsClient.makeCall 发起出局呼叫:
│   ├── 使用具体网关 ID → 通过该网关出局
│   └── 网关 ID 为空 → 调用 fsClient.makeCall 时传入 null 网关参数，由 FS 本地 profile 处理出局
└── 网关 ID 无效兜底（FsSipGatewayDO 不存在）:
    ├── 回退到使用 IVR 转接节点配置的 routeValue
    ├── 若 routeValue 也无效 → 使用当前连接的 FS 兜底
    └── 记录告警日志提示 "网关 ID 无效"
```

**关键约束**：

- 网关 ID 必须指向第三方出局网关（`FsSipGatewayDO`）， **不能设置为内部 FS 地址**，否则会导致 INVITE 回环死循环（详见 3.4
  节告警说明）
- 系统应在网关配置与 IVR 转接节点配置时进行校验，拒绝将内部 FS 地址配置为网关 ID
- 网关 ID 覆盖逻辑仅在 IVR 转接节点 routeType=2（外呼）时生效；routeType=1（转坐席）时不涉及网关 ID

### 14.8 SIP 代理层豁免场景识别（关键代码点）

`SipInviteRequestHandler.handleIncomingRequest` 中识别"FS 源 + 携带 X-Gateway-Id"的组合，直接走
`forwardToOutboundGateway`：

```java
// SipInviteRequestHandler.java L82-99
String callType;
if (SipProxyConstants.FREESWITCH.equals(source) && StrUtil.isNotBlank(gatewayId)) {
    // FS c-leg 携带 X-Gateway-Id → OUTBOUND（响应需回送 FS）
    callType = SipProxyConstants.CALL_TYPE_OUTBOUND;
} else if (SipProxyConstants.FREESWITCH.equals(source)) {
    // FS 内部回环（如 转接 内部转接）→ INTERNAL
    callType = SipProxyConstants.CALL_TYPE_INTERNAL;
} else {
    // THIRD_PARTY 或 WEBSOCKET → 兜底 INTERNAL
    callType = SipProxyConstants.CALL_TYPE_INTERNAL;
}

// SipInviteRequestHandler.java L125-130（豁免分支）
if (SipProxyConstants.FREESWITCH.equals(source) && StrUtil.isNotBlank(gatewayId)) {
    log.info("[handleIncomingRequest][检测到FS c-leg携带X-Gateway-Id,直接出局]...");
    messageForwarder.forwardToOutboundGateway(request, gatewayId);
    return;
}

// 其他场景: forwardToFreeSwitch(request, freeSwitchNode);
messageForwarder.forwardToFreeSwitch(request, freeSwitchNode);
```

***

## 十五、遗留问题与未来演进

本方案当前实现已覆盖 7 个核心场景的"号码分析驱动路由 + 网关 ID 覆盖"设计。经全面排查，仍存在以下遗留问题（按优先级排序）：

### 15.1 高优先级遗留问题（影响核心功能或生产稳定性）

<br />

### 15.2 中优先级遗留问题（影响可维护性或非核心场景）

| #      | 问题                    | 影响模块                   | 修复方向                                                                                                                | 状态     |
|--------|-------------------------|----------------------------|-------------------------------------------------------------------------------------------------------------------------|----------|
| M1     | 第三方节点选择简化      | `SipNodeManager`           | 改为按 INVITE 来源 IP 反查网关节点（`selectThirdPartyNode(callId, sourceIp)`）                                          | 已修复   |
| M3     | PRACK / UPDATE 专门处理 | `SipDefaultRequestHandler` | 改为按 Call-ID 查 SessionInfo + 复用 `ResponseForwardingStrategy` 决策转发目标，SIP 头原样透传（Require/RSeq 自动保留） | 已修复   |
| M-指标 | Micrometer 业务指标     | 全局                       | CPS 限流指标、ESL 重连次数、重连期间丢失事件数等                                                                        | 暂不处理 |

### 15.3 低优先级遗留问题（增强型 / 未来演进）

| #  | 问题                           | 修复方向                                                                                                        |
|----|--------------------------------|-----------------------------------------------------------------------------------------------------------------|
| F1 | 录音转写 + 质检                | 集成 ASR 转写服务（如阿里云语音转写），自动生成通话摘要、关键词命中、坐席质检评分                               |
| F2 | 全链路号码路由可视化           | 管理后台展示号码路由表命中链路、IVR 流程执行路径、异常统计                                                      |
| F3 | WebRTC 视频呼叫支持            | 集成 `mod_av` 视频编解码、坐席视频接入                                                                          |
| F4 | SIP over TCP/TLS 支持          | 第三方网关走 TCP/TLS 时启用，配置证书                                                                           |
| F5 | 多 FreeSWITCH 实例负载均衡优化 | 引入一致性哈希（按 Call-ID）减少单腿切换                                                                        |
| F6 | FS 故障切换已 bridge 通话恢复  | 方案 4.2 节要求业务层支持 ESL originate 重建呼叫腿、媒体路径切换，复杂度极高，当前阶段 FS 自身 RTP 超时检测兜底 |
| F7 | Session Timer B2BUA 两侧维护   | 方案 17.1 节要求 B2BUA 两侧分别维护 re-INVITE 刷新调度，复杂度极高，当前阶段 FS `session-timeout-sec` 配置兜底  |

***

## 十六、端到端信令路径汇总表

| 场景                                              | 号码路由处理                                         | 信令路径                                                                                                          | 媒体路径                 |
|---------------------------------------------------|------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------|--------------------------|
| **场景一**：坐席A → 坐席B（内部坐席间呼叫）       | 走号码路由                                           | A→代理→FS(park)→ESL 号码路由匹配→IVR→转接节点(routeType=1)→ESL originate→FS→代理→B                                | A↔FS↔B（经 FS 中继）     |
| **场景一**：坐席A → 非坐席号码（IVR 子流程）      | 走号码路由                                           | A→代理→FS(park)→ESL 号码路由匹配→IVR→转接节点→ESL originate→FS→代理→目标                                          | A↔FS↔目标（经 FS 中继）  |
| **场景二**：坐席A → 手机（携带 X-Gateway-Id=gw3） | 走号码路由（IVR 转接节点用 CallInfo.gatewayId 覆盖） | A→代理→FS(park)→ESL 号码路由匹配→IVR→转接节点(routeType=2,用 gw3 覆盖)→ESL originate→FS→代理→第三方网关→PSTN→手机 | A↔FS(转码)↔网关↔手机     |
| **场景二**：坐席A → 手机（未携带 X-Gateway-Id）   | 走号码路由（IVR 转接节点用 routeValue 兜底）         | A→代理→FS(park)→ESL 号码路由匹配→IVR→转接节点(routeType=2)→ESL originate→FS→代理→第三方网关→PSTN→手机             | A↔FS(转码)↔网关↔手机     |
| **场景三**：手机 → 坐席A（入局）                  | 走号码路由（type=1 呼入）                            | 手机→PSTN→第三方网关→代理→FS(park)→ESL 号码路由匹配(呼入)→IVR→ESL originate→FS→代理→A                             | 手机↔网关↔FS(转码)↔A     |
| **场景四**：三方会议（A+B+外部手机）              | **豁免号码路由**                                     | A、B→代理→FS(conf) + ESL originate(携 gw3)→FS→代理→第三方网关→手机                                                | 三方→FS 会议桥混合       |
| **场景五**：手机A → 手机B（双向出局转接）         | **豁免号码路由**                                     | ESL originate(携 gw1)→FS→代理→网关→手机A + ESL originate(携 gw3)→FS→代理→网关→手机B + uuid\_bridge                | 手机A↔网关↔FS↔网关↔手机B |
| **场景六**：坐席间转接到外部手机（转接 携 gw3）   | **豁免号码路由**（折中方案）                         | A-B 通话中→转接(gw3)→ESL originate(携 gw3)→FS→代理→网关→手机 + uuid\_bridge(B↔手机)                               | B↔FS(转码)↔网关↔手机     |
| **场景六**：坐席间转接到外部手机（转接 未携 gw3） | 走号码路由                                           | A-B 通话中→转接→ESL 号码路由匹配→IVR→转接节点(routeType=2)→ESL originate→FS→代理→网关→手机 + uuid\_bridge(B↔手机) | B↔FS(转码)↔网关↔手机     |
| **场景七**：机器人自动外呼（指定 ivr\_flow）      | **跳过号码路由**（ivr\_flow 显式指定优先）           | 外呼任务(内部方法)→ESL originate→FS(sofia/external)→网关→手机(接通)→ESL IVR(可转人工坐席)                         | 手机↔网关↔FS(IVR 媒体)   |
| **场景七**：机器人自动外呼（未指定 ivr\_flow）    | 走号码路由（兜底）                                   | 外呼任务(内部方法)→ESL originate→FS(sofia/external)→网关→手机(接通)→ESL 号码路由匹配→IVR(可转人工坐席)            | 手机↔网关↔FS(IVR 媒体)   |

***

## 十七、生产环境必需的 SIP 补充机制

上述场景描述了核心呼叫流程。在生产环境中，以下 SIP 标准机制对于保障通话可靠性至关重要，需在 SIP 代理服务和 FreeSWITCH
中配置启用：

### 17.1 Session Timer（会话定时器，RFC 4028）

**目的**：防止"僵尸通话"——通话一方网络异常断开后，另一方的会话永远挂起不释放。

**机制**：在 INVITE/200 OK 中协商 `Session-Expires`，周期性发送 re-INVITE 或 UPDATE 刷新会话。若刷新超时，主动释放呼叫。

```
Session Timer 协商示例:
INVITE sip:B@domain SIP/2.0
  Session-Expires: 1200;refresher=uac     ← 会话最长 1200 秒，主叫侧刷新
  Min-SE: 90                               ← 最小刷新间隔 90 秒

200 OK:
  Session-Expires: 1200;refresher=uac     ← 被叫接受参数
```

**配置要点**：

| 组件           | 配置                                                                                         |
|----------------|----------------------------------------------------------------------------------------------|
| **FreeSWITCH** | sofia profile 启用 `enable-timer`，设置 `session-timeout-sec`（如 1200 秒）                  |
| **SIP 代理**   | 作为 B2BUA，需在两段对话中分别维护 Session Timer，分别向坐席和 FS/网关方向发送刷新 re-INVITE |
| **最小 SE**    | 建议不低于 90 秒，避免频繁刷新影响性能                                                       |

> **B2BUA 下的 Session Timer**：由于 SIP 代理是 B2BUA，两段对话的 Session Timer 独立维护。代理需分别向坐席侧和 FS 侧发送
> re-INVITE 刷新，任一侧超时则通过 ESL 释放整个呼叫。

### 17.2 PRACK / 100rel（可靠临时响应，RFC 3262）

**目的**：确保携带 SDP 的 183 临时响应可靠传输。在标准 SIP 中，1xx 临时响应不触发重传，若 183 携带了 SDP answer
但丢失，会导致媒体路径建立失败。

**机制**：183 响应中携带 `Require: 100rel`，要求主叫方回送 PRACK 确认。PRACK 本身也可携带 SDP，实现早期媒体阶段的可靠协商。

```
PRACK/100rel 协商示例:
INVITE sip:B@domain SIP/2.0
  Supported: 100rel                         ← 声明支持 100rel

183 Session Progress:
  Require: 100rel                           ← 要求对 183 进行确认
  RSeq: 1

PRACK sip:B@domain SIP/2.0
  RAck: 1 183 INVITE                        ← 确认 183
```

**配置要点**：

| 组件           | 配置                                                                                      |
|----------------|-------------------------------------------------------------------------------------------|
| **FreeSWITCH** | sofia profile 启用 `enable-100rel`，设置 `inbound-no-media` 等参数                        |
| **SIP 代理**   | 透传 `Require: 100rel` / `RSeq` / `RAck` 头域；不吞没 PRACK 请求                          |
| **JSSIP**      | 默认支持 100rel（`sessionDescriptionHandler` 配置 `extraHeaders: ['Supported: 100rel']`） |

> **遗留优化点**：当前 `WsDefaultRequestHandler` 不区分方法类型，对所有未注册的 SIP 方法做相同处理（仅转发到 FS），可能吞没
> PRACK 的 `RSeq` / `RAck` 头域。详见十五、M3。

### 17.3 GRUU（Globally Routable User Agent URI，RFC 5627）

**目的**：在多设备注册场景下，精确路由到特定设备实例。当一个坐席账号同时登录 Web 端和移动端时，普通 AOR（如 `sip:A@domain`
）无法区分应路由到哪个设备。

**机制**：REGISTER 时携带 `+sip.instance` 参数（设备唯一标识），注册服务器返回 GRUU（如 `sip:A@domain;gr=urn:uuid:xxx`），后续
INVITE 可使用 GRUU 精确路由。

```
REGISTER 流程（携带实例 ID）:
REGISTER sip:domain SIP/2.0
  Contact: <sip:A@10.0.0.5:5060>;+sip.instance="<urn:uuid:00000000-0000-1000-8000-000A95A0E128>"
  Supported: gruu

200 OK:
  Contact: <sip:A@10.0.0.5:5060>;+sip.instance="<urn:uuid:...>";pub-gruu="sip:A@domain;gr=urn:uuid:..."
```

**配置要点**：

| 组件         | 配置                                                                                                              |
|--------------|-------------------------------------------------------------------------------------------------------------------|
| **SIP 代理** | 注册服务器需支持 GRUU 生成与存储，在注册表中维护 AOR→GRUU 映射                                                    |
| **JSSIP**    | REGISTER 时携带 `+sip.instance`，启用 GRUU 支持                                                                   |
| **路由逻辑** | 呼叫时若 INVITE 的 Request-URI 包含 `gr` 参数，精确路由到对应设备实例；否则按 AOR 多设备策略（最后注册/并行振铃） |

> **遗留优化点**：当前 `WsRegisterRequestHandler` 注册成功后仅调用 `sessionManager.cacheRegisterInfo` 缓存 registerInfo 到
> SessionManager，无 `saveLocationInfo` 方法，未实现 GRUU。详见十五、L2。

### 17.4 ICE 协商（Interactive Connectivity Establishment）

**目的**：JSSIP 使用 WebRTC，客户端可能位于 NAT/防火墙后，需通过 ICE 收集候选地址（主机候选、STUN 候选、TURN 中继候选），确保媒体可达。

**机制**：SDP 中携带多个 ICE 候选地址，双方通过 STUN 绑定检测连通性，选择最优路径。FreeSWITCH 作为媒体锚点需正确处理 ICE
候选替换。

```
ICE 候选地址类型:
├── host 候选：本机 IP 地址（仅同一局域网可达）
├── srflx 候选：STUN 反射地址（NAT 公网映射地址）
└── relay 候选：TURN 中继地址（通过 TURN 服务器中继，兜底方案）
```

**配置要点**：

| 组件           | 配置                                                                                      |
|----------------|-------------------------------------------------------------------------------------------|
| **FreeSWITCH** | sofia profile 启用 `rtp-ip`、`ext-rtp-ip`（NAT 环境公网地址），支持 ICE（`ice-`相关参数） |
| **JSSIP**      | 配置 STUN/TURN 服务器，收集 ICE 候选                                                      |
| **SIP 代理**   | 不参与 ICE 协商，但需确保 SDP 透传完整（ICE 候选在 SDP 的 `a=candidate` 行中）            |

> **WebRTC 与 FS 的 ICE 交互**：当 FS 收到 WebRTC 客户端的 INVITE（SDP 含 ICE 候选），FS 作为 ICE Lite
> 端（仅响应连接检查，不主动发起），选择可达的候选地址建立 DTLS-SRTP 媒体路径。

### 17.5 各机制在生产环境中的重要性

| 机制              | 重要性                | 不启用的风险                                      |
|-------------------|-----------------------|---------------------------------------------------|
| **Session Timer** | **高**                | 网络中断后产生僵尸通话，媒体资源泄漏，FS 端口耗尽 |
| **PRACK/100rel**  | **中**                | 183 携带 SDP 丢失时早期媒体不可靠，可能导致单通   |
| **GRUU**          | **中**                | 多设备登录时路由不精确，呼叫可能振到错误设备      |
| **ICE**           | **高**（WebRTC 必需） | NAT 环境下 WebRTC 媒体不可达，通话无声            |

***

## 附录 A：号码路由表配置规范

所有呼叫（含内部坐席间呼叫）必须经过号码路由表的正则匹配 → IVR 流程。号码路由表（`CallRouteDO`
）成为路由决策核心，其配置完整性直接决定系统是否能正常处理呼叫。

### A.1 配置强制性要求

| 要求项                     | 说明                                                                                                              |
|----------------------------|-------------------------------------------------------------------------------------------------------------------|
| **必须配置至少一条规则**   | 号码路由表为空时，所有呼叫（包括内部坐席间呼叫）都会因匹配失败被挂断                                              |
| **必须配置默认兜底规则**   | 推荐配置 `.*` 匹配所有号码指向默认 IVR 流程，避免未匹配到规则的呼叫被挂断                                         |
| **必须配置坐席分机号规则** | 内部坐席间呼叫要求号码路由表配置坐席分机号正则规则，指向包含转坐席节点（routeType=1）的 IVR 流程                  |
| **必须配置 DID 号码规则**  | 入局呼叫要求号码路由表配置 DID 号码正则规则（type=1 呼入），指向对应业务 IVR 流程                                 |
| **必须配置外部手机号规则** | 出局到外部手机要求号码路由表配置外部手机号正则规则（type=2 呼出），指向包含外呼转接节点（routeType=2）的 IVR 流程 |
| **条目数建议 < 1000 条**   | 当前实现先按 status + type 过滤候选列表，再对候选列表做正则匹配，条目数过多时正则匹配性能下降                     |

### A.2 推荐配置示例

| 号码类型                | 正则规则        | type | level | flowId         | IVR 流程说明                                                                                     |
|-------------------------|-----------------|------|-------|----------------|--------------------------------------------------------------------------------------------------|
| 默认兜底                | `.*`            | 2    | 1     | flow\_default  | 默认 IVR 流程（包含一个外呼转接节点，routeValue 留空依赖 CallInfo.gatewayId 覆盖或当前 FS 兜底） |
| 坐席分机号（1000-1999） | `^1\d{3}$`      | 2    | 10    | flow\_agent    | 坐席间呼叫 IVR 流程（包含转坐席节点 routeType=1，routeValue 为目标坐席 ID）                      |
| 外部手机号              | `^1[3-9]\d{9}$` | 2    | 10    | flow\_outbound | 外呼 IVR 流程（包含外呼转接节点 routeType=2，routeValue 可留空）                                 |
| 入局 DID 号码           | `^010\d{8}$`    | 1    | 10    | flow\_inbound  | 入局 IVR 流程（播放欢迎语、收 DTMF、转人工坐席）                                                 |

### A.3 兜底规则建议

**默认兜底规则** **`.*`** **配置示例**：

- **正则**：`.*`（匹配所有号码）
- **type**：建议同时配置 type=1（呼入）和 type=2（呼出）两条兜底规则
- **level**：设置为最低（如 1），确保只有当其他更具体的规则都不匹配时才使用兜底规则
- **flowId**：指向默认 IVR 流程，该 IVR 流程应包含一个外呼转接节点（routeType=2，routeValue 留空），依赖 `CallInfo.gatewayId`
  覆盖或当前 FS 兜底

**坐席分机号配置示例** **`^1\d{3}$`**：

- **正则**：`^1\d{3}$`（匹配 1000-1999 分机号段）
- **type**：2（呼出）
- **level**：设置为较高（如 10），确保优先于兜底规则匹配
- **flowId**：指向包含转坐席节点（routeType=1）的 IVR 流程
- **IVR 转接节点配置**：routeType=1，routeValue=目标坐席 ID（由 IVR 流程动态确定，或使用变量占位符）

### A.4 号码路由匹配流程

```
ESL 处理器收到 CHANNEL_PARK 事件
├── 读取被叫号码 callee + 方向 direction（1-呼入/2-呼出）
├── 调用 CallRouteService.getListByRouteNumberAndType(callee, direction):
│   ├── 按 status=启用 + type=direction 过滤候选列表
│   ├── 对候选列表按 routeNum 正则匹配 callee
│   ├── 取 level 最高的匹配路由条目（level 越大优先级越高）
│   └── 返回匹配的 CallRouteDO（含 flowId）
├── 匹配成功 → 用 flowId 驱动 IVR 流程
└── 匹配失败（无任何正则匹配）:
    ├── 挂断呼叫
    ├── 播放失败提示音（或返回 503 Service Unavailable）
    ├── 生成失败话单
    └── 记录告警日志提示运维人员补充号码路由规则
```

### A.5 多租户隔离策略

号码路由已实现租户隔离。`FsCallIRouteProcess` 从 `CallInfo.tenantId` 读取租户 ID，通过
`FsCallCacheServiceImpl.getCallRoute(routeNum, type, tenantId)` 查询路由规则：

- **tenantId 非空**（呼出场景）：通过 `TenantUtils.execute(tenantId, ...)` 设置租户上下文，调用
  `callRouteService.getListByRouteNumberAndType`（受 MyBatis-Plus 租户插件自动隔离），确保 A 租户的呼叫不会匹配到 B 租户的路由规则
- **tenantId 为空**（呼入场景，路由反查前）：回退到 `getCallRouteNoTenant`（无租户隔离查询），并打印 `log.warn` 告警，保证呼入主流程不受影响

### A.6 号码路由匹配失败的处理策略

| 失败场景                                   | 处理策略                                                                         |
|--------------------------------------------|----------------------------------------------------------------------------------|
| 号码路由表为空（无任何规则）               | 挂断呼叫，播放"系统配置错误"提示音，记录告警"号码路由表未配置任何规则"           |
| 号码路由表有规则但无任何正则匹配到被叫号码 | 挂断呼叫，播放失败提示音，记录告警"号码 \[被叫号] 未匹配到路由规则"              |
| 匹配到路由但 flowId 为空（IVR 流程未配置） | 挂断呼叫，播放"系统配置错误"提示音，记录告警"号码路由 \[routeId] 的 flowId 为空" |
| 匹配到路由但 IVR 流程不存在（flowId 无效） | 挂断呼叫，播放"系统配置错误"提示音，记录告警"IVR 流程 \[flowId] 不存在"          |

### A.7 配置清单

系统部署时，运维侧需确认以下号码路由表已配置：

- [ ] 坐席分机号段（如 `^1\d{3}$`）→ 坐席间呼叫 IVR（含 routeType=1 转坐席节点）
- [ ] 外部手机号段（如 `^1[3-9]\d{9}$`）→ 外呼 IVR（含 routeType=2 外呼转接节点）
- [ ] 全部 DID 号码（如 `^010\d{8}$`、`^021\d{8}$`）→ 入局 IVR
- [ ] 默认兜底规则 `.*`（type=1 呼入）→ 入局默认 IVR
- [ ] 默认兜底规则 `.*`（type=2 呼出）→ 出局默认 IVR
- [ ] 400/800 客服热线（按运营商约定）
- [ ] 国际长途（按需）
- [ ] 紧急号码 110/120/119（按需）

***

**文档完成时间**：2026-07-22 **对应代码版本**：yudao-cloud-cc main 分支（v3.0） **维护人**：cc 模块开发组 **反馈渠道**：项目
AGENTS.md / 团队 Wiki
