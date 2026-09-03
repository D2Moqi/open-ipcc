---
kind: error_handling
name: 基于 ErrorCode + ServiceException/ServerException + GlobalExceptionHandler 的统一错误处理体系
category: error_handling
scope:
    - '**'
source_files:
    - yudao-cloud/yudao-framework/yudao-common/src/main/java/cn/iocoder/yudao/framework/common/exception/ErrorCode.java
    - yudao-cloud/yudao-framework/yudao-common/src/main/java/cn/iocoder/yudao/framework/common/exception/enums/GlobalErrorCodeConstants.java
    - yudao-cloud/yudao-framework/yudao-common/src/main/java/cn/iocoder/yudao/framework/common/exception/enums/ServiceErrorCodeRange.java
    - yudao-cloud/yudao-framework/yudao-common/src/main/java/cn/iocoder/yudao/framework/common/exception/ServiceException.java
    - yudao-cloud/yudao-framework/yudao-common/src/main/java/cn/iocoder/yudao/framework/common/exception/ServerException.java
    - yudao-cloud/yudao-framework/yudao-common/src/main/java/cn/iocoder/yudao/framework/common/exception/util/ServiceExceptionUtil.java
    - yudao-cloud/yudao-framework/yudao-common/src/main/java/cn/iocoder/yudao/framework/common/pojo/CommonResult.java
    - yudao-cloud/yudao-framework/yudao-spring-boot-starter-web/src/main/java/cn/iocoder/yudao/framework/web/core/handler/GlobalExceptionHandler.java
---

## 1. 系统/方案概述

该仓库（基于 yudao-cloud 多模块微服务脚手架）采用 **统一的错误码 + 业务异常 + 全局异常处理器**的三层架构来处理错误：

- **错误码模型**：`ErrorCode` 对象承载 `code` + `msg`，作为所有错误的统一标识。
- **两类运行时异常**：`ServiceException`（业务逻辑异常，错误码区间见 `ServiceErrorCodeRange`）与 `ServerException`（服务器级异常，使用
  `GlobalErrorCodeConstants`）。两者均继承自 `RuntimeException`，便于在业务层直接抛出而不破坏调用链。
- **全局响应包装**：`CommonResult<T>` 是 Controller 层的统一返回体，提供 `success()` / `error()` / `checkError()`
  等工厂方法，并在失败时可通过 `checkError()` 转换为 `ServiceException`。
- **全局异常处理器**：`GlobalExceptionHandler`（`@RestControllerAdvice` + `@Order(0)`）集中捕获 Spring
  MVC、参数校验、权限、文件上传、404/405、以及未知异常，统一映射为 `CommonResult`，并异步写入错误日志表（通过
  `ApiErrorLogCommonApi`）。

## 2. 关键文件与位置

| 职责                                 | 文件路径                                                                                                                              |
|--------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------|
| 错误码对象                           | `yudao-framework/yudao-common/src/main/java/cn/iocoder/yudao/framework/common/exception/ErrorCode.java`                               |
| 全局错误码常量（0–999）              | `.../exception/enums/GlobalErrorCodeConstants.java`                                                                                   |
| 业务错误码区间规划（10位分段）       | `.../exception/enums/ServiceErrorCodeRange.java`                                                                                      |
| 业务异常                             | `.../exception/ServiceException.java`                                                                                                 |
| 服务器异常                           | `.../exception/ServerException.java`                                                                                                  |
| 异常构造工具（含 `{}` 占位符格式化） | `.../exception/util/ServiceExceptionUtil.java`                                                                                        |
| 统一返回体                           | `.../common/pojo/CommonResult.java`                                                                                                   |
| 全局异常处理器                       | `yudao-framework/yudao-spring-boot-starter-web/src/main/java/cn/iocoder/yudao/framework/web/core/handler/GlobalExceptionHandler.java` |

## 3. 架构与设计约定

### 3.1 错误码分区

- **全局错误码**：`[0, 999]`，由 `GlobalErrorCodeConstants` 定义，包括 `SUCCESS=0`、`BAD_REQUEST=400`、`UNAUTHORIZED=401`、
  `FORBIDDEN=403`、`NOT_FOUND=404`、`METHOD_NOT_ALLOWED=405`、`LOCKED=423`、`TOO_MANY_REQUESTS=429`、
  `INTERNAL_SERVER_ERROR=500`、`NOT_IMPLEMENTED=501`、`ERROR_CONFIGURATION=502`、`REPEATED_REQUESTS=900`、`DEMO_DENY=901`、
  `UNKNOWN=999`。
- **业务错误码**：`[1_000_000_000, +∞)`，按 `ServiceErrorCodeRange` 的 10 位编码规则划分：第 1 位类型（1=业务级别）、第 2–4
  位系统类型（如 001=用户系统、002=商品系统等）、第 5–7 位模块、第 8–10 位错误码。每个模块在自己的区间内自增分配，避免冲突。

### 3.2 异常抛出与传播

- 业务层应通过 `ServiceExceptionUtil.exception(ErrorCode, ...params)` 或
  `ServiceExceptionUtil.invalidParamException(...)` 抛出 `ServiceException`；或直接
  `throw new ServiceException(code, msg)`。
- 跨进程/RPC 场景下，`CommonResult.checkError()` 会在调用方将失败结果转为 `ServiceException`，使异常能沿调用链向上传播。
- `ServerException` 用于表示系统级故障（非业务语义），携带全局错误码。

### 3.3 全局异常到 HTTP 响应的映射

`GlobalExceptionHandler` 对以下异常做了显式映射：

| 异常类型                                                                             | 映射行为                                                                          |
|--------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------|
| `MissingServletRequestParameterException`                                            | `CommonResult.error(BAD_REQUEST, "请求参数缺失:...")`                             |
| `MethodArgumentTypeMismatchException`                                                | `CommonResult.error(BAD_REQUEST, "请求参数类型错误:...")`                         |
| `MethodArgumentNotValidException` / `BindException` / `ConstraintViolationException` | `CommonResult.error(BAD_REQUEST, "请求参数不正确:...")`                           |
| `ValidationException`（Dubbo Consumer 本地校验）                                     | `CommonResult.error(BAD_REQUEST)`                                                 |
| `MaxUploadSizeExceededException`                                                     | `CommonResult.error(BAD_REQUEST, "上传文件过大")`                                 |
| `NoHandlerFoundException` / `NoResourceFoundException`                               | `CommonResult.error(NOT_FOUND, "请求地址不存在:...")`                             |
| `HttpRequestMethodNotSupportedException`                                             | `CommonResult.error(METHOD_NOT_ALLOWED, "请求方法不正确:...")`                    |
| `HttpMediaTypeNotSupportedException`                                                 | `CommonResult.error(BAD_REQUEST, "请求类型不正确:...")`                           |
| `AccessDeniedException`                                                              | `CommonResult.error(FORBIDDEN)`                                                   |
| `UncheckedExecutionException`                                                        | 解包后递归走 `allExceptionHandler`                                                |
| `ServiceException`                                                                   | 记录 warn 日志（首帧堆栈），返回 `CommonResult.error(code, msg)`                  |
| 其他 `Exception`                                                                     | 记录 error 日志，异步写入 `ApiErrorLogCreateReqDTO`，返回 `INTERNAL_SERVER_ERROR` |

此外，`defaultExceptionHandler` 中内置了针对“表结构未导入”的特殊处理：根据根异常消息中的表名前缀（`report_`、`bpm_`、`mp_`、
`product_/promotion_/trade_`、`erp_`、`wms_`、`crm_`、`mes_`、`im_`、`pay_`、`ai_`、`iot_`）返回带模块提示的 `NOT_IMPLEMENTED`
结果。

### 3.4 错误日志

所有兜底异常都会通过 `createExceptionLog` → `buildExceptionLog` 构建 `ApiErrorLogCreateReqDTO`（包含
userId、userType、异常类名、消息、根因、完整 stacktrace、traceId、applicationName、requestUrl、请求参数 JSON、method、UA、IP、时间），再调用
`apiErrorLogApi.createApiErrorLogAsync` 异步落库。即使写日志本身抛异常也会被 try-catch 吞掉，保证主流程不受影响。

## 4. 约定与约束

- **禁止在 Controller 中自行 try-catch 业务异常**：业务异常应抛出 `ServiceException`，由 `GlobalExceptionHandler` 统一收敛为
  `CommonResult`。
- **错误码必须来自常量或已规划的区间**：`GlobalErrorCodeConstants` 管理全局段，`ServiceErrorCodeRange` 声明各模块区间，新增业务错误码需遵守
  10 位分段规则。
- **错误消息支持 `{}` 占位符格式化**：通过 `ServiceExceptionUtil.doFormat` 实现，避免 `String.format` 参数不匹配导致二次异常。
- **成功状态码固定为 0**：注释明确说明“之前一直使用 0 作为成功，就不使用 200 啦”，因此 `CommonResult.isSuccess()` 以
  `code == 0` 判断。
- **全局异常处理器优先级最高**：`@Order(0)` 确保优先于第三方库（如 JimuReport）的默认处理器。
- **部分业务异常消息被忽略日志打印**：`IGNORE_ERROR_MESSAGES` 中包含 `"无效的刷新令牌"`，避免高频刷新的噪声日志。
- **前端交互约定**：`CommonResult` 提供 `checkError()` / `getCheckedData()`，供上层在拿到 `CommonResult`
  后主动检查并转为异常，形成“返回值 + 异常”双通道错误传递模式。

## 5. 适用性说明

该错误处理体系贯穿 `yudao-framework` 公共 starter 与所有业务模块（`yudao-module-*`），并通过 `GlobalExceptionHandler` 在
Web 入口统一收敛，属于本仓库的核心横切关注点之一。