/**
 * 自定义双锚点矩形节点模型
 * 用于 IVR 流程设计中的特定节点类型
 * 特点：左侧锚点不可作为连线起点，只能作为终点
 */
import { RectNodeModel } from '@logicflow/core'

/**
 * CustomNodeBil 类
 * 继承自 RectNodeModel，重写了默认锚点的定义
 */
class CustomNodeBil extends RectNodeModel {
  /**
   * 重写 getDefaultAnchor 方法，定义节点的默认锚点位置和属性
   * @returns {Array} 包含两个锚点对象的数组
   */
  getDefaultAnchor() {
    // 解构当前节点的属性：宽度、x坐标、y坐标和ID
    const { width, x, y, id } = this

    // 返回左右两个锚点的配置
    return [
      {
        x: x - width / 2, // 左侧锚点的x坐标（节点左边缘）
        y, // 左侧锚点的y坐标（节点垂直中心）
        name: 'left', // 锚点名称：左侧
        id: `${id}_0`, // 锚点唯一ID：节点ID_0
        edgeAddable: false // 禁用从该锚点添加连线（只能作为终点）
      },
      {
        x: x + width / 2, // 右侧锚点的x坐标（节点右边缘）
        y, // 右侧锚点的y坐标（节点垂直中心）
        name: 'right', // 锚点名称：右侧
        id: `${id}_1` // 锚点唯一ID：节点ID_1
        // 右侧锚点默认允许添加连线（可作为起点和终点）
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

export default CustomNodeBil
