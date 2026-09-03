import { RectNodeModel } from '@logicflow/core'

const message = useMessage() // 消息弹窗

/**
 * 自定义 IVR 节点模型类
 * 扩展了 LogicFlow 的 RectNodeModel，用于自定义 IVR 流程节点的锚点样式、连接规则和默认锚点位置
 */
class CustomNodeBil extends RectNodeModel {
  /**
   * 获取锚点的样式配置
   * @param anchorInfo 锚点信息对象
   * @returns 包含样式配置的对象
   */
  getAnchorStyle(anchorInfo) {
    // 获取父类的锚点样式
    const style = super.getAnchorStyle(anchorInfo)
    // 设置锚点的边框颜色
    style.stroke = 'rgb(24, 125, 255)'
    // 设置锚点的半径
    style.r = 6
    // 确保 hover 对象存在，用于定义鼠标悬停时的样式
    if (!style.hover) {
      style.hover = {}
    }
    // 设置鼠标悬停时的锚点半径
    style.hover.r = 8
    // 设置鼠标悬停时的锚点填充颜色
    style.hover.fill = 'rgb(24, 125, 255)'
    // 设置鼠标悬停时的锚点边框颜色
    style.hover.stroke = 'rgb(24, 125, 255)'

    return style
  }

  /**
   * 获取源锚点的连接规则
   * 定义节点作为起点时的连接验证规则
   * @returns 连接规则数组
   */
  getConnectedSourceRules() {
    // 获取父类的连接规则
    const rules = super.getConnectedSourceRules()

    // 定义自定义的连接规则
    const getWayOnlyAsTarget = {
      validate: (source, sourceAnchor) => {
        // 过滤出与菜单相关的边
        const edgeArr = source.graphModel.edges.filter(
          (item) => item.sourceNodeId.indexOf('menu_') != -1
        )

        // 从锚点ID中提取按钮ID
        const buttonId = sourceAnchor.id.split('_')[0]

        // 检查是否已存在从该按钮ID出发的边
        const hasIndex = edgeArr.findIndex(
          (items) => items.sourceAnchorId.split('_')[0] == buttonId
        )

        // 验证规则1：按钮必须有值
        const isValid = source.properties.menuButtons[buttonId].buttonValue.length != 0
        if (!isValid) message.warning('请检查按键的值')

        // 验证规则2：锚点只能连接一次
        const isRepeat = hasIndex == -1
        if (!isRepeat) message.warning('锚点只能连接一次！')

        // 只有当两个验证规则都通过时，才允许连接
        return isValid && isRepeat
      }
    }

    // 为验证规则添加错误提示消息
    const ruleWithMessage = {
      ...getWayOnlyAsTarget,
      message: '请检查按键的值或锚点是否已连接'
    }

    // 将自定义规则添加到规则数组中
    rules.push(ruleWithMessage)
    return rules
  }

  /**
   * 获取节点的默认锚点配置
   * 根据节点的属性动态生成锚点位置
   * @returns 包含锚点配置的数组
   */
  getDefaultAnchor(): { x: number; y: number; id: string }[] {
    // 解构获取节点的基本属性
    const { width, x, y, id } = this
    // 获取节点属性中的菜单按钮配置
    const arr = this.properties.menuButtons as any
    // 存储右侧锚点的数组
    const rightArr: any[] = []

    // 创建左侧锚点（用于接收连接，不可作为起点）
    const anchors = [
      {
        x: x - width / 2,
        y,
        name: 'left',
        id: `${id}_0`,
        edgeAddable: false // 只能作为终点，不可作为起点
      }
    ]

    // 根据按钮数量计算右侧锚点的位置
    if (arr.length == 1) {
      // 单个按钮时，锚点居中显示
      arr.forEach((index: number) => {
        const obj = {
          x: x + width / 2,
          y: y - 10,
          name: 'right',
          id: `${index}_2`
        }
        rightArr.push(obj)
      })
    } else {
      // 多个按钮时，锚点按垂直方向均匀分布
      arr.forEach((index: number) => {
        const obj = {
          x: x + width / 2,
          y: y - 10 + 56 * index - 24 * (arr.length - 1),
          name: 'right',
          id: `${index}_2`
        }
        rightArr.push(obj)
      })
    }

    // 合并左侧锚点和右侧锚点数组
    const newArr = [...anchors, ...rightArr]
    // 过滤并类型转换后返回锚点配置数组
    return newArr.filter((item) => typeof item === 'object') as {
      x: number
      y: number
      id: string
    }[]
  }
}

// 导出自定义节点模型类
export default CustomNodeBil
