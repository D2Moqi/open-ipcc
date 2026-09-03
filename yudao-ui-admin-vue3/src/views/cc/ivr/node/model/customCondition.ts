/**
 * 判断器节点动态锚点模型
 * 继承自 LogicFlow 的 HtmlNodeModel，节点尺寸由 HTML 内容自动撑开，
 * 根据 properties.branches 动态生成右侧分支锚点
 * 左侧锚点只入不出，右侧每个分支一个锚点且每个分支仅允许连出一条边
 * 分支右锚点 Y 坐标与对应 branch-item DOM 的中心对齐（优先使用组件上报的 branchCenters 缓存）
 */
import { HtmlNodeModel } from '@logicflow/core'

/** 分支类型：IF 主条件、ELSE_IF 否则如果、ELSE 否则 */
type BranchType = 'IF' | 'ELSE_IF' | 'ELSE'

/** 单个分支配置 */
interface Branch {
  branchType: BranchType
  matchType?: string
  conditions?: any[]
}

class CustomCondition extends HtmlNodeModel {
  /**
   * 分支中心 Y 坐标缓存（相对节点顶部的偏移量，px）
   * 由 condition.vue 组件通过 setBranchCenters 上报，
   * 用于精确对齐右侧锚点与每个 branch-item 卡片中心；
   * 若未上报则回退到均匀分布算法。
   */
  private branchCenters: number[] = []

  initNodeData(data: any) {
    super.initNodeData(data)
    // 不设置固定宽高，由 HtmlNodeModel 根据 Vue 组件 DOM 内容自动撑开
    this.text.draggable = false
    this.text.editable = false
  }

  /**
   * 设置分支中心 Y 偏移缓存（由 condition.vue 组件在渲染和尺寸变化时调用）
   * 并触发本节点所有出边根据新锚点位置重新计算路径，
   * 解决新增/删除分支后锚点Y位置变化但连接线停留在旧位置导致的"线点错位"问题
   * @param centers - 每个分支的中心 Y 偏移（相对节点根元素顶部，px）；无效值填 -1
   */
  setBranchCenters(centers: number[]) {
    if (!Array.isArray(centers)) return
    this.branchCenters = centers.slice()
    this._refreshOutgoingEdgePaths()
  }

  /**
   * 遍历本节点所有出边，根据当前锚点（getDefaultAnchor 最新计算结果）
   * 重置起点坐标并触发路径重绘。LogicFlow 边模型在首次创建后会缓存 startPoint，
   * 节点尺寸/锚点位置变化不会自动同步到边，需手动刷新。
   */
  private _refreshOutgoingEdgePaths() {
    try {
      const graphModel = (this as any).graphModel
      if (!graphModel || !graphModel.edges) return
      // 用最新数据重新计算所有锚点（必须在syncSizeFromDom之后，才能拿到正确width/height）
      const anchors = this.getDefaultAnchor()
      const anchorMap = new Map<string, { x: number; y: number; id: string }>()
      for (const a of anchors) anchorMap.set(a.id, a)
      const edges: any[] = graphModel.edges
      for (const edge of edges) {
        if (!edge || edge.sourceNodeId !== this.id) continue
        const anchor = anchorMap.get(edge.sourceAnchorId)
        if (!anchor) continue
        // 兼容不同 LogicFlow 版本的边端点更新 API
        try {
          if (typeof edge.updateStartPoint === 'function') {
            edge.updateStartPoint(anchor)
          } else if (edge.startPoint) {
            edge.startPoint.x = anchor.x
            edge.startPoint.y = anchor.y
          }
        } catch (_) { /* 单条边更新失败不影响其他边 */ }
        // 触发路径重绘（按存在性依次尝试）
        try {
          if (typeof edge.initPath === 'function') edge.initPath()
          else if (typeof edge.updatePath === 'function') edge.updatePath()
        } catch (_) { /* 路径重绘失败静默降级 */ }
      }
      // 触发 LogicFlow 内部视图层重绘（异步批量执行，避免连续调用多次刷新）
      if (typeof graphModel.toFront === 'function' || (this as any).graphModel?.eventCenter) {
        try { (this as any).graphModel.eventCenter?.emit('custom:anchors-updated', { nodeId: this.id }) } catch (_) {}
      }
    } catch (_) {
      // 边重绘失败时静默降级：锚点和边可能暂时错位，但节点尺寸/属性更新不受影响
    }
  }

  /**
   * 强制从真实 DOM 同步节点尺寸
   * 画布缩放后，HtmlNodeModel 缓存的 width/height 与节点真实 offsetWidth/offsetHeight
   * 可能产生浮点数累积偏差，导致判断器节点右侧分支锚点与实际位置错位（视觉上"变形"）。
   * 在获取锚点/轮廓前调用此方法，确保 model.width/height 与实际渲染尺寸一致。
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
        // 尺寸变化后锚点Y位置会整体偏移（锚点相对节点中心计算），需重绘出边
        this._refreshOutgoingEdgePaths()
      }
    } catch (_) {
      // 尺寸同步失败时静默降级，使用缓存值
    }
  }

  /**
   * 根据分支配置动态生成锚点
   * 左侧1个入锚点（edgeAddable:false，只入不出），右侧按分支数生成出锚点
   * 右锚点优先使用组件上报的 branchCenters，否则使用均匀分布算法
   * 右锚点 id 格式 `${branchIndex}_right`
   * @returns 锚点数组
   */
  getDefaultAnchor() {
    this.syncSizeFromDom()
    const { width, height, x, y, id } = this
    const branches: Branch[] = (this.properties.branches as Branch[]) || []
    const anchors: any[] = []

    // 左侧入锚点：只允许作为连线终点
    anchors.push({
      x: x - width / 2,
      y: y,
      name: 'left',
      id: `${id}_left`,
      edgeAddable: false
    })

    // 如果没有分支数据（节点刚创建），默认返回2个右锚点（IF + ELSE）
    const branchList = branches.length > 0 ? branches : [
      { branchType: 'IF' as BranchType },
      { branchType: 'ELSE' as BranchType }
    ]
    const branchCount = branchList.length

    // 计算 ELSE_IF 出现的累计序号
    let elseIfCount = 0
    branchList.forEach((branch, index) => {
      let branchName: string
      if (branch.branchType === 'IF') {
        branchName = 'IF'
      } else if (branch.branchType === 'ELSE_IF') {
        elseIfCount += 1
        branchName = `ELSE_IF_${elseIfCount}`
      } else {
        branchName = 'ELSE'
      }

      let yPos: number
      // 优先使用组件上报的分支中心 Y 偏移（相对节点顶部）
      const cachedCenter = this.branchCenters ? this.branchCenters[index] : -1
      if (cachedCenter && cachedCenter > 0 && cachedCenter < this.height) {
        // nodeModel 坐标系：节点中心为 (x, y)，顶部 y = node.y - height/2
        // 所以分支中心的 model Y = node.y - height/2 + cachedCenter
        yPos = y - height / 2 + cachedCenter
      } else {
        // 回退：均匀分布算法
        const topPadding = 50
        const bottomPadding = 30
        const usableHeight = Math.max(height - topPadding - bottomPadding, 40)
        yPos = branchCount === 1
          ? y
          : y - usableHeight / 2 + (usableHeight * index) / (branchCount - 1)
      }

      anchors.push({
        x: x + width / 2,
        y: yPos,
        name: branchName,
        id: `${id}_${index}_right`,
        edgeAddable: true
      })
    })

    return anchors
  }

  /**
   * 获取节点外框轮廓，用于选中高亮和连线计算
   */
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

  /**
   * 起点连接规则：限制每个右侧分支锚点只能连出一条边
   */
  getConnectedSourceRules() {
    const rules = super.getConnectedSourceRules()
    const singleBranchConnectionRule = {
      message: '每个分支只能连接一个组件',
      validate: (_sourceNode: any, _targetNode: any, _sourceAnchor: any) => {
        const edges = _sourceNode.graphModel.edges.filter(
          (edge: any) =>
            edge.sourceNodeId === _sourceNode.id && edge.sourceAnchorId === _sourceAnchor.id
        )
        return edges.length === 0
      }
    }
    rules.push(singleBranchConnectionRule)
    return rules
  }

  /**
   * 终点连接规则：禁止其他节点连入本节点的右侧分支锚点
   */
  getConnectedTargetRules() {
    const rules = super.getConnectedTargetRules()
    const forbidRightAnchorRule = {
      message: '不允许连接到该节点的右侧锚点',
      validate: (_sourceNode: any, _targetNode: any, _sourceAnchor: any, _targetAnchor: any) => {
        return !_targetAnchor.id.includes('_right')
      }
    }
    rules.push(forbidRightAnchorRule)
    return rules
  }
}

export default CustomCondition
