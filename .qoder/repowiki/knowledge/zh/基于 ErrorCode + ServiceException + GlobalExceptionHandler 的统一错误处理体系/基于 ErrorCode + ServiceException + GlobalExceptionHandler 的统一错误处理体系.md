---
kind: error_handling
name: 基于 ErrorCode + ServiceException + GlobalExceptionHandler 的统一错误处理体系
category: error_handling
scope:
    - '**'
source_files:
    - yudao-cloud/yudao-framework/yudao-common/src/main/java/cn/iocoder/yudao/framework/common/exception/ErrorCode.java
    - yudao-cloud/yudao-framework/yudao-common/src/main/java/cn/iocoder/yudao/framework/common/exception/ServiceException.java
    - yudao-cloud/yudao-framework/yudao-common/src/main/java/cn/iocoder/yudao/framework/common/exception/enums/GlobalErrorCodeConstants.java
    - yudao-cloud/yudao-framework/yudao-common/src/main/java/cn/iocoder/yudao/framework/common/exception/enums/ServiceErrorCodeRange.java
    - yudao-cloud/yudao-framework/yudao-common/src/main/java/cn/iocoder/yudao/framework/common/exception/util/ServiceExceptionUtil.java
    - yudao-cloud/yudao-framework/yudao-common/src/main/java/cn/iocoder/yudao/framework/common/pojo/CommonResult.java
    - yudao-cloud/yudao-framework/yudao-spring-boot-starter-web/src/main/java/cn/iocoder/yudao/framework/web/core/handler/GlobalExceptionHandler.java
    - yudao-cloud/yudao-module-cc/yudao-module-cc-api/src/main/java/cn/iocoder/yudao/module/cc/enums/ErrorCodeConstants.java
---

## 1. 系统/方案概述

本项目基于 Yudao Cloud（芋道）框架，采用**「统一错误码对象 + 业务异常类型 + 全局异常处理器 + 统一响应体」**的四层错误处理架构：

- **错误码对象** `ErrorCode`：封装 `code` + `msg`，为未来 i18n 预留扩展点。
- **业务异常** `ServiceException`：继承 `RuntimeException`，携带 `code`、`message`，是业务层抛出的唯一异常类型。
- **全局异常处理器** `GlobalExceptionHandler`：位于 `yudao-spring-boot-starter-web`，通过 `@RestControllerAdvice` 拦截所有 HTTP 请求异常，将各类异常统一转换为 `CommonResult`。
- **统一响应体** `CommonResult<T>`：所有接口返回 `code/msg/data` 三字段结构，提供 `success()` / `error()` / `checkError()` 等便捷方法。

该方案贯穿整个多模块工程（system/infra/cc/bpm/pay 等），CC 模块遵循同一约定。网关层（Spring Cloud Gateway）也复用此模型进行统一鉴权与异常转发。

## 2. 关键文件与包

| 层级 | 路径 | 职责 |
|---|---|---|
| 错误码定义 | `yudao-framework/yudao-common/.../exception/enums/GlobalErrorCodeConstants.java` | 全局错误码（0~999），覆盖 400/401/403/404/405/423/429/500/501/502/900/901/999 |
| 错误码区间规划 | `yudao-framework/yudao-common/.../exception/enums/ServiceErrorCodeRange.java` | 声明各模块 10 位业务错误码段（如 infra/system/report/member/mp/pay/bpm/product/trade/promotion/crm/ai 等） |
| 错误码对象 | `yudao-framework/yudao-common/.../exception/ErrorCode.java` | `code` + `msg` 不可变对象 |
| 业务异常 | `yudao-framework/yudao-common/.../exception/ServiceException.java` | 业务逻辑异常基类 |
| 工具类 | `yudao-framework/yudao-common/.../exception/util/ServiceExceptionUtil.java` | 格式化 `{}` 占位符消息并构造 `ServiceException` |
| 统一响应 | `yudao-framework/yudao-common/.../pojo/CommonResult.java` | 统一 JSON 响应体，含 `checkError()` 自动抛异常 |
| 全局异常处理 | `yudao-framework/yudao-spring-boot-starter-web/.../core/handler/GlobalExceptionHandler.java` | 拦截参数校验、权限、404/405、`ServiceException`、数据库表不存在等异常 |
| CC 模块错误码 | `yudao-module-cc/yudao-module-cc-api/src/main/java/cn/iocoder/yudao/module/cc/enums/ErrorCodeConstants.java` | 使用 `1-060-xxx-xxx` 段定义 CC 专属业务错误码（区号、号码池、IVR、FS ACL、SIP 代理等） |

## 3. 架构与约定

### 3.1 错误码编码规则
- **全局错误码**：0~999，由 `GlobalErrorCodeConstants` 集中管理，映射 HTTP 语义（400/401/403/404/405/423/429/500/501/502）及自定义（900 重复请求、901 演示模式、999 未知）。
- **业务错误码**：10 位整数，格式 `1-XXX-YYY-ZZZ`，第一段固定 `1` 表示业务级异常，第二段按模块划分（CC 使用 `060`），第三段按子域，第四段自增。`ServiceErrorCodeRange` 仅做区间声明，不强制校验。
- CC 模块在 `ErrorCodeConstants` 中集中定义全部业务错误码，例如 `CALL_RECORD_NOT_EXISTS=1_060_004_000`、`FS_ACL_NAME_DUPLICATE=1_060_012_004`、`SIP_PROXY_GATEWAY_ADDR_CONFLICT=1_060_031_001` 等。

### 3.2 异常抛出与传播
- 业务层**只抛 `ServiceException`**，通过 `ServiceExceptionUtil.exception(ErrorCode, ...)` 或 `new ServiceException(code, msg)` 构造，支持 `{}` 占位符的参数化消息。
- 跨服务 RPC 调用返回 `CommonResult`，调用方通过 `result.checkError()` 或 `result.getCheckedData()` 在失败时转为 `ServiceException` 向上抛出，实现错误从 API 层向 Service 层单向传播。
- 框架层（Web Starter）的 `GlobalExceptionHandler` 捕获所有异常，将 `ServiceException` 直接映射为 `CommonResult.error(code, msg)`；其他 Spring MVC 异常（参数缺失、类型不匹配、校验失败、404/405、权限不足、上传过大等）均映射到对应全局错误码。

### 3.3 兜底与特殊处理
- `defaultExceptionHandler` 作为最终兜底，记录错误日志并通过 `ApiErrorLogCommonApi.createApiErrorLogAsync` 异步写入错误日志表，返回 `INTERNAL_SERVER_ERROR`。
- 针对数据库表未导入场景，`handleTableNotExists` 根据异常消息中的表名前缀（`report_`、`bpm_`、`mp_`、`product_`、`erp_`、`wms_`、`crm_`、`mes_`、`im_`、`pay_`、`ai_`、`iot_`）返回带引导信息的 `NOT_IMPLEMENTED` 结果。
- `IGNORE_ERROR_MESSAGES` 白名单（如“无效的刷新令牌”）避免对高频预期内异常打印堆栈。

### 3.4 前端侧配合
- 前端统一通过 Axios 拦截器判断 `CommonResult.code === 0` 视为成功，否则弹出提示或直接跳转登录页。这与后端 `GlobalErrorCodeConstants.SUCCESS = 0` 约定一致。

## 4. 约定与约束

| 规则 | 说明 | 依据 |
|---|---|---|
| 业务异常必须使用 `ServiceException` | 禁止在业务层直接抛 `RuntimeException` 或自定义异常，确保被 `GlobalExceptionHandler` 统一处理 | `GlobalExceptionHandler.serviceExceptionHandler` 仅处理 `ServiceException` |
| 错误码必须来自常量枚举 | 禁止硬编码数字错误码，新增错误需先在 `GlobalErrorCodeConstants` 或模块 `ErrorCodeConstants` 中声明 | `GlobalErrorCodeConstants`、`ServiceErrorCodeRange` 的注释与结构 |
| 错误码区间按模块隔离 | 每个模块占用独立 10 位区间，避免冲突；CC 使用 `1-060-*-*` | `ServiceErrorCodeRange` 注释 + CC `ErrorCodeConstants` 实际使用 |
| 参数校验失败统一走 BAD_REQUEST | 所有 `@Valid`、`@NotNull` 等校验失败经 `MethodArgumentNotValidException`/`BindException`/`ConstraintViolationException` 转为 `BAD_REQUEST` | `GlobalExceptionHandler` 多个 `@ExceptionHandler` |
| 404/405/401/403 等 HTTP 语义错误使用全局错误码 | 路由不存在、方法不支持、未登录、无权限分别映射到 `NOT_FOUND`/`METHOD_NOT_ALLOWED`/`UNAUTHORIZED`/`FORBIDDEN` | `GlobalErrorCodeConstants` + `GlobalExceptionHandler` |
| 未知异常落库并返回 500 | 兜底处理器记录完整堆栈、请求参数、TraceId 到错误日志表，对外返回 `INTERNAL_SERVER_ERROR` | `defaultExceptionHandler` + `createExceptionLog` |
| 跨服务调用失败显式检查 | 通过 `CommonResult.checkError()` 将下游错误转为 `ServiceException` 继续上抛 | `CommonResult.checkError()` 实现 |

## 5. CC 模块实践

CC 模块严格遵循上述约定：
- 在 `ErrorCodeConstants` 中集中定义电话区号、号码池、呼叫记录、IVR 流程、FreeSWITCH ACL/CDR/拨号计划、SIP 代理网关等业务错误码。
- 业务代码通过 `throw new ServiceException(ErrorCodeConstants.XXX_NOT_EXISTS)` 或 `ServiceExceptionUtil.exception(...)` 抛出。
- 无需在 CC 模块内编写自己的 `@RestControllerAdvice`，直接复用 Web Starter 的全局异常处理。

该设计使错误处理集中在框架层，业务模块只需关注错误码定义与异常抛出，极大降低了重复实现成本并保证了全仓库一致的 API 错误响应格式。