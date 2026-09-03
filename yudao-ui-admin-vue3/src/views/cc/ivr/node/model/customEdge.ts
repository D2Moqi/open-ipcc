import {BezierEdge, BezierEdgeModel, h} from '@logicflow/core'
import {useIvrStore} from '../../store/ivr'

/**
 * 自定义边缘组件 - CustomEdge
 * 用于IVR流程图中连接两个节点的自定义边，具有删除功能
 * 特点：
 * 1. 蓝色的贝塞尔曲线连接
 * 2. 线中间有删除图标，点击可删除该边
 */

// 获取IVR状态管理实例
const useStore = useIvrStore()

/**
 * 自定义边模型类
 * 负责定义边的样式和属性
 */
class CustomEdgeModel extends BezierEdgeModel {
  /**
   * 自定义边的样式
   * @returns {Object} 包含边样式的对象
   */
  getEdgeStyle() {
    const edgeStyle = super.getEdgeStyle()
    edgeStyle.stroke = '#407fff' // 设置边的颜色为蓝色
    return edgeStyle
  }

  /**
   * 自定义边的文本样式
   * 本实现中将文本设为透明，实际上隐藏了文本显示
   * @returns {Object} 包含文本样式的对象
   */
  getTextStyle() {
    const style = super.getTextStyle()
    style.color = 'transparent' // 文本颜色设为透明
    style.background = style.background || {} // 确保background对象存在
    style.background.fill = 'transparent' // 背景色设为透明
    style.textWidth = 1 // 设置文本宽度为最小
    style.fontSize = 0 // 设置字体大小为0
    return style
  }
}

/**
 * 自定义边视图类
 * 负责边的渲染逻辑，包括路径和删除按钮的绘制
 */
class CustomEdgeView extends BezierEdge {
  /**
   * 生成边的视图
   * 重写父类方法，添加删除按钮功能
   * @returns {Object} 包含边路径和删除按钮的组元素
   */
  getEdge() {
    const { model } = this.props // 获取边的模型数据
    const path = super.getEdge() // 调用父类方法获取基础路径
    const pathData = path.props.d // 获取路径的d属性（SVG路径描述）

    // 计算路径长度和中点坐标，用于放置删除按钮
    const pathLength = this.getPathLength(pathData) // 获取路径总长度
    const halfLength = pathLength / 2 // 计算中点位置
    const centerPoint = this.getPointAtLength(pathData, halfLength) // 获取中点坐标

    // 创建一个组元素，包含路径和删除图标
    return h('g', {}, [
      // 渲染路径
      path,
      // 渲染删除图标，确保它在路径之后，以便覆盖在其上方
      h(
        'g',
        {
          style: {
            cursor: 'pointer' // 鼠标悬停时显示指针样式
          },
          onClick: () => {
            // 点击事件：删除当前边
            useStore.getLf.deleteEdge(model.id)
          }
        },
        [
          // 使用foreignObject元素包裹HTML内容
          h(
            'foreignObject',
            {
              x: centerPoint.x - 16, // 定位：X坐标 - 图标宽度的一半
              y: centerPoint.y - 16, // 定位：Y坐标 - 图标高度的一半
              width: '32', // 外部对象宽度
              height: '32' // 外部对象高度
            },
            [
              // 渲染删除图标
              h('img', {
                style: {
                  display: 'flex',
                  justifyContent: 'center',
                  alignItems: 'center',
                  width: '32px',
                  height: '32px',
                  color: '#FF4D4F',
                  borderRadius: '50%', // 圆形背景
                  background: '#ffffff', // 白色背景
                  zIndex: 2 // 确保图标在顶层显示
                },
                src: 'https://scrm.jzsaas.com/close.svg' // 删除图标的SVG源文件
              })
            ]
          )
        ]
      )
    ])
  }

  /**
   * 计算SVG路径的总长度
   * @param {string} pathData - SVG路径的d属性值
   * @returns {number} 路径的总长度
   */
  getPathLength(pathData) {
    // 创建临时的SVG路径元素用于计算长度
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path')
    path.setAttribute('d', pathData) // 设置路径数据
    return path.getTotalLength() // 获取路径总长度
  }

  /**
   * 获取SVG路径上指定长度位置的坐标点
   * @param {string} pathData - SVG路径的d属性值
   * @param {number} length - 从路径起点开始的长度
   * @returns {Object} 包含x和y坐标的对象
   */
  getPointAtLength(pathData, length) {
    // 创建临时的SVG路径元素用于计算点坐标
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path')
    path.setAttribute('d', pathData) // 设置路径数据
    const point = path.getPointAtLength(length) // 获取指定长度处的点
    return { x: point.x, y: point.y } // 返回坐标对象
  }

  /**
   * 自定义边的附加元素
   * 本实现中不添加任何附加元素
   * @returns {Object} 空的组元素
   */
  getAppend() {
    return h('g', {}, [])
  }
}

/**
 * 导出自定义边配置
 * 供LogicFlow注册和使用
 */
export default {
  type: 'CustomEdge', // 边类型标识
  view: CustomEdgeView, // 边的视图类
  model: CustomEdgeModel // 边的模型类
}
