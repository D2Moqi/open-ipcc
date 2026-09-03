import { RectNodeModel } from '@logicflow/core'

/**
 * 自定义右侧锚点节点模型类
 * 继承自 RectNodeModel，用于创建只有右侧单个锚点的矩形节点
 * 这种节点通常用于表示流程中的起始节点或可以作为连线起点的节点
 */
class CustomNodeModel extends RectNodeModel {
  /**
   * 重写 getDefaultAnchor 方法，定义节点默认的锚点配置
   * 锚点是节点上用于连接边的点
   * @returns 包含单个锚点配置的数组
   */
  getDefaultAnchor() {
    // 从当前节点实例中解构出宽高和位置信息
    const { width, x, y, id } = this
    return [
      {
        // 计算锚点的 x 坐标：位于节点右侧中间位置
        x: x + width / 2,
        // 锚点的 y 坐标：与节点中心 y 坐标相同
        y,
        // 锚点的名称，用于标识锚点位置
        name: 'right',
        // 锚点的唯一标识，由节点 ID 和锚点索引组成
        id: `${id}_1`
        // 注意：与 customLeft.ts 不同，这里没有设置 edgeAddable: false
        // 因此此锚点默认既可以作为连线的起点，也可以作为终点
      }
    ]
  }

  /**
   * 重写 getConnectedTargetRules 方法，定义节点作为终点时的连接规则
   * 添加限制不允许其他节点连接到当前节点右侧锚点的规则
   * @returns 连接规则数组
   */
  getConnectedTargetRules() {
    const rules = super.getConnectedTargetRules()
    // 添加自定义规则：不允许其他节点连接到当前节点右侧锚点
    const forbidRightAnchorRule = {
      message: '不允许连接到该节点的右侧锚点',
      validate: (_sourceNode: any, _targetNode: any, _sourceAnchor: any, _targetAnchor: any) => {
        // 检查目标锚点是否为右侧锚点
        return _targetAnchor.name !== 'right'
      }
    }
    rules.push(forbidRightAnchorRule)
    return rules
  }
}

export default CustomNodeModel
