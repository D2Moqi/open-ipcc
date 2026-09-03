---
kind: dependency_management
name: 基于 Maven BOM + pnpm 的多模块依赖版本统一与镜像源管理
category: dependency_management
scope:
    - '**'
source_files:
    - yudao-cloud/pom.xml
    - yudao-cloud/yudao-dependencies/pom.xml
    - yudao-ui-admin-vue3/package.json
    - yudao-ui-admin-vue3/pnpm-lock.yaml
    - yudao-ui-admin-vue3/.npmrc
    - yudao-ui-admin-vue3/pnpm-workspace.yaml
    - yudao-cloud/.gitmodules
    - yudao-cloud/yudao-module-cc/ipcc-fs-esl/pom.xml
    - yudao-cloud/yudao-module-cc/ipcc-sipproxy/pom.xml
---

## 1. 使用的系统与工具

- 后端（Java）：Maven 多模块项目，通过 `yudao-dependencies` 子模块作为 **BOM**（Bill of Materials）集中声明所有第三方依赖版本；根
  `pom.xml` 通过 `<dependencyManagement><import>` 引入该 BOM。
- 前端（Vue3）：pnpm 工作区（`pnpm-workspace.yaml`），依赖版本集中在 `package.json` 中，使用 `pnpm-lock.yaml` 锁定安装结果。
- 私有/本地组件：FreeSWITCH ESL 客户端 (`ipcc-fs-esl`) 和 SIP 代理 (`ipcc-sipproxy`) 以 **Git Submodule** 形式嵌入
  `yudao-module-cc/`，各自维护独立 `pom.xml` 并复用父 POM 的依赖管理。

## 2. 关键文件

- `yudao-cloud/pom.xml`：根聚合 POM，声明 Java/Spring Boot/Maven 插件版本、`revision` 统一版本号、以及华为云/阿里云 Maven
  镜像仓库。
- `yudao-cloud/yudao-dependencies/pom.xml`： **核心 BOM**，集中声明 Spring Boot、Spring Cloud、Alibaba
  Cloud、MyBatis-Plus、Redisson、Flowable、SkyWalking、Hutool、Fastjson2、Weixin-Java、Alipay SDK 等全部第三方依赖的版本号，并通过
  `<exclusions>` 解决冲突（如排除 fastjson、hutool-core、redisson 等）。
- `yudao-ui-admin-vue3/package.json`：前端依赖清单，固定 Vue 3.5.34、Element Plus 2.13.7、Vite 8.1.4、TypeScript 6.0.3 等版本。
- `yudao-ui-admin-vue3/pnpm-lock.yaml`：pnpm 锁文件，保证前端依赖树可重现。
- `yudao-ui-admin-vue3/.npmrc`：pnpm 配置，启用 `shamefully-hoist=true`、`auto-install-peers=true`、`unsafe-perm=true`。
- `yudao-ui-admin-vue3/pnpm-workspace.yaml`：定义 workspace 包列表及允许构建的 native addon。
- `yudao-cloud/.gitmodules`：声明两个 Git Submodule（`ipcc-fs-esl`、`ipcc-sipproxy`）。

## 3. 架构与约定

- **单一版本源**：所有后端模块不直接写具体第三方库版本，而是通过 `cn.iocoder.cloud:yudao-dependencies` BOM 继承版本；业务模块仅声明
  groupId/artifactId，由 BOM 注入 version。
- **统一 revision**：根 POM 使用 `${revision}` 属性控制整个多模块项目的版本号，配合 `flatten-maven-plugin`（`oss`/`bom`
  模式）在构建时生成扁平化 POM，便于发布到仓库。
- **镜像仓库优先**：根 POM 的 `<repositories>` 显式配置华为云 (`mirrors.huaweicloud.com`) 与阿里云 (`maven.aliyun.com`)
  公共镜像，提升国内下载速度。
- **依赖冲突治理**：BOM 中对易冲突的三方库（fastjson、hutool、redisson、jsqlparser 等）使用 `<exclusions>` 显式剔除传递依赖，避免版本漂移。
- **Submodule 内聚**：呼叫中心核心能力（FreeSWITCH ESL 客户端、SIP Proxy）作为独立 Maven 模块通过 Git Submodule
  引入，保持代码与依赖版本隔离，但仍遵循父 POM 的编译插件约定（Lombok + MapStruct + proc=full）。
- **前端依赖锁定**：pnpm 通过 `pnpm-lock.yaml` 锁定精确版本，`.npmrc` 中的 `shamefully-hoist` 兼容旧版 node_modules 结构，
  `auto-install-peers` 自动安装 peerDependencies。

## 4. 约定与约束

- 新增后端第三方依赖必须先在 `yudao-dependencies/pom.xml` 的 `<properties>` 中声明版本号，再在 `<dependencyManagement>`
  中注册，禁止在业务模块中硬编码版本。
- 若第三方依赖存在已知冲突或安全漏洞，应在 BOM 层通过 `<exclusions>` 或升级版本处理（例如注释中明确标注“解决
  CVE-2025-48924”、“避免 Fast Jar 启动失败”）。
- 所有模块共享 `revision` 统一版本号，发布前需执行 `flatten-maven-plugin` 生成扁平 POM。
- 前端新增依赖应写入 `package.json`，提交后需同步更新 `pnpm-lock.yaml`，禁止手动修改 `node_modules`。
- 呼叫中心专用组件（`ipcc-fs-esl`、`ipcc-sipproxy`）通过 `.gitmodules` 管理，克隆仓库时需执行
  `git submodule update --init --recursive`。
- 未在项目中发现全局 `~/.m2/settings.xml` 或 CI 中的私有 Maven 仓库配置，当前仅依赖华为云/阿里云公共镜像。