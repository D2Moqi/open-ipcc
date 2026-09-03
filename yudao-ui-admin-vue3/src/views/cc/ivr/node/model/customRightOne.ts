/**
 * 自定义右侧单锚点节点模型（仅右出锚点）
 * 继承自 HtmlNodeModel，节点尺寸由 Vue 组件 HTML 内容自动撑开
 * 用于 IVR 流程中的开始节点，仅允许向右连出一条边
 */
import { HtmlNodeModel } from '@logicflow/core'

class CustomRightOne extends HtmlNodeModel {
  initNodeData(data: any) {
    super.initNodeData(data)
    this.text.draggable = false
    this.text.editable = false
  }

  /**
   * 强制从真实 DOM 同步节点尺寸
   * 画布缩放后，HtmlNodeModel 缓存的 width/height 与节点真实 offsetWidth/offsetHeight
   * 可能产生浮点数累积偏差，导致锚点位置、外轮廓和连线端点错位（视觉上"变形"）。
   * 在获取锚点前调用此方法，确保 model.width/height 与实际渲染尺寸一致。
   */
  syncSizeFromDom() {
    try {
      const h = (this as any).__htmlRootEl as HTMLElement | undefined
      if (!h) return
      const el = h.firstElementChild as HTMLElement | null
      if (!el) return
      const ow = el.offsetWidth
      const oh = el.offsetHeight
      if (ow && oh && (Math.abs(ow - this.width) > 0.5 || Math.abs(oh - this.height) > 0.5)) {
        this.width = ow
        this.height = oh
      }
    } catch (_) {
      // 尺寸同步失败时静默降级，使用缓存值
    }
  }

  getDefaultAnchor() {
    this.syncSizeFromDom()
    const { width, height, x, y, id } = this
    return [
      {
        x: x + width / 2,
        y,
        name: 'right',
        id: `${id}_1`
      }
    ]
  }

  getOutlineShape() {
    this.syncSizeFromDom()
    const { x, y, width, height } = this
    return {
      x: x - width / 2,
      y: y - height / 2,
      width,
      height,
      radius: 8
    }
  }

  getConnectedSourceRules() {
    const rules = super.getConnectedSourceRules()
    const singleConnectionRule = {
      message: '该节点只能有一个右连接线',
      validate: (_sourceNode: any, _targetNode: any, _sourceAnchor: any, _targetAnchor: any) => {
        const edges = _sourceNode.graphModel.edges.filter((edge: any) => edge.sourceNodeId === _sourceNode.id)
        if (edges.length >= 1) {
          return false
        }
        return true
      }
    }
    rules.push(singleConnectionRule)
    return rules
  }
}

export default CustomRightOne
