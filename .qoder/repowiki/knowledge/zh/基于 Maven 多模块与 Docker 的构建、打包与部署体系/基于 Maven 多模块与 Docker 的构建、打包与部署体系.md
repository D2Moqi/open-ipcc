---
kind: build_system
name: 基于 Maven 多模块与 Docker 的构建、打包与部署体系
category: build_system
scope:
    - '**'
source_files:
    - yudao-cloud/pom.xml
    - yudao-cloud/yudao-dependencies/pom.xml
    - yudao-cloud/.github/workflows/maven.yml
    - yudao-cloud/script/docker/docker-compose.yml
    - yudao-cloud/yudao-server/Dockerfile
    - yudao-cloud/yudao-gateway/Dockerfile
    - yudao-ui-admin-vue3/package.json
    - yudao-ui-admin-vue3/vite.config.ts
    - yudao-cloud/sql/mysql/quartz.sql
    - yudao-cloud/sql/mysql/ruoyi-vue-pro.sql
    - yudao-cloud/sql/tools/convertor.py
---

## 1. 构建系统总览

本项目采用 **Maven 多模块 + Spring Boot 3 (JDK 17) + Vite 前端工程** 的双栈构建方式，通过 Git 子模块聚合后端 `yudao-cloud`、Vue3 管理后台 `yudao-ui-admin-vue3` 与 PRD 文档站点。后端以 `yudao` 根 POM 为聚合入口，仅启用 system/infra/cc 三个业务模块（其余模块在根 POM 中以注释形式保留），形成裁剪后的呼叫中心单体服务；每个业务模块同时提供 API 与 Server 子模块，遵循 API-Server 解耦约定。

## 2. 核心构建文件与工具

- **根构建配置**：`yudao-cloud/pom.xml` 定义所有模块、统一版本 `${revision}`（当前 `2026.07-SNAPSHOT`）、Java 17 编译、Lombok+MapStruct 注解处理器链、`flatten-maven-plugin` 生成扁平化 POM 并发布。
- **依赖 BOM**：`yudao-dependencies/pom.xml` 作为 `dependencyManagement` 导入中心，集中声明所有第三方依赖版本，各子模块不再重复声明版本号。
- **CI**：`.github/workflows/maven.yml` 在 GitHub Actions 中对 JDK 8/11/17 矩阵执行 `mvn -B package --file pom.xml -Dmaven.test.skip=true`，缓存 Maven 仓库以提升速度。
- **容器镜像**：每个可独立部署的服务（gateway、system、infra、bpm、pay、mp、report、ai、crm、erp、im、mall、mes、wms、cc-server 等）均自带 `Dockerfile`，基础镜像统一使用 `eclipse-temurin:21-jre`，暴露端口并支持通过 `JAVA_OPTS`/`ARGS` 环境变量覆盖 JVM 参数与启动参数。
- **本地编排**：`script/docker/docker-compose.yml` 提供 gateway/system/infra/report/bpm/pay/mp 等服务一键拉起脚本，默认挂载 SkyWalking Agent 与日志目录，使用 host 网络模式并通过 Nacos 配置/注册中心注入运行时参数。
- **数据库初始化**：`sql/<db>/` 下按 MySQL、PostgreSQL、Oracle、SQL Server、达梦、人大金仓、OpenGauss、瀚高、DM2 等分别提供 `quartz.sql` 与 `ruoyi-vue-pro.sql` 初始化脚本，另有 `sql/tools/convertor.py` 用于 DDL 转换。
- **前端构建**：`yudao-ui-admin-vue3/package.json` 定义 `dev`/`build:local`/`build:dev`/`build:test`/`build:stage`/`build:prod` 等多环境脚本，通过 `vite.config.ts` + `.env.*` 切换；构建产物输出到 `dist/`，使用 oxc 压缩并按 echarts/form-create 拆分 chunk。

## 3. 架构与约定

- **版本策略**：通过 `flatten-maven-plugin` 的 `oss` 模式将 `${revision}` 展开为具体版本号写入发布 POM，clean 阶段自动清理，保证发布物不含占位符。
- **源码编码与编译器**：统一 UTF-8，强制 `-parameters` 编译参数以兼容 Spring Boot 3 的参数名发现机制；Lombok、lombok-mapstruct-binding、mapstruct-processor、spring-boot-configuration-processor 组成固定注解处理器顺序。
- **模块裁剪**：根 POM 中除 system/infra/cc 外，其余 module 均以 XML 注释形式存在，便于按需启用；CC 二次开发聚焦 `yudao-module-cc`，其内又包含 `ipcc-fs-esl`（FreeSWITCH ESL 客户端）、`ipcc-sipproxy`（SIP over WebSocket 代理）两个独立 Maven 子项目以及 `yudao-module-cc-api`/`yudao-module-cc-server` 业务层。
- **运行环境**：容器内统一设置 `TZ=Asia/Shanghai`，通过 `SPRING_PROFILES_ACTIVE`、`SPRING_CLOUD_NACOS_*` 环境变量注入配置；SkyWalking 通过 `JAVA_TOOL_OPTIONS=-javaagent:...` 注入链路追踪。
- **前端多环境**：Vite 通过 `--mode dev/test/stage/prod` 加载对应 `.env.*` 文件，`VITE_BASE_PATH`、`VITE_PORT`、`VITE_OUT_DIR`、`VITE_SOURCEMAP`、`VITE_DROP_DEBUGGER`、`VITE_DROP_CONSOLE` 等变量控制构建行为。

## 4. 约束与规范

- 后端必须使用 JDK 17 进行编译（`java.version=17`），但 CI 矩阵仍对 8/11/17 做兼容性验证。
- 新增业务模块需遵循 `xxx-api` + `xxx-server` 双模块拆分结构，并在根 POM 中显式 `<module>` 引入方可参与构建。
- 每个可部署服务必须提供 `Dockerfile`，且镜像基础镜像统一为 `eclipse-temurin:21-jre`，通过环境变量而非硬编码传递 JVM 与启动参数。
- 数据库变更需同步维护 `sql/<db>/` 下的多方言 SQL 脚本，或借助 `sql/tools/convertor.py` 生成。
- 前端构建要求 Node ≥ 20.19.0、pnpm ≥ 8.6.0（见 `package.json` engines），并使用 `pnpm install` 安装依赖。
- 代码质量检查通过 `lint-staged` + ESLint + Prettier + Stylelint 组合，在 `package.json` scripts 中提供 `lint`/`lint:eslint`/`lint:format`/`lint:style` 命令。
- 发布制品由 `mvn package` 生成的 `target/*.jar` 直接打入镜像，不经过额外归档步骤；GitHub Actions 跳过测试（`-Dmaven.test.skip=true`），单元测试需在本地或自定义流水线执行。
