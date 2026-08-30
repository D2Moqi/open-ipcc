---
kind: logging_system
name: 基于 Logback + SLF4J 的日志体系：文件滚动、异步写入与结构化错误日志
category: logging_system
scope:
    - '**'
source_files:
    - yudao-cloud/yudao-server/src/main/resources/logback-spring.xml
    - yudao-cloud/yudao-module-cc/yudao-module-cc-server/src/main/resources/logback-spring.xml
    - yudao-cloud/yudao-module-cc/yudao-module-cc-server/src/main/resources/application.yaml
    - yudao-cloud/yudao-framework/yudao-spring-boot-starter-web/src/main/java/cn/iocoder/yudao/framework/web/core/handler/GlobalExceptionHandler.java
    - yudao-cloud/yudao-framework/yudao-common/src/main/java/cn/iocoder/yudao/framework/common/biz/infra/logger/ApiAccessLogCommonApi.java
    - yudao-cloud/yudao-framework/yudao-common/src/main/java/cn/iocoder/yudao/framework/common/biz/infra/logger/dto/ApiErrorLogCreateReqDTO.java
---

## 1. 使用的框架与工具
- 日志实现：**Logback**（`ch.qos.logback.core.*`），通过 `logback-spring.xml` 显式配置。
- 日志门面：**SLF4J**，业务代码通过 Lombok `@Slf4j` 注入 `org.slf4j.Logger`。
- 链路追踪集成：预留 **SkyWalking GRPC 日志收集 Appender**（已注释），用于接入集中式日志中心。
- 运行期日志输出：根级别为 `INFO`，同时输出到控制台（`STDOUT`）和异步文件（`ASYNC -> FILE`）。

## 2. 核心配置文件与位置
- 单体服务入口：`yudao-cloud/yudao-server/src/main/resources/logback-spring.xml`
- CC 服务：`yudao-cloud/yudao-module-cc/yudao-module-cc-server/src/main/resources/logback-spring.xml`
- 日志路径由 Spring Boot 属性控制：`logging.file.name=${user.home}/logs/${spring.application.name}.log`（CC 服务在 `application.yaml` 中定义）
- 实际日志文件位于仓库根目录 `logs/`，按 `yudao-server.log.2026-08-03.N.log` 形式滚动归档。

## 3. 架构与约定
### 3.1 输出格式
- 控制台模式带 ANSI 高亮：`%d{yyyy-MM-dd HH:mm:ss.SSS} [%thread] %highlight(%-5level) %cyan(%logger{50}:%L) - %msg%n`
- 文件模式无高亮：`%d{yyyy-MM-dd HH:mm:ss.SSS} [%thread] %-5level %logger{50}:%L - %msg%n`
- 统一包含时间、线程名、级别、类名:行号、消息。

### 3.2 滚动策略
- 使用 `SizeAndTimeBasedRollingPolicy`：按天切割 + 单文件最大 10MB 滚动。
- 保留最近 30 天历史文件。
- 文件名模板：`${LOG_FILE}.%d{yyyy-MM-dd}.%i.log`，与 `logs/` 下大量 `yudao-server.log.2026-08-03.N.log` 完全对应。

### 3.3 异步写入
- 通过 `AsyncAppender` 包装 `FILE` Appender，队列深度默认 512，`discardingThreshold=0` 表示不丢弃任何级别日志（包括 DEBUG/INFO）。

### 3.4 SkyWalking 集成点
- 预留 `SKYWALKING` Appender，使用 `TraceIdPatternLogbackLayout` 输出 `[tid]` 前缀；当前注释未启用，需取消注释并引入依赖后生效。

## 4. 结构化日志与业务日志
项目将“系统运行日志”和“业务访问/错误日志”分离：
- 系统运行日志：通过 SLF4J 直接输出到 Logback 文件/控制台，遵循上述格式。
- API 访问日志 / 错误日志：通过 `ApiAccessLogCommonApi`、`ApiErrorLogCommonApi` Feign 接口异步写入 Infra 模块数据库，属于结构化持久化日志，而非 Logback 文件。
- 全局异常处理集中在 `GlobalExceptionHandler`：参数校验、权限拒绝、ServiceException、表不存在等异常均记录 `warn`/`error` 级别日志，并通过 `createExceptionLog` 调用 `apiErrorLogApi.createApiErrorLogAsync` 持久化错误日志。
- 错误日志结构字段包括：`userId`、`userType`、`exceptionName`、`exceptionMessage`、`exceptionStackTrace`、`traceId`、`applicationName`、`requestUrl`、`requestParams`、`requestMethod`、`userAgent`、`userIp`、`exceptionTime`。

## 5. 约定与约束
- 所有服务模块（server、cc-server）各自维护独立的 `logback-spring.xml`，保持相同输出格式与滚动策略，便于独立部署与运维。
- 日志文件路径通过 `${LOG_FILE}` 变量与 `logging.file.name` 解耦，支持不同环境覆盖。
- 生产环境建议保持 `root level=INFO`；如需调试可调整具体包级别。
- 业务代码统一使用 Lombok `@Slf4j` 获取 logger，避免手写 Logger 实例。
- 对高频或可忽略的业务异常（如 `ServiceException`）仅打印第一层堆栈并使用 `warn`，避免日志风暴。
- 表结构缺失等基础设施问题通过 `handleTableNotExists` 识别并输出明确提示日志，辅助快速定位未导入的模块 SQL。

## 6. 关键文件清单
- `yudao-cloud/yudao-server/src/main/resources/logback-spring.xml`
- `yudao-cloud/yudao-module-cc/yudao-module-cc-server/src/main/resources/logback-spring.xml`
- `yudao-cloud/yudao-module-cc/yudao-module-cc-server/src/main/resources/application.yaml`（含 `logging.file.name`）
- `yudao-cloud/yudao-framework/yudao-spring-boot-starter-web/src/main/java/cn/iocoder/yudao/framework/web/core/handler/GlobalExceptionHandler.java`
- `yudao-cloud/yudao-framework/yudao-common/src/main/java/cn/iocoder/yudao/framework/common/biz/infra/logger/ApiAccessLogCommonApi.java`
- `yudao-cloud/yudao-framework/yudao-common/src/main/java/cn/iocoder/yudao/framework/common/biz/infra/logger/dto/ApiErrorLogCreateReqDTO.java`
- 根目录 `logs/yudao-server.log*`（运行时生成的滚动日志文件）
