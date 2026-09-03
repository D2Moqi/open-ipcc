---
kind: build_system
name: 基于 Maven + Vite 的多模块微服务构建与容器化体系
category: build_system
scope:
    - '**'
source_files:
    - yudao-cloud/pom.xml
    - yudao-cloud/yudao-dependencies/pom.xml
    - yudao-cloud/yudao-server/Dockerfile
    - yudao-cloud/script/docker/docker-compose.yml
    - yudao-cloud/.github/workflows/maven.yml
    - yudao-ui-admin-vue3/package.json
    - yudao-ui-admin-vue3/vite.config.ts
---

## 1. 构建系统总览

本项目采用 **Maven 多模块聚合**（后端）+ **Vite + pnpm**（前端 Vue3）的双栈构建，产物通过 **Docker** 打包镜像，使用
**docker-compose** 编排部署，并通过 GitHub Actions 在 push 到 master 时执行 CI 构建。

- 后端：Spring Boot 4.1.0 / JDK 25，`yudao-cloud` 为聚合 POM，统一管理 `yudao-dependencies` BOM、`yudao-framework`
  starter、各业务模块（system/infra/bpm/pay/mp/ai/cc 等）以及 `yudao-gateway`、`yudao-server`。
- 前端：`yudao-ui-admin-vue3`，基于 Vite 8、Vue 3.5、Element Plus、TypeScript，提供 dev/test/stage/prod 多环境构建脚本。
- 容器化：每个 server 模块根目录自带 `Dockerfile`；`script/docker/docker-compose.yml` 统一编排
  gateway/system/infra/report/bpm/pay/mp 等服务。
- CI：`.github/workflows/maven.yml` 在 Ubuntu 上以 JDK 8/11/17 矩阵执行 `mvn -B package`（跳过测试）。

## 2. 关键文件与位置

| 类别                | 路径                                                                                            | 作用                                                                                              |
|---------------------|-------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------|
| 聚合 POM            | `yudao-cloud/pom.xml`                                                                           | 声明 modules、revision 版本、maven-compiler/surefire/flatten 插件、华为/阿里云镜像                |
| 依赖 BOM            | `yudao-cloud/yudao-dependencies/pom.xml`                                                        | 集中管理 Spring Boot/Cloud/Alibaba、MyBatis-Plus、Redisson、SkyWalking、Flowable 等所有第三方版本 |
| 主应用 Dockerfile   | `yudao-cloud/yudao-server/Dockerfile`                                                           | 基于 `eclipse-temurin:21-jre`，暴露 48080，通过 `JAVA_OPTS`/`ARGS` 注入参数                       |
| 其他服务 Dockerfile | 各 `*-server/Dockerfile`（如 `yudao-module-system`, `yudao-module-bpm`, `yudao-module-pay` 等） | 同构模板，产出对应 `-server.jar`                                                                  |
| 本地编排            | `yudao-cloud/script/docker/docker-compose.yml`                                                  | 定义 gateway/system/infra/report/bpm/pay/mp 等服务，挂载 SkyWalking agent、Nacos 配置、日志卷     |
| CI 流水线           | `yudao-cloud/.github/workflows/maven.yml`                                                       | push master 触发，JDK 8/11/17 矩阵编译                                                            |
| 前端构建            | `yudao-ui-admin-vue3/package.json`、`vite.config.ts`                                            | 提供 `build:dev/test/stage/prod` 等脚本，按 `.env.*` 模式输出到 `dist-*`                          |
| LiveKit POC         | `yudao-cloud/script/livekit-poc/docker-compose.yml`                                             | 独立音视频 POC 的 compose 编排                                                                    |

## 3. 架构与约定

### 3.1 版本管理

- 统一使用 `${revision}` 属性（当前 `2026.07-jdk25-SNAPSHOT`），由 `flatten-maven-plugin` 在 `process-resources` 阶段展开，BOM
  用 `bom` 模式、普通模块用 `oss` 模式生成扁平化 pom。
- 所有子模块不单独声明 `<version>`，继承父 POM 的 `${revision}`。

### 3.2 编译与插件

- `maven-compiler-plugin` 开启 `proc=full` 并显式注册 Lombok + MapStruct 注解处理器，同时添加 `-parameters` 编译参数以兼容
  Spring Boot 3.2+ 的参数名发现。
- `maven-surefire-plugin` 统一版本 3.5.5，用于 JUnit 5 单元测试。
- 仓库源固定为华为云与阿里云 Maven 镜像，加速依赖下载。

### 3.3 模块划分与产物

- 每个业务域拆分为 `api`（接口契约）+ `server`（可执行 Jar）双模块，例如 `yudao-module-cc-api` / `yudao-module-cc-server`。
- `yudao-server` 是聚合启动入口，其余 `yudao-module-*-server` 各自独立打包为可运行 Jar，配合 Nacos 注册中心组成微服务。
- Gateway 模块 `yudao-gateway` 单独存在，作为统一入口。

### 3.4 容器化与部署

- 每个 `*-server` 模块根目录包含 `Dockerfile`，基础镜像统一为 `eclipse-temurin:21-jre`，工作目录 `/yudao-server`，暴露端口
  48080（gateway 可能不同）。
- `docker-compose.yml` 中所有服务统一设置 `TZ=Asia/Shanghai`，通过 `JAVA_TOOL_OPTIONS` 注入 SkyWalking Java Agent，并通过环境变量
  `SPRING_PROFILES_ACTIVE=test`、`SPRING_CLOUD_NACOS_*` 接入配置/注册中心。
- 服务间通过 `depends_on` + `healthcheck` 控制启动顺序（infra → report/bpm/pay/mp 等）。
- 日志通过 volume 挂载到宿主机 `/docker/yudao-cloud/logs`。

### 3.5 前端构建

- 使用 pnpm 包管理器（`pnpm-lock.yaml`），Node ≥ 20.19.0。
- 通过 `--mode env.local/dev/test/stage/prod` 切换 `.env.*` 配置文件，分别输出到 `dist` 或 `dist-prod` 目录。
- Vite 构建启用 oxc 压缩、按需拆分 echarts/form-create 等大包，支持 source map 开关。

## 4. 约定与约束

- **统一版本**：所有第三方依赖必须经 `yudao-dependencies` BOM 管理，禁止在子模块直接指定版本号（除排除冲突外）。
- **统一 revision**：项目版本通过 `${revision}` 单一入口维护，由 flatten 插件自动展开，不得在子模块硬编码版本。
- **JDK 要求**：源码编译目标为 JDK 25（`java.version=25`），但 CI 矩阵仍覆盖 8/11/17 以保证向后兼容。
- **镜像基线**：所有后端 Dockerfile 基于 `eclipse-temurin:21-jre`，时区固定为 `Asia/Shanghai`。
- **部署配置**：生产/测试环境通过 docker-compose 注入 Nacos 地址、命名空间、SkyWalking 采集端点等变量，禁止将敏感信息写死进镜像。
- **CI 行为**：push 到 master 即触发构建，默认跳过测试（`-Dmaven.test.skip=true`），如需运行测试需修改 workflow。
- **前端构建**：开发/测试/预发/生产四套构建脚本，严禁在生产构建中保留 debugger/console（由 `VITE_DROP_DEBUGGER`/
  `VITE_DROP_CONSOLE` 控制）。