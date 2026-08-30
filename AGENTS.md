# AGENTS.md

This file provides guidance to Lingma (lingma.aliyun.com) when working with code in this repository.

## 仓库概览

本工作区是基于 yudao-cloud 二次开发的**呼叫中心系统**，由三个独立 Git 仓库（git submodule）组成，各自独立提交与分支：

| 目录 | 说明 | 技术栈 |
|---|---|---|
| `yudao-cloud/` | 后端微服务（含自定义呼叫中心模块 `yudao-module-cc`） | Java 25 + Spring Boot 4.1 + Spring Cloud 2025.1 + Maven 多模块 |
| `yudao-ui-admin-vue3/` | 管理后台前端 | Vue 3.5 + TypeScript 6 + Vite 8 + Element Plus 2.13 + pnpm |
| `yudao-prd/` | 产品需求文档静态站点（纯 HTML，无构建） | Vue 3 CDN + Element Plus |

首次拉取需执行 `git submodule update --init --recursive`。子模块内已有更详细的 AGENTS.md，进入对应目录工作前先阅读：`yudao-prd/AGENTS.md`、`yudao-cloud/yudao-module-cc/ipcc-fs-esl/AGENTS.md`、`yudao-cloud/yudao-module-cc/ipcc-sipproxy/AGENTS.md`。

## 常用命令

### 后端（yudao-cloud）

构建环境要求 **JDK 25**（根 pom `java.version=25`、revision `2026.07-jdk25-SNAPSHOT`；JDK 17 无法编译当前分支，旧环境线见 `master-jdk17-cc` 分支）。

```bash
# 全量构建（按依赖顺序 api → fs-esl → sipproxy → server）
cd yudao-cloud && mvn clean install -DskipTests

# 单模块编译（-am 连带依赖模块）
mvn -pl yudao-module-cc/yudao-module-cc-server -am compile

# 运行测试（JUnit 5 + Mockito，surefire 3.5.5）
mvn test
# 单个测试类（在目标模块目录下执行）
cd yudao-module-cc/yudao-module-cc-server && mvn test -Dtest=FlowConditionEvaluatorTest
```

### 前端（yudao-ui-admin-vue3）

```bash
pnpm install          # 依赖安装
pnpm dev              # 本地开发（--mode env.local，默认端口 80，Vite 热更新）
pnpm build:prod       # 生产构建（另有 build:dev / build:test / build:stage / build:local）
pnpm ts:check         # TypeScript 类型检查
pnpm lint             # eslint + stylelint + prettier 检查
```

### PRD（yudao-prd）

无构建工具，浏览器直接打开 `index.html` 即可；禁止引入构建工具。

## 架构速览

### 后端

- `yudao-server` 是聚合启动容器（dev 环境端口 48080，`spring.profiles.active=dev`），业务模块以 Maven 依赖方式聚合。根 pom 当前启用 `system`、`infra`、`ai`、`cc` 四个业务模块，其余（bpm/pay/mall/iot 等）均已注释；`ai` 模块基于 spring-ai 2.0.0 + spring-ai-alibaba 2.0.0-M1.1（DashScope）。
- 关键依赖版本由 `yudao-dependencies` BOM 统一锁定：Spring Boot 4.1.0、Spring Cloud 2025.1.2、Spring Cloud Alibaba 2025.1.0.0、MyBatis Plus 3.5.16（`mybatis-plus-spring-boot4-starter`）、Redisson 4.6.1、Netty 4.2.15、Lombok 1.18.46、MapStruct 1.6.3、fastjson2 2.0.63。
- **Nacos 注册发现与配置中心默认禁用**，配置以本地 YAML 为主：`application.yaml` 放默认值，`application-{env}.yaml` 做环境覆盖；敏感信息用 `${ENV_VAR:default}` 注入。跨服务环境标签（tag）由 `yudao-spring-boot-starter-env` 透传。
- `yudao-module-cc` 是二次开发核心，含四个子模块：
  - `yudao-module-cc-api`：API 契约、常量与枚举
  - `yudao-module-cc-server`：呼叫中心业务（坐席、外呼、IVR、录音、TTS/ASR、WebSocket 总线），独立启动端口 48089
  - `ipcc-fs-esl`：Netty 重写的 FreeSWITCH ESL 客户端组件（传输层，不含业务）
  - `ipcc-sipproxy`：SIP over WebSocket B2BUA 代理组件（13 个扩展点接口与父程序解耦）

### 呼叫链路（需跨多文件理解）

JsSIP 软电话（前端 `src/layout/components/SoftPhone/`）→ 浏览器 WebSocket → `ipcc-sipproxy`（SIP 信令代理，B2BUA）→ FreeSWITCH（媒体与拨号）→ `ipcc-fs-esl`（事件监听与命令下发）→ `cc-server` 业务编排（呼叫路由、IVR 流程、坐席分配）。sipproxy **不直连 ESL、不做呼叫决策**，REFER 转接等 ESL 编排场景通过 `SipMessageInterceptor` 扩展点委托 cc-server 实现。

### IVR 流程引擎

`cc-server` 的 `ivr/` 包实现状态机驱动的 IVR 流程引擎：`handler/node/` 下每个节点类型一个处理器（start / condition / playback / receive / transfer / end / hangup / satisfaction / method），节点间通过 `dto/` 流转输出值，流程状态持久化到 Redis（`config/` + `properties/`）。

### 前端

- 核心依赖版本：Vue 3.5.34、TypeScript 6.0.3、Element Plus 2.13.7、pinia 3.0.4、vue-router 5.0.6、axios 1.16.0、echarts 6.0.0、unocss 66.6.8、JsSIP 3.13.6；Node ≥ 20.19、pnpm ≥ 8.6。
- 菜单为**动态路由**（菜单由后端权限接口下发），页面在 `src/views/`，API 封装在 `src/api/`；CC 相关页面集中在 `src/views/cc/` 与 `src/api/cc/`（ivr、sysagent、autocalltask、callrecord、sipproxygateway 等）。
- 环境配置通过 `.env` + `.env.{mode}` 注入：`.env.local` 指向 `http://localhost:48080`；生产环境 `VITE_BASE_URL` 指向 `https://cc.wenmoqi.top`，WebSocket 走 `wss://cc.wenmoqi.top/cc/ws` 与 `/sipproxy/ws`（nginx WSS 代理）。只有 `VITE_` 前缀的变量会被 Vite 注入浏览器。

## 关键约束与陷阱

- **软电话心跳**：sipproxy WebSocket 空闲超时 `sipproxy.heartbeat.idle-timeout=90s`，JsSIP 客户端 OPTIONS 心跳间隔必须小于该值（`SoftPhone.vue` 中 `KEEP_ALIVE_INTERVAL=30s`）。修改任一侧需联动验证，否则坐席注册后会被僵尸会话清理，导致来话失败。
- **fs-esl 约束**：仅支持 Inbound 模式；事件订阅与命令必须异步（Netty IO 线程内阻塞 `.get()` 会死锁）；API 命令必须带 `api ` 前缀，bgapi 是平级独立命令。
- **WebSocket sender-type 一致性**：`cc.websocket.sender-type` 必须与 `yudao.websocket.sender-type` 一致，否则分布式环境下 CC 消息无法跨节点投递。
- **编译要求（JDK 25）**：根 pom 已配置 Lombok + MapStruct 注解处理器、`-parameters` 编译参数与显式 `<proc>full</proc>`（JDK 22+ 默认禁用 classpath 隐式注解处理，独立 POM 模块升级 JDK 时最容易踩 Lombok 找不到符号的坑，需同步补 annotationProcessorPaths）；JAIN-SIP 版本必须统一为 1.2.1.4，避免跨版本 AbstractMethodError。
- **Spring Boot 4 约束**：`spring.autoconfigure.exclude` 配置在 `application.yaml`（含 `spring.profiles.active` 的文档）中不生效，必须放在 `application-{profile}.yaml`；spring-ai-alibaba 2.0.0-M1.1 的 `AutoConfiguration.imports` 注册了 JAR 中不存在的类（如 DashScopeMultimodalEmbeddingAutoConfiguration），需在 profile 配置中排除，遇 "Unable to read meta-data for class X" 先用 `unzip -l` 核对类是否真实存在。
- **提交注意**：三个子仓库各自独立提交推送，需在对应目录内执行 git 操作；`yudao-cloud` 双分支并行维护（当前工作线 `master-jdk25-cc`，旧环境线 `master-jdk17-cc`），提交前确认分支与推送目标一致。

## 开发与验证

- IDE 需安装 Multi-Project Workspace 插件以同时打开前后端；项目加载异常时删除 `.idea` 下除 `jb-workspace.xml` 外的文件后重开。
- 需求实现后必须启动本地服务验证：前端页面通过浏览器真实操作验证，接口/命令真实运行验证；发现问题立即修复并重新验证。本地调试优先使用 ij-debugger 技能获取运行时证据（变量值、调用栈、线程状态），技能失效时降级原生能力。
- 新增/修改代码时同步维护注释：方法级用语言标准文档注释（含功能、入参、返回、异常），业务逻辑标注需求背景、预期结果、核心处理逻辑。

# 通用ai开发规则

## 始终使用中文回答。

## 代码注释约束规则
**核心原则**：注释解释设计意图、业务背景、边界约束，不复述代码字面逻辑；代码新增/修改时，对应注释必须同步更新，保持一致。
**强制注释场景**
- 方法级：所有自定义方法生成对应语言标准文档注释；公开方法需包含功能、入参约束、返回规则、异常场景、前置条件
- 业务逻辑：标注需求背景、预期结果、核心处理逻辑、异常分支的业务含义
- 复杂逻辑：算法、并发、状态流转、多层循环，说明设计思路、执行流程、边界条件
- 数据计算：标注字段映射、公式来源、精度舍入规则、异常值处理策略
- 特殊项：魔数、容错降级、第三方依赖/兼容逻辑，说明取值依据与约束
  **豁免范围**
- Java DO/VO/DTO等纯数据载体类（仅字段+get/set），无特殊业务约束时无需类定义注释
- 命名完全自解释的单行极简方法、命名清晰的测试用例，可简化行内注释
  **质量要求**：禁止复述代码的无效注释；关键逻辑块统一注释，避免逐行冗余；表述精准，使用通用术语
  **语言规范**：遵循对应语言官方注释标准（JavaDoc、JSDoc、GoDoc 等）

## 本地服务启动，运行，调试，编译
- 启动服务，编译、代码运行、服务重启、调试排查优先调用 ij-debugger 技能
- ij-debugger 技能，可获取变量值、方法调用栈、线程状态、异常信息等调试数据，用于程序验证与调试
- 技能无法生效时，降级使用原生能力兜底

## 数据库 SQL 执行
- 优先检测匹配的数据库类 MCP（如 MySQL MCP,ij-debugger），自动调用执行 SQL 操作
- 无适配 MCP 时，降级使用原生能力执行

## 需求实现强制规范
- 先完整分析并理解需求，主动补全遗漏的边界条件、异常场景与隐含逻辑；涉及路由需同步补充权限、传参与兜底规则，涉及命令需补充参数校验与错误处理规范。
- 需求实现后必须启动本地服务充分验证全场景功能：前端页面必须通过浏览器真实操作验证，接口 / 命令必须真实运行验证，路由变更必须验证跳转与权限。
- 验证出现问题立即修复，修复后重新完整验证，直至全部验证通过。

## 非qoder编程工具需主动检索根目录.qoder/repowiki下的知识库文件。