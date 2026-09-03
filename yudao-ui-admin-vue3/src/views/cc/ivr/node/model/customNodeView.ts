/**
 * 自定义 Vue 节点视图
 *
 * 背景：
 * @logicflow/vue-node-registry 的 VueNodeView 在构造函数中将 measureAndUpdate
 * 定义为实例属性（而非原型方法），内部使用 getBoundingClientRect() 读取节点尺寸。
 * 该方法返回经过 SVG transform:scale() 变换后的视觉尺寸，画布缩放（zoom != 1）时
 * 会把缩小后的视觉尺寸写回 model，导致节点在内容变化（如切换放音类型）后越变越小、
 * 内容被裁剪。
 *
 * 由于实例属性会遮蔽子类原型方法，必须在 super.setHtml() 之后（此时实例已创建且
 * ResizeObserver 尚未回调）重新赋值 this.measureAndUpdate 才能生效。
 *
 * 本类重写 measureAndUpdate，改用 offsetWidth/offsetHeight（不受 transform 影响的
 * 布局尺寸），保证写回模型的始终是节点在 SVG 坐标系中的真实尺寸。
 *
 * 同时在 setHtml 时将内容容器引用挂到 model 上，供自定义 model 的 syncSizeFromDom()
 * 使用，替代当前版本不存在的 graphModel.flowChart.getHtmlElement()。
 */
import { VueNodeView } from '@logicflow/vue-node-registry'

class CustomNodeView extends VueNodeView {
  /**
   * 重写 setHtml：在父类完成 Vue 组件挂载和 ResizeObserver 启动后，
   * 替换 measureAndUpdate 实例方法，改用 offsetWidth/offsetHeight 测量尺寸，
   * 并缓存 DOM 引用到 model 供 syncSizeFromDom 使用。
   *
   * @param rootEl - foreignObject 元素，Vue 组件内容挂载到其子节点中
   */
  setHtml(rootEl: HTMLElement): void {
    super.setHtml(rootEl)

    const model = (this as any).props.model
    if (model) {
      model.__htmlRootEl = this.getComponentContainer()
    }

    /**
     * 重写尺寸测量逻辑：使用 offsetWidth/offsetHeight 替代 getBoundingClientRect，
     * 避免画布缩放时将视觉缩放尺寸误写入模型导致节点缩小。
     *
     * 注意：VueNodeView 在构造函数中将 measureAndUpdate 设为实例属性，
     * 会遮蔽原型链上的方法，因此必须在 setHtml 中重新赋值。
     * ResizeObserver 回调是异步的（RAF + throttle），此处替换先于首次回调执行。
     */
    ;(this as any).measureAndUpdate = function (this: CustomNodeView) {
      try {
        const root = this.getComponentContainer()
        if (!root) return
        const target = (root.firstElementChild as HTMLElement) || root
        const width = target.offsetWidth
        const height = target.offsetHeight
        if (width <= 0 || height <= 0) return
        const self = this as unknown as Record<string, unknown>
        if (width === self.__lastWidth && height === self.__lastHeight) return
        self.__lastWidth = width
        self.__lastHeight = height

        const props = (this as any).props.model.properties as Record<string, unknown>
        const extra = getTitleExtraHeight(props)
        const baseHeight = Math.max(height - extra, 1)
        ;(this as any).props.model.setProperties({ width, height: baseHeight })
      } catch (_) {
        // 尺寸测量失败时静默降级，保留现有模型尺寸
      }
    }
  }
}

/**
 * 计算标题区域额外占用的高度
 * @param props - 节点属性对象
 * @returns 标题高度像素值，无标题时返回 0
 */
function getTitleExtraHeight(props: Record<string, unknown>): number {
  if (!props._showTitle) return 0
  if (typeof props._titleHeight === 'number') {
    return props._titleHeight as number
  }
  return 28
}

export default CustomNodeView
