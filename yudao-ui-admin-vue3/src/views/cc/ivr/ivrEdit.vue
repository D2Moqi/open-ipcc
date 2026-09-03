<template>
  <!-- IVR 流程编辑器主容器 -->
  <div class="ivr-edit">
    <!-- 顶部标题栏 -->
    <div class="ivr-title">
      <el-row justify="space-between">
        <el-col :span="6" style="align-items: center; vertical-align: middle">
          <!-- 左侧标题信息 -->
          <span class="size-16 mr-10">{{ name }}</span>
          <span class="size-14">保存时间:{{ formatTime(formState.updateTime, 'yyyy-MM-dd HH:mm:ss') }}</span>
        </el-col>
        <el-col :span="6" />
        <el-col :span="6" style="text-align: right">
          <!-- 添加组件弹窗 -->
          <el-popover placement="bottom" v-model:open="visible" trigger="click" :width="300" popper-class="ivr-node-popover">
            <span class="node-title">基础组件</span>
            <el-divider style="margin: 10px 0" />
            <div class="node-list">
              <!-- 组件列表：支持点击添加（默认位置）和拖拽添加（指定位置）两种交互 -->
              <div
                v-for="item in nodeList"
                :key="item.id"
                class="node-li"
                @pointerdown="handleDragStart($event, item)"
              >
                <div class="node-content">
                  <div class="node-icon" :style="{ background: item.bgc }">
                    <img :src="item.img" alt="组件图标" class="node-img" />
                  </div>
                  <div class="node-des">
                    <h4>{{ item.name }}</h4>
                    <h5>{{ item.des }}</h5>
                  </div>
                </div>
              </div>
            </div>
            <template #reference>
              <el-button class="mr-20 add-comp-btn"> 添加组件 </el-button>
            </template>
          </el-popover>
          <!-- 保存按钮 -->
          <el-button type="primary" @click="submit">保存</el-button>
        </el-col>
      </el-row>
    </div>
    <!-- 流程图容器 -->
    <div ref="containerRef" id="graph" class="viewport"></div>
    <!-- LogicFlow 节点渲染容器 -->
    <TeleportContainer :flow-id="flowId" />
  </div>
</template>

<script setup lang="ts">
import LogicFlow from '@logicflow/core' // 导入 LogicFlow 核心库
import { register, getTeleport } from '@logicflow/vue-node-registry' // 导入 Vue 节点注册相关功能
import '@logicflow/core/es/index.css' // 导入 LogicFlow 样式

const message = useMessage() // 消息弹窗
import { CcIvrApi } from '@/api/cc/ivr' // IVR 相关 API
import { formatTime } from '@/utils' // 时间格式化工具
import { generateRandomString } from './utils/node' // 随机字符串生成工具
import StartNode from './node/start.vue' // 开始节点组件
import EndNode from './node/end.vue' // 结束节点组件
import { useIvrStore } from './store/ivr' // IVR 状态管理
import CustomEdge from './node/model/customEdge' // 自定义边组件
import CustomLeft from './node/model/customLeft' // 单左锚点节点模型
import CustomRightOne from './node/model/customRightOne' // 单右锚点节点模型(只有一个右连接线）
import CustomBilRightOne from './node/model/customBilRightOne' // 双边锚点节点模型(只有一个右连接线）
import { NodeType } from '@/views/cc/ivr/consts/ivrEnum' // 节点类型枚举
import PlayBackNode from './node/playback.vue' // 放音节点组件
import TransferNode from './node/transfer.vue' // 转移节点组件
import ReceiveNode from './node/receive.vue' // 收号节点组件
import ConditionNode from './node/condition.vue' // 判断器节点组件
import MethodNode from './node/method.vue' // 方法节点组件
import AiNode from './node/ai.vue' // AI 对话节点组件
import CustomCondition from './node/model/customCondition' // 判断器节点动态锚点模型
import CustomNodeView from './node/model/customNodeView' // 自定义节点视图（修复缩放后尺寸测量错误）
import './node/node-common.css' // 引入节点通用样式
import { installIvrFormGuard } from './node/utils/formEventGuard' // 表单交互全局守护者（解决下拉框单击、输入框单击聚焦问题）

/**
 * 防抖函数：在指定延迟时间内重复调用只执行最后一次
 * 用于 graph:transform 事件，避免缩放过程中频繁触发节点尺寸同步导致抖动
 * @param fn - 需要防抖的函数
 * @param delay - 延迟时间（毫秒），默认 80ms
 */
function debounce<T extends (...args: any[]) => void>(fn: T, delay: number = 80): T {
  let timer: number | null = null
  return function (this: any, ...args: Parameters<T>) {
    if (timer !== null) {
      clearTimeout(timer)
    }
    timer = window.setTimeout(() => {
      fn.apply(this, args)
      timer = null
    }, delay)
  } as T
}

/**
 * 强制同步所有节点尺寸
 * 从真实 DOM 读取 offsetWidth/offsetHeight 并写回节点模型，
 * 消除缩放后 model.width/height 与实际渲染尺寸的累积偏差
 * @param lfInstance - LogicFlow 实例
 */
function syncAllNodesSize(lfInstance: any) {
  try {
    const lfAny: any = lfInstance
    const graphModel = lfAny.graphModel
    if (!graphModel?.nodes) return
    const nodes = graphModel.nodes
    for (let i = 0, len = nodes.length; i < len; i++) {
      const nodeModel = nodes[i]
      try {
        if (typeof (nodeModel as any).syncSizeFromDom === 'function') {
          ;(nodeModel as any).syncSizeFromDom()
        } else {
          // 兜底：未定义 syncSizeFromDom 时，使用视图层缓存的 DOM 引用手动同步
          const h = (nodeModel as any).__htmlRootEl as HTMLElement | undefined
          if (!h) continue
          const el = h.firstElementChild as HTMLElement | null
          if (!el) continue
          const ow = el.offsetWidth
          const oh = el.offsetHeight
          if (ow && oh && (Math.abs(ow - nodeModel.width) > 0.5 || Math.abs(oh - nodeModel.height) > 0.5)) {
            nodeModel.width = ow
            nodeModel.height = oh
          }
        }
      } catch (_) {
        // 单个节点同步失败不影响其他节点
      }
    }
  } catch (_) {
    // 尺寸同步异常时静默降级，不阻塞画布交互
  }
}

// 获取 IVR 状态管理实例
const useStore = useIvrStore()

// 计算属性：获取节点列表
const nodeList = computed(() => {
  return useStore.getNodeList
})
// 路由
const route = useRoute()

// 获取 LogicFlow 的 Teleport 容器
const TeleportContainer = getTeleport()

// 状态定义
const visible = ref(false) // 组件弹窗显示状态
const name = route.params.name
const formState = reactive({
  id: route.params.id, // 流程ID
  flowData: '', // 流程图数据
  updateTime: '' // 更新时间
})
const containerRef = ref(null) // 流程图容器引用
const flowId = ref('') // 流程图ID

/**
 * 全局 IVR 表单交互守护者（v2）：解决下拉框/级联/输入框需要双击才能激活的问题
 * 设计思路参见：node/utils/formEventGuard.ts installIvrFormGuard
 *  - pointerdown 不阻断事件冒泡 → Element Plus popperManager 全局监听正常收到，弹层能打开 ✅
 *  - 仅在表单交互期间拦截 pointermove/mousemove（window capture阶段）→ LogicFlow 收不到 move，就不启动拖拽偏移 ✅
 */
let _uninstallIvrFormGuard: (() => void) | null = null

// 组件卸载：移除全局监听器
onBeforeUnmount(() => {
  try { _uninstallIvrFormGuard?.() } catch (_) {}
})

// 组件挂载后初始化
onMounted(() => {
  // 在 LF 初始化前安装全局表单交互守护者
  if (containerRef.value) {
    _uninstallIvrFormGuard = installIvrFormGuard(containerRef.value)
  }
  // 如果容器引用存在，初始化 LogicFlow
  if (containerRef.value) {
    const lf = new LogicFlow({
      container: containerRef.value, // 容器元素
      height: window.innerHeight - 57, // 高度，减去标题栏高度
      multipleSelectKey: 'ctrl', // 多选快捷键
      nodeTextEdit: false, // 禁用节点文本编辑
      edgeTextEdit: false, // 禁用边文本编辑
      nodeSelectedOutline: false, // 禁用节点选中边框
      keyboard: {
        enabled: false // 禁用键盘删除节点
      },
      outline: true, // 启用轮廓功能
      partial: false, // 关闭部分渲染，避免多次缩放后节点缓存尺寸与实际 DOM 不一致
      background: {
        color: '#FFFFFF' // 背景颜色（始终白色）
      },
      grid: {
        size: 20,
        type: 'dot',
        config: {
          color: '#e5e7eb',
          thickness: 1
        }
      },
      edgeTextDraggable: true, // 启用边文本拖动
      edgeType: 'bezier', // 默认边类型为贝塞尔曲线
      style: {
        // 样式配置
        anchor: {
          // 锚点样式
          r: 6, // 半径
          fill: '#4080ff', // 填充颜色
          stroke: '#ffffff', // 边框颜色
          strokeWidth: 2,
          hover: {
            fill: '#4080ff', // 悬停填充颜色
            r: 7
          }
        },
        edgeText: {
          color: '#606266',
          fontSize: 12,
          background: { fill: '#ffffff' }
        },
        outline: {
          stroke: '#4080ff',
          strokeWidth: 1,
          hover: {
            stroke: '#4080ff'
          }
        }
      }
    })

    // 注册自定义 Vue 节点
    register(
      {
        type: NodeType.START_NODE, // 开始节点类型
        component: StartNode, // 开始节点组件
        view: CustomNodeView, // 自定义视图（修复缩放后尺寸测量错误）
        model: CustomRightOne
      },
      lf
    )
    register(
      {
        type: NodeType.END_NODE, // 结束节点类型
        component: EndNode, // 结束节点组件
        view: CustomNodeView, // 自定义视图（修复缩放后尺寸测量错误）
        model: CustomLeft
      },
      lf
    )
    register(
      {
        type: NodeType.PLAYBACK_NODE, // 放音节点类型
        component: PlayBackNode, // 放音节点组件
        view: CustomNodeView, // 自定义视图（修复缩放后尺寸测量错误）
        model: CustomBilRightOne
      },
      lf
    )
    register(
      {
        type: NodeType.TRANSFER_NODE, // 转接节点类型
        component: TransferNode, // 转接节点组件
        view: CustomNodeView, // 自定义视图（修复缩放后尺寸测量错误）
        model: CustomBilRightOne
      },
      lf
    )
    register(
      {
        type: NodeType.RECEIVE_NODE, // 收号节点类型
        component: ReceiveNode, // 收号节点组件
        view: CustomNodeView, // 自定义视图（修复缩放后尺寸测量错误）
        model: CustomBilRightOne
      },
      lf
    )
    register(
      {
        type: NodeType.CONDITION_NODE, // 判断器节点类型
        component: ConditionNode, // 判断器节点组件
        view: CustomNodeView, // 自定义视图（修复缩放后尺寸测量错误）
        model: CustomCondition
      },
      lf
    )
    register(
      {
        type: NodeType.METHOD_NODE, // 方法节点类型
        component: MethodNode, // 方法节点组件
        view: CustomNodeView, // 自定义视图（修复缩放后尺寸测量错误）
        model: CustomBilRightOne
      },
      lf
    )
    register(
      {
        type: NodeType.AI_NODE, // AI 对话节点类型
        component: AiNode, // AI 对话节点组件
        view: CustomNodeView, // 自定义视图（修复缩放后尺寸测量错误）
        model: CustomBilRightOne
      },
      lf
    )

    // 监听图渲染完成事件，获取流程ID
    lf.on('graph:rendered', ({ graphModel }) => {
      flowId.value = graphModel?.flowId || ''
    })

    // 添加自定义行为：鼠标悬停线条时显示删除按钮
    lf.on('edge:mouseenter', (data) => {
      const edgeModelData = data.data
      if (edgeModelData.type === 'bezier') {
        lf.changeEdgeType(edgeModelData.id, 'CustomEdge')
      }
    })

    // 鼠标离开线条时恢复默认边类型
    lf.on('edge:mouseleave', (data) => {
      const edgeModelData = data.data
      lf.changeEdgeType(edgeModelData.id, 'bezier')
    })

    // 拖拽添加节点完成事件：关闭组件弹窗
    lf.on('node:dnd-add', () => {
      visible.value = false
    })

    // 注册自定义边组件
    lf.register(CustomEdge)

    // 防抖版的尺寸同步：缩放过程中（滚轮/手势）高频触发 graph:transform，
    // 若每次都同步尺寸会引发抖动与性能开销，因此仅在缩放停止 80ms 后同步一次
    const debouncedSyncAll = debounce(() => syncAllNodesSize(lf), 80)

    // 画布缩放/平移后（防抖）：强制所有节点重新从真实 DOM 同步尺寸，
    // 避免多次缩放后 HtmlNodeModel 缓存的 width/height 与实际渲染尺寸
    // 产生浮点数累积偏差，进而导致锚点、连线端点和选中轮廓错位（视觉上"变形"）。
    lf.on('graph:transform', () => {
      debouncedSyncAll()
    })

    // 节点添加后立即同步一次尺寸：
    // 新节点的 Vue 组件渲染与 HtmlNodeModel 尺寸初始化之间存在时序差，
    // 若不主动同步会导致首次渲染后 model.width/height 为默认值（如 100x100），
    // 锚点位置和连线端点就会与真实节点边界错位。
    lf.on('node:add', ({ data }: any) => {
      try {
        // 延迟一帧等待 Vue 组件完成 DOM 渲染，再同步尺寸
        requestAnimationFrame(() => {
          try {
            const nodeModel = (lf as any).graphModel.getNodeModelById(data?.id)
            if (!nodeModel) return
            if (typeof nodeModel.syncSizeFromDom === 'function') {
              nodeModel.syncSizeFromDom()
            } else {
              const h = nodeModel.graphModel?.flowChart?.getHtmlElement(nodeModel.id)
              if (!h) return
              const el = h.firstElementChild as HTMLElement | null
              if (!el) return
              const ow = el.offsetWidth
              const oh = el.offsetHeight
              if (ow && oh && (Math.abs(ow - nodeModel.width) > 0.5 || Math.abs(oh - nodeModel.height) > 0.5)) {
                nodeModel.width = ow
                nodeModel.height = oh
              }
            }
          } catch (_) {
            // 单个节点同步失败不影响其他节点
          }
        })
      } catch (_) {
        // 尺寸同步异常时静默降级
      }
    })

    // 画布整体渲染完成后同步一次：解决首次加载流程数据时，
    // 所有节点批量渲染后尺寸未对齐的问题
    // 注意：不再在这里调用 fitView——feedbackData 中已用 setTimeout(300ms) 保证节点 Vue 组件挂载完成后再 fitView，
    // 此处 rAF 时机过早（Vue 组件尚未 mounted），fitView 会在节点 DOM 为 0 尺寸时计算 bounds 得到错误结果，
    // 然后被后续 graph:transform 覆盖回 identity transform，导致所有节点位于视口外。
    lf.on('graph:rendered', () => {
      try {
        requestAnimationFrame(() => {
          syncAllNodesSize(lf)
          // 第二次 rAF 兜底：兼容某些浏览器 DOM layout 延迟（如Safari）
          requestAnimationFrame(() => syncAllNodesSize(lf))
        })
      } catch (_) {}
    })

    // 渲染空数据，初始化画布
    lf.render({})

    // 保存 LogicFlow 实例到状态管理中
    useStore.setLfRef(lf)
    // 加载并显示数据
    feedbackData()
  }
})

/**
 * 回显数据方法
 * 从服务器获取 IVR 流程数据并在编辑器中显示
 */
const feedbackData = async () => {
  const res = await CcIvrApi.getDetail(formState.id)
  const { flowData, updateTime } = res
  Object.assign(formState, { flowData, updateTime })
  const data = JSON.parse(flowData)
  const lf = useStore.getLf as any
  // 如果有流程数据，渲染流程图；否则创建默认的开始和结束节点
  if (data && data.length !== 0) {
    lf.render(data)
    /**
     * 渲染后校正视图时序说明：
     * 1. lf.render(data) 是异步的：设置节点/边数据 → 派发 graph:rendered → 异步挂载HtmlNode(Vue组件)
     * 2. Vue 组件挂载（mounted）本身又是异步的（nextTick），组件内部会调用 setProperties、syncSizeFromDom
     *    这些操作可能会二次触发 graph:transform 重置 transformModel（回到 0,0,1）
     * 3. 因此 rAF 时机过早（组件尚未挂载），fitView 执行时节点DOM还没渲染好，LF计算的bounds为0或初始值，
     *    导致 fitView 不产生有效平移/缩放，transform 仍为 identity，所有节点位于视口外（视觉上“样式错乱、内容显示不全”）
     * 4. 直接用 fitView 自动缩放会把节点压缩到 ~40% 缩放，导致内容过小看不清。
     *    正确做法：固定缩放到 100%（zoom=1），再定位第一个节点到视口左上合适位置，用户可以自由滚动/缩放查看
     */
    setTimeout(() => {
      try {
        const container = lf.container || lf.containerRef
        const viewW = container?.clientWidth || window.innerWidth
        const viewH = container?.clientHeight || window.innerHeight
        // 1) 先重置缩放到 100%（避免上次残留缩放状态）
        if (typeof lf.resetZoom === 'function') {
          lf.resetZoom()
        }
        // 2) 定位最左节点（start-node）到视口左侧合适位置
        const nodes = lf.graphModel?.nodes || []
        if (nodes.length > 0) {
          // 找开始节点优先，否则取x最小的
          let anchor = nodes.find((n: any) => n.type === 'start-node')
          if (!anchor) {
            anchor = nodes.reduce((a: any, b: any) => (a.x < b.x ? a : b))
          }
          // 屏幕坐标 = 画布坐标 * scale + TRANSLATE
          // 目标：锚点节点的左边缘在屏幕 targetScreenX 处，顶部在 targetScreenY 处
          const tm = lf.graphModel.transformModel
          const scale = tm.SCALE_X
          const targetScreenX = 80
          const targetScreenY = Math.max(80, (viewH - (anchor.height || 280)) / 2 - 40)
          const modelLeftX = anchor.x - (anchor.width || 360) / 2
          const modelTopY = anchor.y - (anchor.height || 280) / 2
          tm.TRANSLATE_X = targetScreenX - modelLeftX * scale
          tm.TRANSLATE_Y = targetScreenY - modelTopY * scale
          // 3) 通过 setView(getView()) 触发 LF 内部重渲染，让 SVG g 元素与HTML层同步transform
          if (typeof lf.setView === 'function' && typeof lf.getView === 'function') {
            const view = lf.getView()
            lf.setView(view)
          }
        }
      } catch (_) {}
      // 同步节点尺寸（根据真实DOM）；syncAllNodesSize 需等Vue mounted，再用两重 rAF 兜底
      requestAnimationFrame(() => {
        try { syncAllNodesSize(lf) } catch (_) {}
        requestAnimationFrame(() => {
          try { syncAllNodesSize(lf) } catch (_) {}
        })
      })
    }, 300)
  } else {
    // 默认开始和结束节点
    // 确保节点定义存在
    const startNode = useStore.getNodes[NodeType.START_NODE]
    const endNode = useStore.getNodes[NodeType.END_NODE]
    if (startNode && endNode) {
      // 添加开始节点
      const startNodeId = NodeType.START_NODE + '_' + generateRandomString(6)
      useStore.getLf.addNode({
        ...startNode,
        id: startNodeId,
        x: 200,
        y: 300
      })
      // 添加结束节点
      const endNodeId = NodeType.END_NODE + '_' + generateRandomString(6)
      useStore.getLf.addNode({
        ...endNode,
        id: endNodeId,
        x: 900,
        y: 300
      })
      // 连接开始节点和结束节点
      useStore.getLf.addEdge({
        sourceNodeId: startNodeId,
        targetNodeId: endNodeId,
        sourceAnchorId: 'right',
        targetAnchorId: 'left'
      })
    } else {
      message.error('缺少默认节点配置')
    }
  }
}

/**
 * 保存流程方法
 * 将当前编辑的 IVR 流程保存到服务器
 */
const submit = async () => {
  const lf = useStore.getLf
  if (lf) {
    // 保存前强制同步所有节点尺寸，确保导出的节点 width/height
    // 与真实 DOM 渲染尺寸一致，避免下次加载时尺寸偏差
    syncAllNodesSize(lf)
    // 获取当前流程图数据
    const lfData = lf.getGraphData()

    // 处理每条边，添加事件标识
    lfData.edges.forEach((item) => {
      // 判断器节点出边特殊处理：根据 sourceAnchorId 解析分支标识
      const sourceNode = lfData.nodes.find(n => n.id === item.sourceNodeId)
      if (sourceNode && sourceNode.type === NodeType.CONDITION_NODE) {
        // sourceAnchorId 格式为 "${branchIndex}_right"
        const branchIndex = parseInt(item.sourceAnchorId?.split('_')[0] || '0')
        const branches = sourceNode.properties?.branches || []
        const branch = branches[branchIndex]
        if (branch) {
          let branchLabel = ''
          if (branch.branchType === 'IF') {
            branchLabel = 'IF'
          } else if (branch.branchType === 'ELSE_IF') {
            // 计算 ELSE IF 序号
            let elseIfCount = 0
            for (let i = 0; i <= branchIndex; i++) {
              if (branches[i].branchType === 'ELSE_IF') elseIfCount++
            }
            branchLabel = 'ELSE_IF_' + elseIfCount
          } else if (branch.branchType === 'ELSE') {
            branchLabel = 'ELSE'
          }
          item.text = branchLabel
          item.event = 'next_' + branchLabel
        }
      } else if (item.text) {
        item.event = 'next_' + item.text.value
      } else {
        if (item.targetNodeId) item.event = 'next'
      }
    })

    // 保存流程图数据到表单状态
    formState.flowData = JSON.stringify(lfData)
    // 调用 API 保存数据
    await CcIvrApi.editIvr(formState).then((res) => {
      if (res) {
        message.success('保存成功')
        // 回显数据
        feedbackData()
      } else {
        message.error('保存失败')
      }
    })
      .catch(() => {
        message.error('保存失败')
      })
  }
}

/**
 * 组件项鼠标按下处理：通过移动距离阈值区分"点击添加"与"拖拽添加"
 * - 移动距离 < 5px：视为点击，释放鼠标时将节点添加到画布默认位置并关闭弹窗
 * - 移动距离 >= 5px：视为拖拽，调用 LogicFlow Dnd 插件，节点添加到鼠标释放位置
 * 开始/结束节点全局唯一：若画布中已存在同类型节点，则提示并阻止添加
 * @param e - 鼠标按下事件，用于获取初始坐标
 * @param item - 要添加的节点配置项
 */
const handleDragStart = (e, item) => {
  // 开始/结束节点全局唯一校验：画布中已存在同类型节点时阻止添加
  if (item.type === NodeType.START_NODE || item.type === NodeType.END_NODE) {
    const existCount = useStore.getLf.graphModel.nodes.filter(
      (n) => n && n.type === item.type
    ).length
    if (existCount > 0) {
      const typeName = item.type === NodeType.START_NODE ? '开始' : '结束'
      message.warning(`只能存在一个${typeName}组件`)
      visible.value = false
      return
    }
  }

  // 深拷贝节点配置，避免修改原数据
  const obj = JSON.parse(JSON.stringify(useStore.getNodes[item.type]))
  // 为节点生成唯一 ID
  obj.id = useStore.getNodes[item.type].id + generateRandomString(6)
  // 移除固定宽高，让HtmlNodeModel自动根据内容确定尺寸
  delete obj.properties.width
  delete obj.properties.height
  delete obj.properties.digits
  delete obj.properties.result

  // 记录鼠标按下时的坐标，用于计算移动距离
  const startX = e.clientX
  const startY = e.clientY
  let dragStarted = false

  // 指针移动监听：移动距离超过阈值时启动 Dnd 拖拽
  const onPointerMove = (moveEvent) => {
    if (!dragStarted &&
      (Math.abs(moveEvent.clientX - startX) > 5 ||
       Math.abs(moveEvent.clientY - startY) > 5)) {
      dragStarted = true
      cleanup()
      // 启动 LogicFlow Dnd 拖拽，后续 pointermove/pointerup 由 Dnd 自动处理
      useStore.getLf.dnd.startDrag(obj)
    }
  }

  // 指针抬起监听：未发生拖拽时执行点击添加
  const onPointerUp = () => {
    if (!dragStarted) {
      cleanup()
      visible.value = false // 关闭组件弹窗
      // 添加节点到画布默认位置
      useStore.getLf.addNode(obj)
    }
  }

  // 清理临时监听器
  const cleanup = () => {
    document.removeEventListener('pointermove', onPointerMove)
    document.removeEventListener('pointerup', onPointerUp)
  }

  document.addEventListener('pointermove', onPointerMove)
  document.addEventListener('pointerup', onPointerUp)
}
</script>
<style scoped lang="scss">
/* 编辑器主容器样式 - 强制白色主题，不随系统深色模式变化 */
.ivr-edit {
  overflow: hidden;
  background: #ffffff !important;
  height: 100vh;
}

/* 去除 LogicFlow 矩形节点底板的默认深色边框 */
:deep(.lf-node rect) {
  stroke: transparent;
  stroke-width: 0;
}

/* 画布背景强制白色 */
:deep(#graph) {
  background: #ffffff !important;
}

:deep(.lf-background) {
  background: #ffffff !important;
}

/* 标题栏样式 - 固定白色 */
.ivr-title {
  padding: 10px 24px;
  border-bottom: 1px solid #e5e7eb;
  align-items: center;
  background-color: #ffffff !important;
}

/* 间距样式 */
.mr-20 {
  margin-right: 20px;
}
.mr-10 {
  margin-right: 10px;
}

/* 文本样式 - 固定颜色 */
.size-16 {
  font-size: 16px;
  color: #1f2329 !important;
  font-weight: bold;
  margin-bottom: 0;
}

.size-14 {
  font-size: 14px;
  color: #646a73 !important;
  letter-spacing: 0;
  margin-bottom: 0;
}

/* 添加组件按钮 - 固定白色背景蓝色边框，不随主题变化 */
.add-comp-btn {
  background: #ffffff !important;
  border-color: #4080ff !important;
  color: #4080ff !important;
  margin-right: 12px;
}
.add-comp-btn:hover {
  background: #ecf5ff !important;
  border-color: #4080ff !important;
  color: #4080ff !important;
}

/* 组件弹窗样式 - 固定白色主题 */
.node-title {
  color: #1f2329 !important;
  padding: 0 12px;
  font-size: 13px;
  font-weight: 600;
}

.node-li {
  cursor: grab;
  width: 268px;
}
.node-li:active {
  cursor: grabbing;
}
.node-content {
  padding: 8px 12px;
  display: flex;
  align-items: flex-start;
  border-radius: 6px;
}
.node-li:hover .node-content {
  background-color: #f0f7ff;
}
.node-des {
  display: flex;
  flex-direction: column;
  justify-content: space-around;
  align-items: flex-start;
}
.node-icon {
  width: 32px;
  height: 32px;
  border-radius: 4px;
  flex-shrink: 0;
  margin-right: 10px;
  margin-top: 4px;
  display: flex;
  justify-content: center;
  align-items: center;
}
.node-des {
  h4 {
    margin: 0;
    color: #1f2329 !important;
    font-size: 14px;
    font-weight: 500;
  }
  h5 {
    margin: 0;
    font-size: 12px;
    color: #8f959e !important;
    line-height: 1.5;
  }
}
.node-img {
  width: 20px;
  height: 20px;
}
</style>

<!-- 全局样式覆盖：强制组件弹窗内白色主题，不随深色模式变化 -->
<style lang="scss">
/* 添加组件弹窗固定白色 */
.ivr-node-popover {
  background: #ffffff !important;
  border: 1px solid #e5e7eb !important;
  box-shadow: 0 4px 12px rgba(0,0,0,0.1) !important;
}
.ivr-node-popover .el-divider {
  border-color: #f0f0f0 !important;
}
.ivr-node-popover .el-divider__text {
  background: #ffffff !important;
  color: #909399 !important;
}
.ivr-node-popover .el-popper__arrow::before {
  background: #ffffff !important;
  border-color: #e5e7eb !important;
}
</style>
