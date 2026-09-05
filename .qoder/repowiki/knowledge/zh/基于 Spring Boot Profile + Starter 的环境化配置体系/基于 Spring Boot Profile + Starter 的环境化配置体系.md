---
kind: configuration_system
name: 基于 Spring Boot Profile + Starter 的环境化配置体系
category: configuration_system
scope:
    - '**'
source_files:
    - yudao-cloud/yudao-server/src/main/resources/application.yaml
    - yudao-cloud/yudao-server/src/main/resources/application-local.yaml
    - yudao-cloud/yudao-server/src/main/resources/application-dev.yaml
    - yudao-cloud/yudao-server/src/main/resources/application-prod.yaml
    - yudao-cloud/yudao-framework/yudao-spring-boot-starter-env/src/main/java/cn/iocoder/yudao/framework/env/config/EnvProperties.java
    - yudao-cloud/yudao-framework/yudao-spring-boot-starter-env/src/main/java/cn/iocoder/yudao/framework/env/config/EnvEnvironmentPostProcessor.java
    - yudao-cloud/yudao-framework/yudao-spring-boot-starter-env/src/main/java/cn/iocoder/yudao/framework/env/config/YudaoEnvRpcAutoConfiguration.java
    - yudao-cloud/yudao-framework/yudao-spring-boot-starter-env/src/main/java/cn/iocoder/yudao/framework/env/config/YudaoEnvWebAutoConfiguration.java
---

## 1. 采用的方案与框架

项目采用 **Spring Boot 原生配置机制**，以 `application.yaml` 为基线、通过 `spring.profiles.active` 叠加多环境 profile（
`local`/`dev`/`prod`），并配合自定义 starter `yudao-spring-boot-starter-env` 实现环境标签（tag）注入、RPC 请求透传和 Web
过滤。所有运行时参数统一通过 YAML 暴露，由框架各模块的 `@ConfigurationProperties` 类绑定到 Java 对象。

## 2. 核心文件与位置

- 应用入口配置：`yudao-cloud/yudao-server/src/main/resources/application.yaml`（默认 active=local，定义全局通用配置如
  MyBatis-Plus、Redis、AI、WebSocket、租户、XSS、Swagger 等）
- 环境覆盖文件：`application-local.yaml`、`application-dev.yaml`、`application-prod.yaml`（分别覆盖
  datasource、Redis、MQ、xxl-job、日志级别、wx 公众号/小程序、cc/sipproxy/ipcc 等运行期差异）
- 环境 starter：`yudao-framework/yudao-spring-boot-starter-env`
    - `EnvProperties.java`：`@ConfigurationProperties(prefix = "yudao.env")`，提供 `tag` 字段及常量
      `TAG_KEY="yudao.env.tag"`
    - `EnvEnvironmentPostProcessor.java`：实现 `EnvironmentPostProcessor`，在 Spring 启动早期把 `yudao.env.tag` 同步写入
      `spring.cloud.nacos.discovery.metadata.tag` 等目标 key；同时兜底 `${HOST_NAME}` 环境变量
    - `YudaoEnvRpcAutoConfiguration.java`：注册 `EnvLoadBalancerClientFactory`、`EnvRequestInterceptor`，使 Feign/RPC 调用携带
      env tag
    - `YudaoEnvWebAutoConfiguration.java`：注册 `EnvWebFilter`，在 Servlet 层注入 env tag

## 3. 架构与约定

### 3.1 分层加载顺序

1. `application.yaml` 作为公共基线，包含所有模块共享配置（MyBatis、Flowable、XXL-Job、Kafka/RocketMQ、AI 厂商密钥占位符等）。
2. 通过 `spring.profiles.active: local` 激活对应 profile 文件，profile 文件中的同名 key 会覆盖 base 配置。
3. 每个业务模块（如 cc、sipproxy、ipcc-fs-esl）在各自 profile 中以独立命名空间（`cc.*`、`sipproxy.*`、`ipcc.fs.esl.*`
   ）声明自身配置，避免污染公共命名空间。

### 3.2 配置绑定方式

- 框架内所有可配置项均通过 `@ConfigurationProperties` 集中声明，例如：
    - `yudao.tenant` → `TenantProperties`
    - `yudao.web` / `yudao.swagger` / `yudao.xss` / `yudao.api-encrypt` / `yudao.websocket` / `yudao.security` /
      `yudao.cache` / `yudao.tracer` / `xxl.job` 等
- 业务模块（如 AI 模块）使用 `@Value("${...}")` 直接读取，但推荐路径仍遵循 `yudao.*` 或模块前缀。

### 3.3 敏感信息与外部化

- API Key / 密码等敏感值统一通过 `${ENV_VAR:default}` 形式注入，如 `OPENAI_API_KEY`、`DASHSCOPE_API_KEY`、
  `ANTHROPIC_API_KEY`、`STABILITYAI_API_KEY`、`DEEPSEEK_API_KEY`、`GEMINI_API_KEY`、`DOUBAO_API_KEY`、`HUNYUAN_API_KEY`、
  `SILICONFLOW_API_KEY`、`XINGHUO_API_KEY`、`BAICHUAN_API_KEY`、`YIYAN_API_KEY`、`ZHIPU_API_KEY`、`MINIMAX_API_KEY`、
  `MOONSHOT_API_KEY`、`STEPFUN_API_KEY`、`GROK_API_KEY`、`MIDJOURNEY_API_KEY`、`WEB_SEARCH_API_KEY` 等。
- 数据库密码、Redis 密码在生产/本地 profile 中明文出现（当前仓库含真实凭据），应通过外部环境变量或配置中心替换。

### 3.4 灰度与特性开关

- `cc.recording.enabled`、`cc.recording.mode`（`shadow`/`replace`）、`cc.audio-fork.*`、`sipproxy.enabled`、`pf4j.pluginsDir`
  等构成录音统一存储演进方案的灰度开关，通过 profile 切换行为而不改代码。
- `yudao.demo`、`yudao.captcha.enable`、`yudao.access-log.enable`、`yudao.ai.*.enable` 等布尔开关控制功能启停。

### 3.5 多数据源与动态配置

- 使用 `dynamic-datasource` 的 `master`/`slave` 双数据源，各 profile 中分别配置 URL、username、password，支持
  MySQL/PostgreSQL/Oracle/SQLServer/DM/Kingbase/OpenGauss 等多种方言（注释中给出示例）。

## 4. 约定与约束

- **Profile 文件必须放在 resources 下且命名为 `application-{profile}.yaml`**，由 `spring.profiles.active` 选择，这是
  Spring Boot 标准约定，本项目严格遵守。
- **所有可配置项必须通过 `@ConfigurationProperties` 暴露**，禁止在业务代码中散落硬编码字符串——该约定由框架 starter 中大量
  Properties 类体现。
- **敏感信息不得硬编码进配置文件**，应通过环境变量 `${VAR}` 注入；AI 厂商密钥已按此约定处理。
- **Nacos 配置中心默认禁用**（`spring.cloud.nacos.config.enabled=false`），如需启用需显式开启，当前部署依赖本地 YAML + 环境变量。
- **`yudao.env.tag` 是环境标识的统一入口**，`EnvEnvironmentPostProcessor` 会在启动时将其自动传播到 Nacos discovery
  metadata 等下游组件，新增目标 key 需在此处扩展。
- **CC/SIPProxy/ESL 等实时通信模块的配置集中在各自命名空间**（`cc.*`、`sipproxy.*`、`ipcc.fs.esl.*`），便于按服务维度隔离变更。
- **日志级别按包名精细控制**（`logging.level.cn.iocoder.yudao.module.*`），生产/开发 profile 中分别设置不同粒度，避免全量
  DEBUG 影响性能。
