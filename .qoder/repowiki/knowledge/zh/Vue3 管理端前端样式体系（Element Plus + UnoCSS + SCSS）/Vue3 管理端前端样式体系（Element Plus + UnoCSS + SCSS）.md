---
kind: frontend_style
name: Vue3 管理端前端样式体系（Element Plus + UnoCSS + SCSS）
category: frontend_style
scope:
    - '**'
source_files:
    - yudao-ui-admin-vue3/package.json
    - yudao-ui-admin-vue3/uno.config.ts
    - yudao-ui-admin-vue3/src/styles/var.css
    - yudao-ui-admin-vue3/src/styles/index.scss
    - yudao-ui-admin-vue3/src/styles/variables.scss
    - yudao-ui-admin-vue3/src/styles/theme.scss
    - yudao-ui-admin-vue3/stylelint.config.js
---

## 1. 采用的系统/方案

- **框架与构建**：基于 Vue 3 + Vite 4 的前端工程，使用 pnpm 作为包管理器。
- **UI 组件库**：Element Plus 2.x，通过 `unplugin-element-plus` 按需引入；深色主题通过导入
  `element-plus/theme-chalk/dark/css-vars.css` 启用。
- **原子化 CSS**：使用 UnoCSS 66（`presetUno`），在 `uno.config.ts` 中扩展自定义规则（如 `custom-hover`、
  `layout-border__left/right/top/bottom`）和快捷类 `wh-full`，并开启 `dark: 'class'` 模式以配合 Element Plus 的
  class-based 暗色切换。
- **预处理器**：SCSS（`sass` 包），通过 `postcss-scss` 在 stylelint 中对部分文件启用 SCSS 解析。
- **国际化**：`vue-i18n` 提供多语言文案，样式层不直接绑定语言。

## 2. 关键文件与包

- `yudao-ui-admin-vue3/package.json`：声明 `element-plus`、`unocss`、`sass`、`stylelint`、`prettier`、`vite` 等核心依赖。
- `yudao-ui-admin-vue3/uno.config.ts`：UnoCSS 配置，定义业务级自定义规则与快捷键。
- `yudao-ui-admin-vue3/src/styles/var.css`：全局 CSS 变量集中地，定义登录背景、左侧菜单宽度/颜色、顶部工具栏高度、标签页高度、应用内容区背景、过渡时间等设计令牌。
- `yudao-ui-admin-vue3/src/styles/index.scss`：入口样式，引入 `var.css`、`FormCreate/index.scss`、`theme.scss` 以及 Element
  Plus 暗色主题变量；包含 nprogress 进度条与 Element 滚动条的全局修复。
- `yudao-ui-admin-vue3/src/styles/variables.scss`：仅定义 SCSS 命名空间 `$namespace: v` 与 Element 命名空间
  `$elNamespace: el`。
- `yudao-ui-admin-vue3/src/styles/theme.scss`：当前为占位文件，预留按 dark/light 切换文本色的注释示例。
- `yudao-ui-admin-vue3/stylelint.config.js`：统一样式规范校验，继承 `stylelint-config-standard`，对 `.vue`/`.html` 使用
  `postcss-html`，并对特定 SCSS 文件使用 `postcss-scss`。
- `yudao-ui-admin-vue3/.eslintrc-auto-import.json`、`eslint.config.mjs`、`prettier.config.js`、`.editorconfig`：配合
  ESLint + Prettier 进行代码格式化约束。

## 3. 架构与约定

### 3.1 设计令牌（Design Tokens）

- 所有布局与主题相关尺寸、颜色均集中在 `src/styles/var.css` 的 `:root` 下，例如 `--left-menu-max-width`、
  `--left-menu-bg-color`、`--top-header-bg-color`、`--tags-view-height`、`--app-content-padding`、`--transition-time-02` 等。
- 深色模式下通过 `.dark` 选择器覆盖部分变量（如 `--app-content-bg-color` 指向 `--el-bg-color`），实现与 Element Plus
  暗色主题的联动。
- 颜色方面大量复用 Element Plus 内置 CSS 变量（如 `--el-color-primary`、`--el-border-color`、`--el-bg-color-overlay`
  ），避免硬编码色值。

### 3.2 样式组织方式

- 全局基础样式集中在 `src/styles/`：`index.scss` 作为聚合入口，`var.css` 承载设计令牌，`theme.scss` 预留主题扩展点，
  `FormCreate/` 子目录承载表单设计器定制样式。
- 业务组件样式优先使用 UnoCSS 原子类（如 `wh-full`、`custom-hover`、`layout-border__*`），仅在需要复杂结构或伪元素时回退到
  SCSS。
- 第三方组件（Element Plus、nprogress）通过全局样式覆盖适配项目主题，而非修改源码。

### 3.3 响应式策略

- 未引入移动端专用框架；布局通过 CSS 变量控制侧边栏最小/最大宽度（`--left-menu-min-width`、`--left-menu-max-width`
  ）及折叠态，结合媒体查询在组件内处理。
- 未使用 Tailwind 或 Bootstrap，响应式断点由项目自行在 SCSS 中编写。

### 3.4 图标与资源

- 图标采用 `@iconify/vue` + `@iconify/json` 组合，通过 SVG sprite 方式按需加载。
- 静态资源按功能域分目录存放于 `src/assets/`（如 `ai/`、`cc/`、`ivr/`、`imgs/`、`svgs/`），便于呼叫中心各模块隔离。

## 4. 约定与约束

- **样式规范由 Stylelint + Prettier 强制**：`pnpm lint:style` 与 `pnpm lint:format` 分别执行样式检查与格式化；
  `stylelint.config.js` 规定了属性顺序（`order/properties-order`）、SCSS at-rule 白名单、`rpx` 单位允许等规则，并在 `.vue`/
  `.html` 中额外启用 HTML 推荐规则。
- **命名空间约定**：SCSS 中使用 `$namespace: v` 作为项目前缀，Element 组件命名空间为 `$elNamespace: el`，便于生成带前缀的类名。
- **暗色主题开关**：通过 UnoCSS 的 `dark: 'class'` 模式与 Element Plus 的 `dark/css-vars.css` 配合，页面根节点添加/移除
  `dark` class 即可切换主题。
- **禁止随意写死颜色**：现有代码普遍通过 `var(--el-* )` 或 `var(--xxx)` 读取设计令牌，新增样式应沿用该方式以保持主题一致性。
- **SCSS 文件范围受限**：stylelint 仅对个别路径（如 `src/views/im/home/components/picker/picker-dialog.scss`）启用
  `postcss-scss` 解析，其余 `.vue`/`.scss` 走 postcss-html 流程，避免历史遗留 SCSS 语法污染整体检查。
- **构建产物**：生产构建输出至 `dist-prod/`，其中 `assets/` 包含打包后的样式与资源，`index.html` 与 `logo.gif` 为入口与
  favicon。

总体而言，该项目的前端样式体系以 **Element Plus 组件库 + UnoCSS 原子类 + SCSS 设计令牌** 为核心，通过统一的
stylelint/prettier 流水线保障风格一致，并通过 CSS 变量实现主题与布局的可配置化。