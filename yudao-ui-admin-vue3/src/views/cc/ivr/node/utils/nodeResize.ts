/**
 * IVR 节点尺寸同步工具
 *
 * 背景：
 * LogicFlow 的 HtmlNodeModel 将 Vue 组件渲染在 SVG foreignObject 内。
 * 当组件内容高度动态变化时（如放音类型从"语音文件"select 切换到"文本内容"textarea），
 * 节点 DOM 的 offsetHeight 会改变，但 model.width/height 不会自动更新，
 * 导致 foreignObject 尺寸与内容不一致，出现内容被裁剪、连线错位等问题。
 *
 * 本工具在 DOM 更新后（nextTick）主动调用 nodeModel.syncSizeFromDom()，
 * 强制将 foreignObject 尺寸同步为真实 DOM 尺寸。
 */
import { nextTick } from 'vue'
import { useIvrStore } from '../../store/ivr'

/**
 * 同步指定 LogicFlow 节点的 foreignObject 尺寸为当前 DOM 真实尺寸
 *
 * 调用时机：表单字段变化导致内容高度改变后，在 nextTick 中调用。
 * 例如：放音类型切换、条件增删、路由类型切换等会改变 DOM 高度的交互。
 *
 * @param getNode - 组件 inject 的 getNode 函数，返回当前 LF 节点数据
 * @returns Promise<void>，在 DOM 更新和尺寸同步完成后 resolve
 */
export async function syncNodeSize(getNode: () => any): Promise<void> {
  try {
    await nextTick()
    const node = getNode?.()
    if (!node) return
    const lf = useIvrStore().getLf as any
    if (!lf?.graphModel) return
    const nodeModel = lf.graphModel.getNodeModelById(node.id)
    if (!nodeModel) return
    if (typeof nodeModel.syncSizeFromDom === 'function') {
      nodeModel.syncSizeFromDom()
    }
  } catch (e) {
    console.warn('同步节点尺寸失败', e)
  }
}
