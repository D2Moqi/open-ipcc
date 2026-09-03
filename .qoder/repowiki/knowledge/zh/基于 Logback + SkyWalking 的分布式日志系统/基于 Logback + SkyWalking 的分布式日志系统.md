---
kind: logging_system
name: 基于 Logback + SkyWalking 的分布式日志系统
category: logging_system
scope:
    - '**'
source_files:
    - yudao-cloud/yudao-server/src/main/resources/logback-spring.xml
    - yudao-cloud/yudao-gateway/src/main/resources/logback-spring.xml
    - yudao-cloud/yudao-module-ai/yudao-module-ai-server/src/main/resources/logback-spring.xml
    - yudao-cloud/yudao-server/src/main/resources/application-local.yaml
    - yudao-cloud/yudao-server/src/main/resources/application-prod.yaml
    - yudao-cloud/yudao-dependencies/pom.xml
    - yudao-cloud/yudao-framework/yudao-spring-boot-starter-monitor/pom.xml
---

## 1. 使用的框架与工具

项目采用 **Logback** 作为统一的日志实现，通过 SLF4J API（`org.slf4j:slf4j-api`
）进行调用。每个独立服务模块（yudao-server、yudao-gateway、yudao-module-ai-server 等）均自带独立的 `logback-spring.xml`
配置文件，遵循 yudao-cloud 脚手架的统一规范。

依赖方面，`yudao-dependencies` 和 `yudao-spring-boot-starter-monitor` 中引入了 `apm-toolkit-logback-1.x`，为接入
SkyWalking 链路追踪预留了扩展点；AI 模块还额外引入 `slf4j-reload4j`、`log4j-slf4j-impl`、`slf4j-simple` 以解决第三方库日志冲突。

## 2. 核心文件与位置

- 各服务日志配置：
    - `yudao-server/src/main/resources/logback-spring.xml`
    - `yudao-gateway/src/main/resources/logback-spring.xml`
    - `yudao-module-ai/yudao-module-ai-server/src/main/resources/logback-spring.xml`
- 运行时日志输出目录：`logs/`（根目录及 `yudao-server/logs/`），按 `yudao-server.log`、`yudao-server.log.2026-08-18.0.log`
  形式滚动归档。
- 日志级别与文件路径由 Spring Boot 配置驱动：
    - `application-local.yaml` / `application-prod.yaml` 中的 `logging.file.name: ./logs/${spring.application.name}.log`
      指定日志文件。
    - `logging.level.*` 针对各模块包名设置细粒度级别（如 `cn.iocoder.yudao.module.cc: debug`、
      `cn.iocoder.yudao.module.ai.dal.mysql: debug` 等）。

## 3. 架构与约定

### 3.1 Appender 结构（每个服务一致）

| Appender     | 作用                     | 关键参数                                                                        |
|--------------|--------------------------|---------------------------------------------------------------------------------|
| `STDOUT`     | 控制台输出，带 ANSI 高亮 | `PatternLayoutEncoder` + `CONSOLE_LOG_PATTERN`                                  |
| `FILE`       | 同步文件输出             | `RollingFileAppender` + `SizeAndTimeBasedRollingPolicy`                         |
| `ASYNC`      | 异步包装 FILE，提升吞吐  | `AsyncAppender`，`queueSize=512`，`discardingThreshold=0`（不丢弃任何级别日志） |
| `SKYWALKING` | 预留 GRPC 日志上报       | `GRPCLogClientAppender` + `TraceIdPatternLogbackLayout`，默认注释未启用         |

### 3.2 日志格式

- 控制台：`%d{yyyy-MM-dd HH:mm:ss.SSS} [%thread] %highlight(%-5level) %cyan(%logger{50}:%L) - %msg%n`
- 文件：同格式但去掉高亮颜色。
- Gateway/AI 模块在控制台格式中额外包含 `[TID:%X{tid:-N/A}]` 字段，用于 SkyWalking 链路 ID 透传；server 模块当前未包含 tid
  字段。

### 3.3 滚动策略

- 使用 `SizeAndTimeBasedRollingPolicy`：按天切割 + 单文件超过 `10MB` 时按序号滚动（`.log.2026-08-18.0.log`）。
- 保留最近 `maxHistory=30` 天的历史文件。

### 3.4 代码层日志注入

业务代码统一通过 Lombok 注解 `@Slf4j` 注入 `Logger`，并在框架通用组件（`ServiceExceptionUtil`、`JsonUtils`、`AreaUtils`、
`IPUtils`、`TenantJobAspect` 等）中以 `log.error(...)`、`log.info(...)` 记录异常与启动耗时等信息。

### 3.5 多环境日志级别控制

通过 `application-{profile}.yaml` 的 `logging.level.*` 对各个模块的 Mapper、DAL 包单独设置为 `debug`，便于排查 SQL；同时把
`ApiErrorLogMapper`、`JobLogMapper`、`SmsChannelMapper` 等重复打印场景调整为 `INFO`，避免与全局异常处理器重复输出。

## 4. 约定与约束

- **每个可运行服务必须提供自己的 `logback-spring.xml`**：gateway、server、ai-server 均各自维护一份，未共用父 POM 中的公共配置。
- **日志文件路径统一通过 `${LOG_FILE}` 变量 + `logging.file.name` 配置**：实际落盘路径形如 `./logs/yudao-server.log`
  ，滚动后生成 `./logs/yudao-server.log.{date}.{index}.log`。
- **禁止丢弃日志**：`AsyncAppender` 的 `discardingThreshold` 显式设为 `0`，确保队列满时也不丢弃 DEBUG/INFO 日志。
- **SkyWalking 集成为可选扩展**：`SKYWALKING` appender 在默认配置中被注释，需手动取消注释并引入对应依赖才能开启 GRPC 日志上报。
- **日志级别分层**：root 级别为 `INFO`；具体模块（尤其是 cc、bpm、infra、pay、system、ai 等 DAL 层）在 profile 配置中按需调至
  `DEBUG`，生产建议保持 INFO。
- **线程上下文追踪**：Gateway 与 AI 模块在日志格式中预留 `%X{tid}` 字段，配合 SkyWalking APM 实现跨服务链路追踪；新增服务如需链路追踪应沿用该模式。
- **第三方日志冲突处理**：AI 模块通过排除 `slf4j-reload4j`、`log4j-slf4j-impl`、`slf4j-simple` 等方式避免与主工程的 Logback
  产生冲突，新引入的第三方库若自带日志实现时需做同样处理。