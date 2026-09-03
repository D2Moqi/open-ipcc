<template>
  <div
    class="node-box node-start"
    @mousedown="onNodeMouseDown"
    @pointerdown="onNodePointerDown"
    @click="onNodeClick"
  >
    <div class="node-title">
      <div class="title-left">
        <div class="img-box" style="background:linear-gradient(270deg,#00b42a 0%,#00a854 100%)">
          <img src="@/assets/ivr/start.svg" alt="开始" class="w-14 h-14" />
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
    <div class="node-body">
      <div class="form-row">
        <span class="form-label">ASR引擎</span>
        <el-select
          v-model="formState.asrEngine"
          @change="updateProperties"
          :teleported="true"
          clearable
          size="small"
          class="form-ctrl"
        >
          <el-option v-for="item in engineAsrOptions" :key="item.id" :label="item.name" :value="String(item.id)" />
        </el-select>
      </div>
      <div class="form-row">
        <span class="form-label">TTS引擎</span>
        <el-select
          v-model="formState.ttsEngine"
          @change="updateProperties"
          :teleported="true"
          clearable
          size="small"
          class="form-ctrl"
        >
          <el-option v-for="item in engineTtsOptions" :key="item.id" :label="item.name" :value="String(item.id)" />
        </el-select>
      </div>
      <div class="form-row output-list-row">
        <span class="form-label">输出值</span>
        <div class="output-list">
          <OutputValue
            v-for="item in outputList"
            :key="item.key"
            :label="item.label"
            :output-key="item.key"
          />
        </div>
      </div>
      <p class="output-tip">可将本组件的 ${xxx} 用于后续组件的文本内容</p>
    </div>
  </div>
</template>

<script lang="ts">
import { defineComponent } from 'vue'
import OutputValue from './components/OutputValue.vue'
import { useIvrStore } from '../store/ivr'
import { stopFormEventBubble } from './utils/formEventGuard'
import { syncNodeSize } from './utils/nodeResize'
import { SysVoiceEngineApi } from '@/api/cc/sysvoiceengine'
import { generateRandomString } from '@/views/cc/ivr/utils/node'
import { NodeType } from '@/views/cc/ivr/consts/ivrEnum'
import { NODE_OUTPUTS } from '@/views/cc/ivr/consts/nodeOutputs'

const message = useMessage()
const useStore = useIvrStore()

export default defineComponent({
  name: NodeType.START_NODE,
  components: { OutputValue },
  inject: ['getNode', 'getGraph'],
  data() {
    return {
      formState: {
        asrEngine: '',
        ttsEngine: ''
      },
      name: '',
      id: NodeType.START_NODE + '_',
      engineAsrOptions: [] as any,
      engineTtsOptions: [] as any,
      outputList: NODE_OUTPUTS[NodeType.START_NODE] || []
    }
  },
  mounted() {
    this.getEngineOption()
    const node = (this as any).getNode()
    const graph = (this as any).getGraph()
    const { nodes } = graph
    const index = nodes.findIndex((item: any) => item && item.id == node.id)
    if (index === -1) {
      // 新添加节点，使用默认名称
      this.name = '开始'
    } else {
      const { asrEngine, ttsEngine, name } = nodes[index].properties
      this.name = name || '开始'
      Object.assign(this.formState, { asrEngine, ttsEngine })
    }
    // 输出值列表完整展开后节点高度由内容撑开，需在 DOM 更新后同步 foreignObject 尺寸，
    // 保证 11 个输出值完整展示不截断
    this.$nextTick(() => {
      syncNodeSize((this as any).getNode)
    })
  },
  methods: {
    onNodeMouseDown(e: MouseEvent) {
      stopFormEventBubble(e)
    },
    onNodePointerDown(e: PointerEvent) {
      stopFormEventBubble(e)
    },
    onNodeClick(e: MouseEvent) {
      stopFormEventBubble(e)
    },
    updateProperties() {
      const node = (this as any).getNode()
      const graph = (this as any).getGraph()
      const { nodes } = graph
      const index = nodes.findIndex((item: any) => item.id === node.id)
      if (index !== -1) {
        const updatedNode = { ...nodes[index].properties, ...this.formState }
        useStore.getLf.setProperties(node.id, updatedNode)
      }
    },
    /**
     * 加载ASR/TTS引擎下拉选项
     * 调用语音引擎管理list接口，响应拦截器已将业务数据直接返回，
     * code=0/200 时返回值就是数据数组，无需再取 res.data
     */
    async getEngineOption() {
      try {
        const asrList = await SysVoiceEngineApi.list({ type: 1 })
        this.engineAsrOptions = (asrList || []).map((item: any) => ({ id: item.id, name: item.name }))
      } catch (e) {
        console.error('加载ASR引擎列表失败', e)
      }
      try {
        const ttsList = await SysVoiceEngineApi.list({ type: 2 })
        this.engineTtsOptions = (ttsList || []).map((item: any) => ({ id: item.id, name: item.name }))
      } catch (e) {
        console.error('加载TTS引擎列表失败', e)
      }
      // 引擎选项渲染完成后再次同步尺寸，避免下拉选项填充引起的 DOM 尺寸变化未被 foreignObject 感知
      await syncNodeSize((this as any).getNode)
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
.node-start {
}
</style>
