---
kind: dependency_management
name: Maven BOM + pnpm 多模块依赖统一管理与私有仓库镜像
category: dependency_management
scope:
    - '**'
source_files:
    - yudao-cloud/pom.xml
    - yudao-cloud/yudao-dependencies/pom.xml
    - yudao-ui-admin-vue3/package.json
    - yudao-ui-admin-vue3/pnpm-lock.yaml
    - yudao-ui-admin-vue3/.npmrc
    - .gitmodules
---

## 1. 整体方案

本项目采用 **Maven 多模块 + BOM（Bill of Materials）+ pnpm** 的混合依赖管理策略：
- Java 后端通过 `yudao-dependencies` 作为统一的 BOM，集中声明所有第三方库版本；各业务模块仅引入 starter 而不指定版本。
- 前端 Vue3 工程使用 `pnpm` 进行包管理，并通过 `pnpm-lock.yaml` 锁定依赖树。
- 顶层仓库通过 **Git Submodule** 聚合 `yudao-cloud`、`yudao-ui-admin-vue3`、`yudao-prd` 三个子仓库，使前后端与文档在单一仓库中协同演进。
- Maven 构建阶段通过 `flatten-maven-plugin` 将 `${revision}` 变量展开为固定版本号，生成可发布的扁平化 POM。

## 2. 关键文件

| 文件 | 作用 |
|---|---|
| `yudao-cloud/pom.xml` | 根 POM，声明 modules、统一 `revision=2026.07-SNAPSHOT`、导入 `yudao-dependencies` BOM、配置华为/阿里云 Maven 镜像源 |
| `yudao-cloud/yudao-dependencies/pom.xml` | BOM 核心，集中声明 Spring Boot、Spring Cloud、Alibaba、MyBatis-Plus、Redisson、Flowable、Hutool、Fastjson2、Weixin-Java 等全部第三方依赖版本 |
| `yudao-cloud/yudao-framework/*/pom.xml` | 各 Starter 模块仅声明自身依赖，版本由 BOM 统一管理 |
| `yudao-ui-admin-vue3/package.json` | 前端依赖声明（dependencies/devDependencies），限定 Node ≥20.19.0、pnpm ≥8.6.0 |
| `yudao-ui-admin-vue3/pnpm-lock.yaml` | pnpm 锁文件，锁定精确依赖树 |
| `yudao-ui-admin-vue3/.npmrc` | pnpm 配置：`shamefully-hoist=true`、`auto-install-peers=true`、`unsafe-perm=true` |
| `.gitmodules` | 定义 `yudao-cloud`、`yudao-ui-admin-vue3`、`yudao-prd` 三个 Git 子模块及其远端地址 |

## 3. 架构与约定

### 3.1 Maven BOM 分层
- **顶层 POM** (`yudao-cloud/pom.xml`)：仅做聚合与插件管理，不直接声明业务依赖。通过 `<dependencyManagement><import>` 引入 `yudao-dependencies`。
- **BOM 模块** (`yudao-dependencies/pom.xml`)：以 `<properties>` 集中维护每个第三方库的版本号（如 `spring.boot.version=3.5.15`、`mybatis-plus.version=3.5.16`、`redisson.version=4.6.1` 等），并在 `<dependencyManagement>` 中以 `<type>pom</type>` 形式 import Spring Boot / Spring Cloud / Spring Cloud Alibaba 官方 BOM，再覆盖业务组件版本。
- **业务模块**：各 `yudao-module-*-server` 及 `yudao-framework/*` 仅写 `<artifactId>`，版本继承自 BOM。

### 3.2 版本统一策略
- 项目自身所有模块共享 `${revision}`（当前为 `2026.07-SNAPSHOT`），由 `flatten-maven-plugin` 在 `process-resources` 阶段替换为真实版本号，并执行 `clean` 清理生成的 POM。
- 第三方依赖版本集中在 BOM 的 `<properties>` 中，升级时只需修改一处。

### 3.3 依赖冲突治理
BOM 中对易冲突的传递依赖做了显式排除与锁定：
- `lock4j` 排除其自带的 `redisson-spring-boot-starter`，改用 BOM 中的 `redisson-spring-data-35` 以适配 Spring Boot 3.5。
- `rocketmq-spring-boot-starter` 排除 `fastjson`，避免与项目使用的 fastjson2 冲突。
- `justauth-spring-boot-starter` 排除 `hutool-core`，避免与项目 hutool-all 冲突。
- `weixin-java-*` 系列通过固定 `bouncycastle` 版本防止自动升级到不兼容的 `1.80.2`。
- `flowable` 与 `mybatis-plus` 之间通过显式声明 `mybatis.version=3.5.19` 保证一致性。

### 3.4 私有仓库与镜像
根 POM 中配置了华为云与阿里云公共镜像：
```xml
<repositories>
    <repository>
        <id>huaweicloud</id>
        <url>https://mirrors.huaweicloud.com/repository/maven/</url>
    </repository>
    <repository>
        <id>aliyunmaven</id>
        <url>https://maven.aliyun.com/repository/public</url>
    </repository>
</repositories>
```
未发现配置私有 Nexus/Artifactory 或 `settings.xml` 中的认证信息，说明当前依赖来源均为公共镜像。

### 3.5 前端依赖管理
- 使用 `pnpm` 作为包管理器，`package.json` 中明确声明 `engines.node >= 20.19.0`、`engines.pnpm >= 8.6.0`。
- 生产依赖（如 `vue@3.5.34`、`element-plus@2.13.7`、`axios@1.16.0`、`pinia@^3.0.4`）与开发依赖（vite、typescript、eslint 等）严格区分。
- `pnpm-lock.yaml` 提供确定性安装；`.npmrc` 启用 `shamefully-hoist` 和 `auto-install-peers` 以兼容部分依赖的 peer dependency 场景。

### 3.6 子模块聚合
顶层 `.gitmodules` 将后端、前端、PRD 作为 Git Submodule 纳入同一仓库，便于一次性克隆与版本对齐。子模块各自维护独立的依赖清单，互不影响。

## 4. 约定与约束

- **禁止在业务模块 POM 中硬编码第三方依赖版本**——所有版本必须通过 BOM 的 `<properties>` 管理，新增依赖需先在 `yudao-dependencies/pom.xml` 中添加属性与 managed 条目。
- **项目自身模块版本统一通过 `${revision}` 管理**，不得在子模块中单独声明 `<version>`。
- **依赖冲突通过 BOM 层显式 `<exclusion>` 解决**，而非在业务模块中二次排除。
- **Java 编译环境锁定为 JDK 17**（`java.version=17`），Lombok + MapStruct 注解处理器路径在根 POM 的 `maven-compiler-plugin` 中统一配置。
- **前端要求 Node.js ≥20.19.0、pnpm ≥8.6.0**，通过 `package.json` 的 `engines` 字段声明，CI 或本地可通过 `pnpm --ignore-engines` 绕过但不应这样做。
- **未使用 npm/yarn**，前端统一使用 pnpm，避免 lockfile 不一致导致的安装差异。
- **未发现 vendor/ 目录或源码级 vendoring**，所有依赖均通过远程仓库解析。
- **未发现 CI 中的依赖更新自动化脚本**（如 Renovate、Dependabot），依赖升级需人工修改 BOM 或 `package.json`。