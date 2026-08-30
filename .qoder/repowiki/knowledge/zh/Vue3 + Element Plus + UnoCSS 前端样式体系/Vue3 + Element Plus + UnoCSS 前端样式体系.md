---
kind: frontend_style
name: Vue3 + Element Plus + UnoCSS 前端样式体系
category: frontend_style
scope:
    - '**'
source_files:
    - yudao-ui-admin-vue3/package.json
    - yudao-ui-admin-vue3/vite.config.ts
    - yudao-ui-admin-vue3/uno.config.ts
    - yudao-ui-admin-vue3/src/styles/index.scss
    - yudao-ui-admin-vue3/src/styles/var.css
    - yudao-ui-admin-vue3/src/styles/variables.scss
    - yudao-ui-admin-vue3/stylelint.config.js
---

## 1. 系统/技术栈

本项目的前端管理后台位于 `yudao-ui-admin-vue3`，采用 **Vue 3 + TypeScript + Vite** 构建，UI 组件库统一使用 **Element Plus 2.13**（含 `@element-plus/icons-vue`），样式方案为 **SCSS + CSS Variables + UnoCSS** 的组合：
- SCSS 通过 Vite 的 `scss.additionalData` 全局注入 `src/styles/variables.scss`，所有 `.vue` / `.scss` 文件可直接使用 `$namespace`、`$elNamespace` 等变量。
- 主题与布局尺寸集中在 `src/styles/var.css` 的 `:root` 自定义属性中（如 `--left-menu-bg-color`、`--top-header-hover-color`、`--app-content-padding`、`--transition-time-02` 等），并通过 `.dark` 类切换暗色模式。
- 使用 `unocss` 66 作为原子化 CSS 引擎，配合 `presetUno({ dark: 'class' })` 实现 class 模式暗色；通过 `rules` 扩展项目级规则（`custom-hover`、`layout-border__left/right/top/bottom`）和 `shortcuts`（`wh-full`）。
- 通过 `unplugin-element-plus` + `unplugin-vue-components` 实现 Element Plus 按需引入与自动注册。

## 2. 关键文件

| 文件 | 作用 |
|---|---|
| `yudao-ui-admin-vue3/package.json` | 声明 `element-plus`、`unocss`、`sass`、`postcss`、`stylelint`、`prettier` 等依赖及 `build:*`、`lint:style` 脚本 |
| `yudao-ui-admin-vue3/vite.config.ts` | 配置 SCSS 全局 `additionalData` 注入 `variables.scss`、别名 `@/`、构建分包策略（echarts/form-create） |
| `yudao-ui-admin-vue3/uno.config.ts` | UnoCSS 配置：`presetUno`、自定义 `rules`（hover、四边边框）、`shortcuts` |
| `yudao-ui-admin-vue3/src/styles/index.scss` | 入口样式：引入 `var.css`、`theme.scss`、FormCreate 样式、Element Plus 暗色主题 `element-plus/theme-chalk/dark/css-vars.css`，并覆盖 nprogress、抽屉滚动条等全局样式 |
| `yudao-ui-admin-vue3/src/styles/var.css` | 设计令牌集中地：菜单、Logo、Header、Tab、内容区、过渡时间等 CSS 变量 |
| `yudao-ui-admin-vue3/src/styles/variables.scss` | SCSS 命名空间 `$namespace: v`、`$elNamespace: el` |
| `yudao-ui-admin-vue3/stylelint.config.js` | Stylelint 规则：继承 `stylelint-config-standard`，强制属性顺序（`order/order`、`order/properties-order`），允许 `rpx`、`deep/global`、SCSS at-rule，并对 Vue SFC 启用 HTML 语法检查 |
| `yudao-ui-admin-vue3/.stylelintignore` | 被 stylelint 忽略的文件列表 |
| `yudao-prd/index.html` + `yudao-prd/css/common.css` | PRD 静态站点使用独立的最小化样式（仅用于原型预览，非生产 UI） |

## 3. 架构与约定

- **主题层**：所有颜色、间距、尺寸以 CSS 变量形式定义在 `:root`，通过给 `<html>` 或根节点添加 `.dark` 类切换暗色主题；Element Plus 自身也通过 `element-plus/theme-chalk/dark/css-vars.css` 暴露 `--el-*` 变量，业务变量与之混用（如 `--left-menu-bg-active-color: var(--el-color-primary)`）。
- **样式组织**：全局样式集中在 `src/styles/`，按职责拆分——`var.css` 放设计令牌、`index.scss` 做聚合与全局 reset、`theme.scss` 预留主题覆盖点、`FormCreate/index.scss` 隔离表单设计器样式。
- **原子化优先**：页面布局大量使用 UnoCSS 原子类（如 `wh-full` shortcut），复杂交互通过 `rules` 扩展语义化类名（`custom-hover`、`layout-border__*`），避免手写重复 CSS。
- **响应式/移动端**：Stylelint 显式允许 `rpx` 单位（`unit-no-unknown.ignoreUnits: ['rpx']`），说明存在适配小程序/移动端的样式需求。
- **Lint 约束**：通过 `pnpm lint:style` 运行 stylelint，强制 SCSS 内属性书写顺序（position → display → width/height → padding/margin → font → color → background → border → animation/transition 等），并在 Vue SFC 中额外启用 `stylelint-config-html`。
- **构建产物**：Vite 将 SCSS 编译后由 PostCSS/Autoprefixer 处理，最终由 UnoCSS 生成原子 CSS；Element Plus 按需引入，减少包体。

## 4. 约定与约束

- **必须通过 CSS 变量而非硬编码颜色**：业务组件应引用 `var(--el-color-primary)`、`var(--left-menu-bg-color)` 等变量，以保证主题一致性。
- **暗色模式通过 `.dark` 类切换**：UnoCSS 与 Element Plus 均基于 `class` 模式，新增暗色样式需包裹在 `.dark` 选择器下。
- **SCSS 文件必须使用 `@use` 引入变量**：Vite 通过 `additionalData` 自动注入 `variables.scss`，但为避免重复注入导致 Sass duplicate global variables，该文件本身不主动 `@use` 自己。
- **新增样式遵循 Stylelint 属性顺序**：`stylelint.config.js` 中的 `order/properties-order` 是硬性规则，提交前需通过 `pnpm lint:style`。
- **禁止随意使用未知伪类/伪元素**：仅允许 `deep`、`global`、`v-deep`、`v-global`、`v-slotted` 等穿透选择器，其余未知伪类会被 stylelint 拒绝。
- **PRD 站点与生产 UI 分离**：`yudao-prd/` 下的 `common.css`、`lib/element-plus.js` 仅用于产品原型预览，不应混入 `yudao-ui-admin-vue3` 生产代码。