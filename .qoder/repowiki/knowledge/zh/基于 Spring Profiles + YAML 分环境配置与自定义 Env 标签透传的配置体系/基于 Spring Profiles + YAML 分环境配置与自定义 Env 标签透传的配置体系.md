---
kind: configuration_system
name: 基于 Spring Profiles + YAML 分环境配置与自定义 Env 标签透传的配置体系
category: configuration_system
scope:
    - '**'
source_files:
    - yudao-cloud/yudao-server/src/main/resources/application.yaml
    - yudao-cloud/yudao-server/src/main/resources/application-dev.yaml
    - yudao-cloud/yudao-server/src/main/resources/application-prod.yaml
    - yudao-cloud/yudao-framework/yudao-spring-boot-starter-env/src/main/java/cn/iocoder/yudao/framework/env/config/EnvProperties.java
    - yudao-cloud/yudao-framework/yudao-spring-boot-starter-env/src/main/java/cn/iocoder/yudao/framework/env/core/context/EnvContextHolder.java
    - yudao-cloud/yudao-framework/yudao-spring-boot-starter-env/src/main/java/cn/iocoder/yudao/framework/env/core/util/EnvUtils.java
    - yudao-cloud/yudao-framework/yudao-spring-boot-starter-env/src/main/java/cn/iocoder/yudao/framework/env/core/web/EnvWebFilter.java
    - yudao-cloud/yudao-framework/yudao-spring-boot-starter-env/src/main/java/cn/iocoder/yudao/framework/env/core/fegin/EnvRequestInterceptor.java
    - yudao-cloud/yudao-framework/yudao-spring-boot-starter-env/src/main/java/cn/iocoder/yudao/framework/env/core/fegin/EnvLoadBalancerClient.java
    - yudao-cloud/yudao-framework/yudao-spring-boot-starter-security/src/main/java/cn/iocoder/yudao/framework/security/config/SecurityProperties.java
    - yudao-cloud/yudao-framework/yudao-spring-boot-starter-websocket/src/main/java/cn/iocoder/yudao/framework/websocket/config/WebSocketProperties.java
    - yudao-cloud/yudao-framework/yudao-spring-boot-starter-biz-tenant/src/main/java/cn/iocoder/yudao/framework/tenant/config/TenantProperties.java
---

## 1. 系统/方案概述

本项目采用 **Spring Boot 原生配置体系**，以 `application.yaml` + `application-{profile}.yaml` 多文件分环境覆盖的方式组织配置；通过
`spring.profiles.active=local|dev|prod` 切换运行环境。框架层额外提供 `yudao-spring-boot-starter-env`，在 Spring
配置之上封装了“环境标签（tag）”的跨请求、跨服务透传能力，用于在多实例/多租户部署中区分流量来源。

项目未启用 Nacos Config / Bootstrap 模式：`application.yaml` 中显式关闭 `spring.cloud.nacos.config.enabled=false`
，所有配置均通过本地 YAML 文件加载，不依赖外部配置中心。

## 2. 关键文件与包

- 应用入口配置
    - `yudao-cloud/yudao-server/src/main/resources/application.yaml`
      ：全局默认配置（数据库、Redis、AI、WebSocket、Swagger、XSS、安全、多租户等），并声明 `spring.profiles.active: local`。
    - `yudao-cloud/yudao-server/src/main/resources/application-dev.yaml`：开发环境覆盖（端口、数据源、Redis、MQ、日志级别、微信公众号/小程序密钥、pf4j
      插件目录、cc/sipproxy/ipcc-fs-esl 业务配置）。
    - `yudao-cloud/yudao-server/src/main/resources/application-prod.yaml`：生产环境覆盖（远程 MySQL/Redis、不同日志级别、不同
      wx/mp/miniapp 密钥、sipproxy cluster 广播 channel、session TTL 等）。
    - `yudao-cloud/yudao-server/src/main/resources/logback-spring.xml`：日志输出策略。

- 环境标签（Env）starter
    -
    `yudao-framework/yudao-spring-boot-starter-env/src/main/java/cn/iocoder/yudao/framework/env/config/EnvProperties.java`：
    `@ConfigurationProperties(prefix = "yudao.env")`，定义 `tag` 字段及常量 `TAG_KEY = "yudao.env.tag"`。
    - `.../core/context/EnvContextHolder.java`：基于 `TransmittableThreadLocal<List<String>>` 维护每线程的环境标签栈，支持嵌套
      set/remove。
    - `.../core/util/EnvUtils.java`：从 `HttpServletRequest.getHeader("tag")`、`ServiceInstance.getMetadata()`、
      `Environment.getProperty("yudao.env.tag")` 读取 tag，并支持特殊值 `${HOSTNAME}` 解析为本机主机名。
    - `.../core/web/EnvWebFilter.java`：`OncePerRequestFilter`，将请求头 `tag` 写入 `EnvContextHolder`，并在 finally 中清理。
    - `.../core/fegin/EnvRequestInterceptor.java`：Feign `RequestInterceptor`，把当前线程中的 tag 注入到下游 Feign 请求
      header 中，实现跨微服务透传。
    - `.../core/fegin/EnvLoadBalancerClient.java` / `EnvLoadBalancerClientFactory.java`：按 tag 选择目标
      ServiceInstance（配合注册中心元数据）。

- 各模块的 `@ConfigurationProperties` 绑定类（统一以 `yudao.*`、`xxl.job.*`、`spring.ai.*`、`wx.*`、`cc.*`、`ipcc.*`、
  `sipproxy.*` 等前缀暴露可配置项）：
    - `TenantProperties` (`yudao.tenant`)、`SecurityProperties` (`yudao.security`)、`ApiEncryptProperties`
      (`yudao.api-encrypt`)、`SwaggerProperties` (`yudao.swagger`)、`WebSocketProperties` (`yudao.websocket`)、
      `TracerProperties` (`yudao.tracer`)、`XxlJobProperties` (`xxl.job`)、`YudaoCacheProperties` (`yudao.cache`)、
      `WebProperties` (`yudao.web`)、`XssProperties` (`yudao.xss`) 等。

## 3. 架构与设计约定

### 3.1 配置文件分层

- `application.yaml` 存放 **所有环境的公共默认值**，包括 `spring.application.name`、
  `spring.main.allow-circular-references`、MyBatis Plus、Easy Trans、XXL-Job、Kafka/RocketMQ、Spring AI、yudao 系列开关等。
- `application-{env}.yaml` 仅做 **差异化覆盖**：如 dev/prod 的数据源地址、密码、Redis 库号、日志级别、第三方密钥、cc/sipproxy/ipcc-fs-esl
  的业务参数。
- 通过 `spring.profiles.active` 指定激活 profile；未显式 include 其他 profile，因此每个 YAML 文件独立生效。

### 3.2 配置绑定方式

- 框架 starter 统一使用 `@ConfigurationProperties(prefix = "...")` 将 YAML 节点绑定到 Java Bean，再由 AutoConfiguration
  装配。
- 业务代码中少量直接使用 `@Value("${...}")` 读取简单开关或路径（如 `cc.ai.system-user-id:1`、
  `spring.ai.mcp.server.sse-endpoint:/sse`、`yudao.captcha.enable:true`），通常带默认值，避免启动失败。
- AI 相关密钥（OpenAI、Anthropic、DashScope、DeepSeek、Gemini、Doubao、Hunyuan 等）通过 `${ENV_VAR:default}` 形式注入，便于容器化时以环境变量覆盖。

### 3.3 环境标签（tag）透传机制
- 入口：HTTP 请求携带 `tag` 请求头 → `EnvWebFilter` 提取并压入 `EnvContextHolder`。
- 上下文：`EnvContextHolder` 用 `TransmittableThreadLocal` 维护 tag 栈，保证异步/线程池场景下正确传递。
- 透传：Feign 调用时 `EnvRequestInterceptor` 自动把 tag 放入下游请求 header；负载均衡器可通过 `EnvLoadBalancerClient` 按
  tag 路由到对应实例。
- 读取：任意位置通过 `EnvUtils.getTag(HttpServletRequest|ServiceInstance|Environment)` 获取当前 tag，支持特殊值
  `${HOSTNAME}` 解析为真实主机名，解决 IDE 调试工具无法读取环境变量的问题。

### 3.4 多数据源与多 MQ
- 通过 `spring.datasource.dynamic` 配置 master/slave 双数据源，dev/prod 分别覆盖 URL、用户名、密码。
- RocketMQ、RabbitMQ、Kafka 三套 MQ 同时声明，各 profile 只覆盖实际使用的 broker 地址，运行时由上层逻辑决定走哪条通道。

## 4. 约定与约束

- **禁止硬编码连接信息**：数据库、Redis、MQ、微信/小程序密钥、AI API Key 等敏感配置必须放在 `application-{profile}.yaml` 或通过
  `${ENV_VAR}` 注入，不得写死在源码中。
- **新增配置项应遵循命名空间约定**：框架级配置统一以 `yudao.*` 为前缀（如 `yudao.tenant`、`yudao.security`、
  `yudao.websocket`、`yudao.swagger`、`yudao.api-encrypt`、`yudao.xss`、`yudao.info`），第三方组件使用其标准前缀（`xxl.job`、
  `spring.ai`、`wx`、`justauth`、`lock4j`、`logging`、`management` 等），业务专属配置使用 `cc.*`、`ipcc.*`、`sipproxy.*`。
- **多环境差异必须通过 profile 文件覆盖**，不要在 `application.yaml` 中写死环境相关值；新增 profile 需保持文件名
  `application-{name}.yaml` 且结构与其他 profile 一致。
- **敏感密钥优先使用环境变量占位符**：如 `${OPENAI_API_KEY:sk-xxxx}`、`${ANTHROPIC_API_KEY:sk-xxxx}`、
  `${DOUBAO_API_KEY:sk-xxxx}` 等，默认值仅作本地开发兜底。
- **环境标签透传是可选增强**：只有当请求携带 `tag` 请求头时才会进入 `EnvContextHolder`，不影响无 tag 的普通请求；但一旦设置，必须在
  Filter 的 finally 块中 `removeTag`，防止线程复用污染后续请求。
- **Nacos 配置中心已禁用**：若未来要接入远程配置中心，需在 `application.yaml` 中重新开启
  `spring.cloud.nacos.config.enabled=true`，并移除本地 profile 覆盖策略。
- **AI 向量存储自动配置按需排除**：dev/prod 中通过 `spring.autoconfigure.exclude` 手动排除 Qdrant/Milvus/Redis
  的自动配置，改为业务代码动态创建，避免多实现注入歧义。

## 5. 适用性说明

该配置体系完整覆盖了本仓库后端服务的配置加载、分环境覆盖、类型安全绑定、敏感信息注入以及跨服务环境标签透传，属于成熟可用的配置系统，适用于
yudao-cloud 及其所有子模块（system、infra、cc、ai、bpm 等）的统一配置管理。