/**
 * 表单交互事件拦截工具（v3：最终版）
 *
 * 核心设计思路：
 * LogicFlow 画布拖拽/选中流程 = pointerdown/mousedown（记录起点+选中节点）+ pointermove（计算偏移→移动节点）+ pointerup（结束）
 * Element Plus 弹层打开流程 = click 事件冒泡到组件自身的 handler → popperManager 全局监听
 *
 * v3 方案（容器级冒泡拦截 + 窗口级 move 拦截双保险）：
 *   1. 在 LF container 上以 bubble 阶段监听 pointerdown/mousedown/click，
 *      且在 `new LogicFlow()` 之前注册（installIvrFormGuard 在 LF 初始化前调用），
 *      保证同一元素上我们的监听器先于 LF 触发。
 *      当事件 target 是表单控件时，调用 stopPropagation()：
 *      → 事件已从 target 冒泡到 container（目标和子组件的 handler 已执行完毕）
 *      → 在 container 处截断，LF 的 container 级监听收不到事件 → 不会选中节点/启动拖拽 ✅
 *      → Element Plus 组件自身的 click handler 在 target 阶段已执行 → 弹层正常打开 ✅
 *      → 不调用 preventDefault()，浏览器默认行为（input 聚焦）正常 ✅
 *   2. window capture 阶段继续拦截 pointermove/mousemove（双保险，防止极端情况下 LF 已记录起点）
 *   3. pointerup/mouseup 后重置标志位
 */

/**
 * 判断事件 target 是否属于"可交互的表单/菜单控件"
 * 通过 tagName、className、aria role 等多维度识别，最多向上回溯 20 层
 */
export function isInteractiveFormTarget(target: EventTarget | null): boolean {
  if (!target) return false
  let el: HTMLElement | null = target as HTMLElement
  const MAX_DEPTH = 20
  let depth = 0
  while (el && depth < MAX_DEPTH) {
    if (el.nodeType !== 1) {
      el = el.parentElement
      depth++
      continue
    }
    const tag = el.tagName
    if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA' || tag === 'BUTTON' || tag === 'A') return true
    const cls = (el as HTMLElement).className
    if (typeof cls === 'string' && cls.length > 0) {
      if (
        cls.indexOf('el-select') !== -1 || cls.indexOf('el-cascader') !== -1 ||
        cls.indexOf('el-input') !== -1 || cls.indexOf('el-textarea') !== -1 ||
        cls.indexOf('el-input-number') !== -1 || cls.indexOf('el-button') !== -1 ||
        cls.indexOf('el-popper') !== -1 || cls.indexOf('el-dropdown') !== -1 ||
        cls.indexOf('el-switch') !== -1 || cls.indexOf('el-option') !== -1 ||
        cls.indexOf('el-checkbox') !== -1 || cls.indexOf('el-radio') !== -1 ||
        cls.indexOf('el-popover') !== -1 || cls.indexOf('el-date-editor') !== -1 ||
        cls.indexOf('el-time-panel') !== -1 || cls.indexOf('el-cascader__panel') !== -1 ||
        cls.indexOf('el-select-dropdown') !== -1 || cls.indexOf('el-color-picker') !== -1 ||
        cls.indexOf('el-slider') !== -1 || cls.indexOf('el-upload') !== -1 ||
        cls.indexOf('el-rate') !== -1 || cls.indexOf('el-transfer-panel') !== -1 ||
        cls.indexOf('el-tree') !== -1 || cls.indexOf('el-virtual') !== -1 ||
        cls.indexOf('el-dialog') !== -1 || cls.indexOf('el-drawer') !== -1 ||
        cls.indexOf('el-notification') !== -1 || cls.indexOf('el-message-box') !== -1 ||
        cls.indexOf('el-radio-group') !== -1 || cls.indexOf('el-checkbox-group') !== -1
      ) {
        return true
      }
    }
    const role = (el as HTMLElement).getAttribute?.('role')
    if (
      role &&
      ['button', 'option', 'menuitem', 'listbox', 'combobox', 'textbox', 'slider', 'spinbutton',
        'tab', 'tabpanel', 'dialog', 'menu', 'menubar', 'radiogroup', 'tree', 'treeitem',
        'grid', 'gridcell', 'checkbox', 'radio', 'switch'].indexOf(role) !== -1
    ) {
      return true
    }
    // tabindex="0" + contenteditable
    const tabIndex = (el as HTMLElement).getAttribute?.('tabindex')
    if (tabIndex === '0' && (tag === 'DIV' || tag === 'SPAN')) {
      const editable = (el as HTMLElement).getAttribute?.('contenteditable')
      if (editable === 'true' || editable === '') return true
    }
    el = el.parentElement
    depth++
  }
  return false
}

/** ================ 全局拖拽拦截（v2） ================ */

let _formInteracting = false
let _container: HTMLElement | null = null

/**
 * container 级 bubble 阶段拦截：表单控件的 pointerdown/mousedown/click 冒泡到 container 时截断，
 * 阻止 LF 的 container 监听器收到事件（选中节点/启动拖拽）。
 * 因为此监听器在 new LogicFlow() 之前注册，同一元素上先于 LF 触发。
 */
function _onContainerBubble(e: Event): void {
  if (isInteractiveFormTarget(e.target)) {
    e.stopPropagation()
  }
}

/**
 * 在 pointerdown 捕获阶段调用（window 层）
 * 如果事件目标是 IVR 容器内的表单控件，仅设置交互标志位，**不阻止事件冒泡**
 * 这样：
 *  - Element Plus popperManager（在 document/body）能收到事件 → 弹层正常打开
 *  - LogicFlow 的 pointerdown 记录起点逻辑照常执行（没关系，我们拦 move 就行）
 */
function _onDownCapture(e: Event): void {
  const tgt = e.target as HTMLElement | null
  if (!tgt || !_container) return
  if (!_container.contains(tgt)) return
  if (isInteractiveFormTarget(tgt)) {
    _formInteracting = true
    // 注意：这里绝对不能调用 e.stopPropagation() 或 e.preventDefault()
    // 否则 Element Plus 的全局弹层监听收不到，弹层打不开
  }
}

/**
 * 在 pointermove/mousemove 捕获阶段调用（window 层）
 * 表单交互期间的移动事件被我们拦截，LogicFlow 的 document 监听收不到，
 * 于是不会触发节点拖拽偏移，从而实现"单击即可激活控件"的效果
 */
function _onMoveCapture(e: Event): void {
  if (_formInteracting) {
    try { e.stopPropagation() } catch (_) {}
    try { (e as any).stopImmediatePropagation?.() } catch (_) {}
  }
}

/**
 * pointerup/mouseup 后重置标志位，允许后续正常拖拽节点
 */
function _onUpCapture(_e: Event): void {
  if (_formInteracting) _formInteracting = false
}

/**
 * 安装全局 IVR 表单交互守护者（在 onMounted 中 LF 初始化前调用）
 * @param container IVR 画布外层容器（LogicFlow 的 container 元素）
 * @returns 卸载函数，onBeforeUnmount 调用
 */
export function installIvrFormGuard(container: HTMLElement): () => void {
  _container = container
  _formInteracting = false

  // container 级 bubble 阶段拦截（核心修复）：
  // 在 LF 初始化前注册，保证同一元素上先于 LF 触发。
  // 表单控件事件冒泡到 container 时截断，LF 收不到 → 不会选中节点/启动拖拽。
  container.addEventListener('pointerdown', _onContainerBubble, false)
  container.addEventListener('mousedown', _onContainerBubble, false)
  container.addEventListener('click', _onContainerBubble, false)

  // window capture 阶段拦截 move（双保险）
  window.addEventListener('pointerdown', _onDownCapture, true)
  window.addEventListener('mousedown', _onDownCapture, true)
  window.addEventListener('pointermove', _onMoveCapture, true)
  window.addEventListener('mousemove', _onMoveCapture, true)
  window.addEventListener('pointerup', _onUpCapture, true)
  window.addEventListener('mouseup', _onUpCapture, true)
  window.addEventListener('pointercancel', _onUpCapture, true)

  return function uninstallIvrFormGuard() {
    container.removeEventListener('pointerdown', _onContainerBubble, false)
    container.removeEventListener('mousedown', _onContainerBubble, false)
    container.removeEventListener('click', _onContainerBubble, false)
    window.removeEventListener('pointerdown', _onDownCapture, true)
    window.removeEventListener('mousedown', _onDownCapture, true)
    window.removeEventListener('pointermove', _onMoveCapture, true)
    window.removeEventListener('mousemove', _onMoveCapture, true)
    window.removeEventListener('pointerup', _onUpCapture, true)
    window.removeEventListener('mouseup', _onUpCapture, true)
    window.removeEventListener('pointercancel', _onUpCapture, true)
    _container = null
    _formInteracting = false
  }
}

/**
 * 节点内部兼容方法：在 node-box 的 bubble 阶段事件回调中调用，
 * 当事件源是表单控件时 stopPropagation，阻止事件继续冒泡到 LF container。
 * 与全局 container 级监听器形成双保险。
 */
export function stopFormEventBubble(e: Event): void {
  if (isInteractiveFormTarget(e.target)) {
    e.stopPropagation()
  }
}
