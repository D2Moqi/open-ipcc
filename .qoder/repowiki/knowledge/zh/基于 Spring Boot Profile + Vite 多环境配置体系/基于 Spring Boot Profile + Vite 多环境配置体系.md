---
kind: configuration_system
name: 基于 Spring Boot Profile + Vite 多环境配置体系
category: configuration_system
scope:
    - '**'
source_files:
    - yudao-cloud/yudao-server/src/main/resources/application.yaml
    - yudao-cloud/yudao-server/src/main/resources/application-dev.yaml
    - yudao-cloud/yudao-framework/yudao-spring-boot-starter-env/src/main/java/cn/iocoder/yudao/framework/env/config/EnvEnvironmentPostProcessor.java
    - yudao-cloud/yudao-framework/yudao-spring-boot-starter-env/src/main/java/cn/iocoder/yudao/framework/env/config/EnvProperties.java
    - yudao-cloud/yudao-framework/yudao-spring-boot-starter-env/src/main/java/cn/iocoder/yudao/framework/env/core/util/EnvUtils.java
    - yudao-ui-admin-vue3/.env
    - yudao-ui-admin-vue3/.env.dev
    - yudao-ui-admin-vue3/vite.config.ts
    - yudao-ui-admin-vue3/src/config/axios/config.ts
---

## 1. 整体方案

本仓库采用 **Spring Boot 原生 Profile + YAML 分段** 的后端配置体系，配合 **Vite 多 `.env` 文件** 的前端配置体系；并通过框架自研的 `yudao-spring-boot-starter-env` 在启动早期注入环境变量与环境标签（tag），实现跨服务/网关的环境识别与透传。后端默认禁用 Nacos 配置中心与注册发现，以本地 YAML 为主。

## 2. 关键文件与位置

- 后端主应用入口与公共配置：
  - `yudao-cloud/yudao-server/src/main/resources/application.yaml`（全局默认配置、AI/租户/短信/消息队列等）
  - `yudao-cloud/yudao-server/src/main/resources/application-dev.yaml`（开发环境覆盖：端口、数据源、Redis、日志级别、微信/JustAuth、CC/SIPProxy 等）
  - `yudao-cloud/yudao-server/src/main/resources/application-local.yaml`（本地环境覆盖，未展开）
  - `yudao-cloud/yudao-server/src/main/resources/logback-spring.xml`
- 环境 starter（框架层）：
  - `yudao-cloud/yudao-framework/yudao-spring-boot-starter-env/src/main/java/cn/iocoder/yudao/framework/env/config/EnvEnvironmentPostProcessor.java`（`EnvironmentPostProcessor`，启动最早阶段注入 `${HOSTNAME}` 兜底、将 `yudao.env.tag` 写入 Nacos metadata tag）
  - `.../config/EnvProperties.java`（`@ConfigurationProperties(prefix = "yudao.env")`，定义 `tag`）
  - `.../core/util/EnvUtils.java`（从请求头/ServiceInstance/Environment 读取 tag，并支持 `${HOSTNAME}` 解析）
  - `.../core/web/EnvWebFilter.java`、`.../core/fegin/EnvRequestInterceptor.java`、`.../core/fegin/EnvLoadBalancerClient*.java`（请求入参透 tag、Feign 调用带 tag、负载均衡按 tag 选择实例）
- CC 模块相关配置段（集中在 `application-dev.yaml` 末尾）：
  - `cc.freeswitch.*`（录音路径、编码、线程数、队列容量）
  - `cc.websocket.*`（路径、sender-type、各 MQ 的 topic/group/exchange/queue）
  - `sipproxy.*`（SIP over WebSocket 代理：instance-id、SIP 端口/公网 IP、WS 路径、心跳、集群广播 channel、session TTL 等）
- 前端配置：
  - `yudao-ui-admin-vue3/.env`（通用常量：标题、租户开关、验证码开关、API 加解密密钥、百度地图 Key 等）
  - `yudao-ui-admin-vue3/.env.dev`（开发环境：`VITE_BASE_URL`、`VITE_API_URL=/admin-api`、是否删除 debugger/console、sourcemap、压缩策略、GoView 域名等）
  - `yudao-ui-admin-vue3/vite.config.ts`（通过 `loadEnv(mode, root)` 加载对应 `.env.*`，暴露 `VITE_*` 给 `import.meta.env`）
  - `yudao-ui-admin-vue3/src/config/axios/config.ts`（组合 `VITE_BASE_URL + VITE_API_URL` 作为 API 基础路径）

## 3. 架构与约定

### 3.1 后端配置分层

| 层级 | 文件/方式 | 作用 |
|---|---|---|
| 默认值 | `application.yaml` | 所有环境共享的默认配置（Jackson、Flowable、MyBatis-Plus、Redis、XXL-JOB、Kafka/RocketMQ、AI 厂商 key、yudao.tenant/sms/trade/iot、Swagger 等） |
| 环境覆盖 | `application-{profile}.yaml` | 通过 `spring.profiles.active=dev` 激活，覆盖端口、数据源、Redis、日志级别、第三方平台 AppId/Secret、CC/SIPProxy 等运行期差异配置 |
| 运行时变量 | `${OPENAI_API_KEY:sk-xxxx}`、`${spring.application.name}`、`${random.int}`、`${HOSTNAME}` | 敏感信息或机器相关值通过环境变量注入，YAML 中提供默认占位符 |
| 启动期注入 | `EnvEnvironmentPostProcessor` | 在 Spring 容器初始化前设置 `${HOSTNAME}` 兜底，并将 `yudao.env.tag` 同步到 Nacos discovery metadata 的 `tag` 字段，用于后续按环境路由 |

### 3.2 环境标签（tag）机制

- 通过 `yudao.env.tag` 声明当前实例所属环境（如 dev/test/prod）。
- `EnvUtils.getTag(...)` 可从 HTTP 请求头 `tag`、`ServiceInstance.metadata.tag`、Spring `Environment` 中读取；当值为 `${HOSTNAME}` 时自动解析为真实主机名，解决 IDE 调试工具无法解析环境变量问题。
- `EnvWebFilter` 把 tag 注入请求上下文，`EnvRequestInterceptor` 在 Feign 出站请求带上 `tag` 头，`EnvLoadBalancerClient` 根据 tag 选择目标实例，从而实现“同环境内调用”。

### 3.3 CC / SIPProxy 配置约定

- CC 业务配置统一放在 `cc.*` 命名空间下：`freeswitch` 控制 FreeSWITCH ESL 连接参数（录音目录、采样率、codec、线程池、队列容量、分组），`websocket` 控制 CC 专用 WS 路径及消息总线类型（local/redis/rocketmq/kafka/rabbitmq）。
- SIPProxy 组件配置放在 `sipproxy.*` 命名空间：`instance-id` 使用 `${HOSTNAME:node1}` 默认 node1；`sip.public-ip/public-port` 用于改写 Contact/Via 头使外部能回信；`cluster.sender-type` 决定广播通道（单实例用 local，集群用 Redis channel `ipcc:sipproxy:ws:broadcast`）；`session.redis-key-prefix`、`session-ttl`、`register-ttl` 管理会话状态。

### 3.4 前端配置约定

- 所有可编译进浏览器的配置均以 `VITE_` 前缀的 `.env` 变量形式存在，由 `vite.config.ts` 通过 `loadEnv(mode, root)` 加载，再通过 `import.meta.env.VITE_*` 在源码中使用。
- 典型约定：
  - `VITE_BASE_URL` + `VITE_API_URL` → Axios 基础 URL（见 `src/config/axios/config.ts`）
  - `VITE_APP_TENANT_ENABLE`、`VITE_APP_CAPTCHA_ENABLE` → 功能开关
  - `VITE_APP_API_ENCRYPT_*` → 前后端一致的 API 请求/响应 AES 加解密密钥
  - `VITE_DEV`、`VITE_SOURCEMAP`、`VITE_DROP_DEBUGGER`、`VITE_COMPRESS` → 构建期行为开关
- 不同环境通过 `.env`、`.env.dev`、`.env.prod`、`.env.stage`、`.env.test` 等文件切换。

## 4. 约束与规范

1. **Profile 激活**：默认通过 `application.yaml` 中的 `spring.profiles.active=dev` 指定，新增环境需新增 `application-{env}.yaml` 并在部署时切换 active。
2. **敏感信息不入库**：AI 厂商 key、数据库密码、Redis 密码、微信/JustAuth secret 等均通过 `${ENV_VAR:default}` 形式注入，禁止硬编码进仓库（仅保留示例默认值）。
3. **环境标签一致性**：跨服务调用必须通过 `EnvRequestInterceptor` 传递 `tag`，下游通过 `EnvUtils.getTag()` 获取，保证同环境内 RPC 路由。
4. **Nacos 配置中心默认关闭**：`application.yaml` 显式 `spring.cloud.nacos.config.enabled=false`，本项目以本地 YAML 为主，如需接入配置中心需在部署侧开启。
5. **CC/SIPProxy 配置集中化**：所有与呼叫中心相关的运行时参数（FreeSWITCH、WebSocket、SIPProxy、集群广播、会话 TTL）均集中在 `application-dev.yaml` 的 `cc.*` 与 `sipproxy.*` 段，避免散落各处。
6. **前端环境变量必须以 `VITE_` 开头**：只有 `VITE_*` 会被 Vite 注入到浏览器，其他 `.env` 变量不会生效。
7. **日志级别按包名精细控制**：`application-dev.yaml` 中 `logging.level.cn.iocoder.yudao.module.*` 针对各模块 Mapper 单独设为 debug，便于定位 SQL 问题。
8. **CC 模块的 WebSocket sender-type 必须与后端 `yudao.websocket.sender-type` 保持一致**：否则分布式环境下 CC 消息无法跨节点投递。

## 5. 适用性说明

该配置体系贯穿 yudao-server 单体聚合应用、yudao-module-cc（含 ipcc-fs-esl、ipcc-sipproxy）、以及 yudao-ui-admin-vue3 前端工程，是本项目运行期可观测、可切换、可编排的核心基础设施。