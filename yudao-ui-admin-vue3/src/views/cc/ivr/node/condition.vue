<template>
  <div class="node-box node-condition" @mousedown="onBoxMouseDown" @pointerdown="onBoxPointerDown" @click="onBoxClick">
    <!-- 标题区域：图标 + 名称 + 操作弹出 -->
    <div class="node-title">
      <div class="title-left">
        <div class="img-box" style="background:#722ed1">
          <img src="@/assets/ivr/condition.svg" alt="" class="w-14 h-14" />
        </div>
        <div class="titles">{{ name }}</div>
      </div>
      <div class="title-right">
        <el-popover placement="bottom" trigger="click" :teleported="true">
          <template #reference>
            <span class="op-btn">操作</span>
          </template>
          <div class="op-menu">
            <p class="op-item" @click="copyNode">复制</p>
            <el-divider style="margin:4px 0" />
            <p class="op-item" @click="delNode">删除</p>
          </div>
        </el-popover>
      </div>
    </div>

    <!-- 分支区域 -->
    <div class="node-body">
      <div class="branches">
        <div
          v-for="(branch, branchIndex) in formState.branches"
          :key="'branch-' + branchIndex"
          :ref="(el: any) => setBranchRef(branchIndex, el)"
          class="branch-item"
          :class="{ 'branch-removable': branch.branchType === 'ELSE_IF' }"
          :data-branch-index="branchIndex"
        >
          <!-- ELSE_IF 分支右侧中间删除按钮 -->
          <el-icon
            v-if="branch.branchType === 'ELSE_IF'"
            class="branch-remove-icon"
            @click="removeBranch(branchIndex)"
            title="删除分支"
          >
            <Close />
          </el-icon>
          <!-- 分支标题 -->
          <div class="branch-header">
            <span class="branch-label" :class="'label-' + getBranchLabelClass(branch.branchType)">
              {{ getBranchLabel(branch, branchIndex) }}
            </span>
            <!-- IF/ELSE_IF 分支显示匹配模式：符合以下[所有/任一]条件（不需要清空） -->
            <template v-if="branch.branchType !== 'ELSE'">
              <span class="match-text">符合以下</span>
              <el-select
                v-model="branch.matchType"
                @change="handleUiChange"
                :teleported="true"
                class="match-select"
                size="small"
              >
                <el-option label="所有" value="ALL" />
                <el-option label="任一" value="ANY" />
              </el-select>
              <span class="match-text">条件</span>
            </template>
          </div>

          <!-- 条件区域（仅 IF/ELSE_IF 有，ELSE 不渲染） -->
          <template v-if="branch.branchType !== 'ELSE'">
            <div
              v-for="(cond, condIndex) in (branch.conditions || [])"
              :key="'cond-' + branchIndex + '-' + condIndex"
              class="condition-row"
            >
              <div class="cond-row-content">
                <!-- 变量下拉框（两级结构：组件 → 输出值）需要清空按钮 -->
                <el-cascader
                  v-model="cond.variableArr"
                  :options="variableOptions"
                  :props="{ expandTrigger: 'hover', checkStrictly: false }"
                  @change="handleVariableChange(branchIndex, condIndex, $event)"
                  :teleported="true"
                  clearable
                  placeholder="选择变量"
                  class="cond-var"
                  size="small"
                />
                <!-- 操作符下拉框需要清空 -->
                <el-select
                  v-model="cond.operator"
                  @change="handleOperatorChange(branchIndex, condIndex)"
                  :teleported="true"
                  clearable
                  placeholder="条件"
                  class="cond-op"
                  size="small"
                >
                  <el-option
                    v-for="opt in operatorOptions"
                    :key="opt.value"
                    :label="opt.label"
                    :value="opt.value"
                  />
                </el-select>
                <!-- 输入值（文本/数字，需要清空；不加事件stop，避免原生focus被破坏） -->
                <el-input
                  v-if="getInputType(cond.operator) === 'text'"
                  v-model="cond.value"
                  @change="handleUiChange"
                  clearable
                  placeholder="输入值"
                  class="cond-val"
                  size="small"
                />
                <el-input-number
                  v-else-if="getInputType(cond.operator) === 'number'"
                  v-model="cond.value"
                  @change="handleUiChange"
                  class="cond-val"
                  size="small"
                  controls-position="right"
                />
                <!-- 删除条件图标 -->
                <el-icon
                  v-if="condIndex > 0"
                  @click="removeCondition(branchIndex, condIndex)"
                  class="remove-icon"
                >
                  <Close />
                </el-icon>
              </div>
            </div>
            <!-- 添加条件按钮 -->
            <div class="add-cond-btn">
              <el-button link type="primary" size="small" @click="addCondition(branchIndex)">+ 添加条件</el-button>
            </div>
          </template>
        </div>
      </div>

      <!-- 添加分支按钮 -->
      <div class="add-branch-btn">
        <el-button link type="primary" size="small" @click="addBranch">+ 添加分支</el-button>
      </div>
    </div>
  </div>
</template>

<script lang="ts">
import { defineComponent, nextTick } from 'vue'
import { Close } from '@element-plus/icons-vue'
import { useIvrStore } from '../store/ivr'
import { generateRandomString } from '../utils/node'
import { NodeType } from '@/views/cc/ivr/consts/ivrEnum'
import { NODE_OUTPUTS } from '@/views/cc/ivr/consts/nodeOutputs'
import { OPERATOR_INPUT_TYPE } from '@/views/cc/ivr/consts/conditionOperator'
import { getStrDictOptions, DICT_TYPE } from '@/utils/dict'

const message = useMessage()
const useStore = useIvrStore()

import { stopFormEventBubble } from './utils/formEventGuard'

export default defineComponent({
  name: NodeType.CONDITION_NODE,
  components: { Close },
  inject: ['getNode', 'getGraph'],
  data() {
    return {
      formState: {
        branches: [
          {
            branchType: 'IF',
            matchType: 'ALL',
            conditions: [{ variable: '', operator: '', value: '', variableArr: [] }]
          },
          {
            branchType: 'ELSE',
            conditions: []
          }
        ] as any[]
      },
      name: '判断器',
      id: NodeType.CONDITION_NODE + '_',
      /** 分支 DOM 引用缓存 */
      branchRefs: [] as HTMLElement[]
    }
  },
  computed: {
    variableOptions(): any[] {
      try {
        const node = (this as any).getNode()
        const graph = (this as any).getGraph()
        if (!node || !graph) return []
        const { nodes, edges } = graph
        if (!nodes || !edges) return []
        const currentNodeId = node.id

        /**
         * 反向图 BFS：收集所有左侧可达节点（上游/上级/开始节点/同级分支上游节点）
         */
        const visited = new Set<string>()
        const queue: string[] = []
        const directSources = edges
          .filter((edge: any) => edge && edge.targetNodeId === currentNodeId)
          .map((edge: any) => edge.sourceNodeId)
        directSources.forEach((id: string) => {
          if (!visited.has(id)) {
            visited.add(id)
            queue.push(id)
          }
        })
        while (queue.length > 0) {
          const curId = queue.shift() as string
          const curInEdges = edges.filter((edge: any) => edge && edge.targetNodeId === curId)
          curInEdges.forEach((edge: any) => {
            const srcId = edge.sourceNodeId
            if (!visited.has(srcId)) {
              visited.add(srcId)
              queue.push(srcId)
            }
          })
        }
        const options: any[] = []
        nodes.forEach((n: any) => {
          if (!n || !visited.has(n.id)) return
          const outputs = NODE_OUTPUTS[n.type] || []
          if (outputs.length === 0) return
          const componentName = n.properties?.name || n.type
          options.push({
            value: n.id,
            label: componentName,
            children: outputs.map((output) => ({
              value: output.key,
              label: output.label
            }))
          })
        })
        return options
      } catch (e) {
        console.error('获取变量选项失败', e)
        return []
      }
    },
    operatorOptions(): any[] {
      try {
        const dictOpts = getStrDictOptions(DICT_TYPE.CC_IVR_CONDITION_OPERATOR)
        if (dictOpts && dictOpts.length > 0) return dictOpts
      } catch (e) {
        console.error('获取字典选项失败', e)
      }
      return [
        { value: 'IS_EMPTY', label: '为空' },
        { value: 'IS_NOT_EMPTY', label: '不为空' },
        { value: 'CONTAINS', label: '包含' },
        { value: 'NOT_CONTAINS', label: '不包含' },
        { value: 'EQ', label: '等于' },
        { value: 'NE', label: '不等于' },
        { value: 'GT', label: '大于' },
        { value: 'GTE', label: '大于等于' },
        { value: 'LT', label: '小于' },
        { value: 'LTE', label: '小于等于' },
        { value: 'LENGTH_EQ', label: '长度等于' },
        { value: 'LENGTH_NE', label: '长度不等于' },
        { value: 'LENGTH_GT', label: '长度大于' },
        { value: 'LENGTH_GTE', label: '长度大于等于' },
        { value: 'LENGTH_LT', label: '长度小于' },
        { value: 'LENGTH_LTE', label: '长度小于等于' },
        { value: 'IS_TRUE', label: '为真' },
        { value: 'IS_NOT_TRUE', label: '不为真' }
      ]
    }
  },
  mounted() {
    try {
      const node = (this as any).getNode()
      const graph = (this as any).getGraph()
      if (!node || !graph) return
      const { nodes } = graph
      if (!nodes) return
      const index = nodes.findIndex((item: any) => item && item.id == node.id)
      if (index === -1) {
        this.name = '判断器'
        return
      }
      const conditionArr = nodes.filter(
        (item: any) => item && item.properties && item.properties.businessType == NodeType.CONDITION_NODE
      )
      const props = nodes[index].properties || {}
      const { branches, name: propName } = props
      this.name = (propName || '判断器') + (conditionArr.length - 1 == 0 ? '' : conditionArr.length - 1)
      if (branches && Array.isArray(branches) && branches.length > 0) {
        this.formState.branches = JSON.parse(JSON.stringify(branches))
        this.formState.branches.forEach((branch: any) => {
          if (!branch.conditions) branch.conditions = []
          branch.conditions.forEach((cond: any) => {
            cond.variableArr = cond.variable ? cond.variable.split('.') : []
            if (cond.value === undefined || cond.value === null) cond.value = ''
          })
          if (branch.branchType !== 'ELSE' && !branch.matchType) branch.matchType = 'ALL'
        })
      }
    } catch (e) {
      console.error('判断器节点初始化失败', e)
    }
  },
  methods: {
    /**
     * bubble 阶段 mousedown：命中表单控件时 stopPropagation，阻止 LF 选中/拖拽节点
     */
    onBoxMouseDown(e: MouseEvent) {
      stopFormEventBubble(e)
    },
    /**
     * bubble 阶段 pointerdown：同上，兼容 pointer 事件
     */
    onBoxPointerDown(e: PointerEvent) {
      stopFormEventBubble(e)
    },
    /**
     * bubble 阶段 click：命中表单控件时 stopPropagation，阻止 LF 选中节点
     */
    onBoxClick(e: MouseEvent) {
      stopFormEventBubble(e)
    },
    setBranchRef(idx: number, el: any) {
      if (el) {
        this.branchRefs[idx] = el as HTMLElement
        try {
          const node = (this as any).getNode()
          if (node && useStore.getLf && (useStore.getLf as any).graphModel) {
            const nodeModel = (useStore.getLf as any).graphModel.getNodeModelById(node.id)
            if (nodeModel && typeof nodeModel.setBranchCenters === 'function') {
              nodeModel.setBranchCenters(this.calcBranchCenters())
            }
          }
        } catch (_) {}
      }
    },
    calcBranchCenters(): number[] {
      try {
        const rootEl = this.branchRefs[0]?.closest?.('.node-condition') as HTMLElement | null
        if (!rootEl) return []
        const rootRect = rootEl.getBoundingClientRect()
        const centers: number[] = []
        for (let i = 0; i < this.formState.branches.length; i++) {
          const el = this.branchRefs[i] as HTMLElement | undefined
          if (!el) { centers.push(-1); continue }
          const rect = el.getBoundingClientRect()
          centers.push((rect.top + rect.bottom) / 2 - rootRect.top)
        }
        return centers
      } catch (_) {
        return []
      }
    },
    getBranchLabelClass(branchType: string): string {
      if (branchType === 'IF') return 'label-if'
      if (branchType === 'ELSE') return 'label-else'
      return 'label-else-if'
    },
    getBranchLabel(branch: any, branchIndex: number): string {
      if (branch.branchType === 'IF') return 'IF'
      if (branch.branchType === 'ELSE') return 'ELSE'
      return 'ELSE IF ' + this.getElseIfNumber(branchIndex)
    },
    getInputType(operator: string): 'none' | 'text' | 'number' {
      return OPERATOR_INPUT_TYPE[operator] || 'none'
    },
    getElseIfNumber(branchIndex: number): number {
      let count = 0
      for (let i = 0; i <= branchIndex; i++) {
        if (this.formState.branches[i] && this.formState.branches[i].branchType === 'ELSE_IF') count++
      }
      return count
    },
    async handleUiChange() {
      await this.syncNodeSize()
      this.updateProperties()
    },
    addCondition(branchIndex: number) {
      if (!this.formState.branches[branchIndex].conditions) {
        this.formState.branches[branchIndex].conditions = []
      }
      this.formState.branches[branchIndex].conditions.push({
        variable: '', operator: '', value: '', variableArr: []
      })
      nextTick(() => this.handleUiChange())
    },
    removeCondition(branchIndex: number, condIndex: number) {
      if (condIndex <= 0) return
      if (!this.formState.branches[branchIndex].conditions) return
      this.formState.branches[branchIndex].conditions.splice(condIndex, 1)
      nextTick(() => this.handleUiChange())
    },
    addBranch() {
      const branches = this.formState.branches
      const elseIndex = branches.findIndex((b: any) => b.branchType === 'ELSE')
      const insertIndex = elseIndex !== -1 ? elseIndex : branches.length
      const newBranch = {
        branchType: 'ELSE_IF',
        matchType: 'ALL',
        conditions: [{ variable: '', operator: '', value: '', variableArr: [] }]
      }
      branches.splice(insertIndex, 0, newBranch)
      /**
       * 锚点ID重映射：新增ELSE_IF插到ELSE前，ELSE的索引从 elseIndex 变成 insertIndex+1，
       * 需要把所有连在旧ELSE锚点(${nodeId}_${elseIndex}_right)的边的sourceAnchorId改为新锚点id，
       * 否则原来ELSE的连线会错误连到新插入的ELSE_IF锚点上
       */
      try {
        const node = (this as any).getNode()
        const lf = useStore.getLf as any
        if (node && lf && lf.graphModel && elseIndex !== -1) {
          const oldAnchorId = `${node.id}_${elseIndex}_right`
          const newAnchorId = `${node.id}_${insertIndex + 1}_right`
          const edges = lf.graphModel.edges || []
          for (const edge of edges) {
            if (edge && edge.sourceNodeId === node.id && edge.sourceAnchorId === oldAnchorId) {
              edge.sourceAnchorId = newAnchorId
              // 更新startPoint需要等nextTick（新锚点DOM渲染后重新计算）
            }
          }
        }
      } catch (_) {}
      nextTick(() => this.handleUiChange())
    },
    /**
     * 删除指定的 ELSE_IF 分支
     * 删除前处理连线：
     *   1. 删除连在被删分支锚点上的出边
     *   2. 被删分支之后的锚点索引前移 1，对应边的 sourceAnchorId 同步更新
     * @param branchIndex - 要删除的分支索引
     */
    removeBranch(branchIndex: number) {
      const branches = this.formState.branches
      const branch = branches[branchIndex]
      // 仅 ELSE_IF 可删除，IF 和 ELSE 不允许
      if (!branch || branch.branchType !== 'ELSE_IF') return
      try {
        const node = (this as any).getNode()
        const lf = useStore.getLf as any
        if (node && lf && lf.graphModel) {
          const edges = lf.graphModel.edges || []
          const removedAnchorId = `${node.id}_${branchIndex}_right`
          // 收集需要删除的边和需要重映射的边
          const edgesToDelete: string[] = []
          for (const edge of edges) {
            if (!edge || edge.sourceNodeId !== node.id) continue
            if (edge.sourceAnchorId === removedAnchorId) {
              edgesToDelete.push(edge.id)
            } else {
              // 解析锚点索引：格式为 {nodeId}_{index}_right
              const match = edge.sourceAnchorId?.match?.(new RegExp(`^${node.id}_(\\d+)_right$`))
              if (match) {
                const anchorIdx = parseInt(match[1], 10)
                if (anchorIdx > branchIndex) {
                  edge.sourceAnchorId = `${node.id}_${anchorIdx - 1}_right`
                }
              }
            }
          }
          // 删除连在被删分支上的边
          for (const edgeId of edgesToDelete) {
            try { lf.deleteEdge(edgeId) } catch (_) {}
          }
        }
      } catch (_) {}
      branches.splice(branchIndex, 1)
      nextTick(() => this.handleUiChange())
    },
    handleVariableChange(branchIndex: number, condIndex: number, event: any[]) {
      const cond = this.formState.branches[branchIndex].conditions[condIndex]
      cond.variable = (event && event.length >= 2) ? event[0] + '.' + event[1] : ''
      this.handleUiChange()
    },
    handleOperatorChange(branchIndex: number, condIndex: number) {
      this.formState.branches[branchIndex].conditions[condIndex].value = ''
      this.handleUiChange()
    },
    async syncNodeSize() {
      try {
        await nextTick()
        const node = (this as any).getNode()
        if (!node || !useStore.getLf) return
        const nodeModel = (useStore.getLf as any).graphModel.getNodeModelById(node.id)
        if (!nodeModel) return
        if (typeof nodeModel.syncSizeFromDom === 'function') nodeModel.syncSizeFromDom()
        if (typeof nodeModel.setBranchCenters === 'function') nodeModel.setBranchCenters(this.calcBranchCenters())
      } catch (e) {
        console.warn('同步判断器节点尺寸失败', e)
      }
    },
    updateProperties() {
      try {
        const node = (this as any).getNode()
        const graph = (this as any).getGraph()
        if (!node || !graph) return
        const { nodes } = graph
        if (!nodes) return
        const index = nodes.findIndex((item: any) => item.id === node.id)
        if (index !== -1) {
          const branches = this.formState.branches.map((b: any) => {
            const branch: any = { branchType: b.branchType }
            if (b.branchType !== 'ELSE') branch.matchType = b.matchType || 'ALL'
            branch.conditions = (b.conditions || []).map((c: any) => ({
              variable: c.variable || '',
              operator: c.operator || '',
              value: c.value !== undefined && c.value !== null ? c.value : ''
            }))
            return branch
          })
          useStore.getLf.setProperties(node.id, { ...nodes[index].properties, branches })
        }
      } catch (e) {
        console.error('更新判断器属性失败', e)
      }
    },
    async delNode() {
      const node = (this as any).getNode()
      await message.confirm('确定要删除此节点吗?')
      useStore.getLf.deleteNode(node.id)
    },
    copyNode() {
      const node = (this as any).getNode()
      const CloneNode = useStore.getLf.cloneNode(node.id)
      useStore.getLf.changeNodeId(CloneNode.id, this.id + generateRandomString(6))
    }
  }
})
</script>
<style scoped>
/* 判断器节点样式已移至全局 node-common.css */
</style>
