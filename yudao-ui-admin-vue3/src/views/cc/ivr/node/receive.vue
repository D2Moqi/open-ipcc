<template>
  <div
    class="node-box node-receive"
    @mousedown="onNodeMouseDown"
    @pointerdown="onNodePointerDown"
    @click="onNodeClick"
  >
    <div class="node-title">
      <div class="title-left">
        <div class="img-box" style="background:#14c0ff">
          <img src="@/assets/ivr/receive.svg" alt="" class="w-14 h-14" />
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
      <PlaybackContent v-model="playbackContent" @update:modelValue="updateProperties" />
      <div class="form-row switch-row">
        <span class="form-label">可打断</span>
        <el-switch v-model="formState.interruptible" @change="updateProperties" size="small" />
      </div>
      <div class="form-row switch-row">
        <span class="form-label">语音收号</span>
        <el-switch v-model="formState.voiceCollect" @change="updateProperties" size="small" />
      </div>
      <div v-if="formState.voiceCollect" class="voice-collect-tip">
        语音收号已开启，将使用 ASR 识别语音内容触发后续流程
      </div>
      <div v-if="!formState.voiceCollect" class="form-row">
        <span class="form-label">首位超时</span>
        <el-input-number v-model="formState.firstDigitTimeout" :min="1" :max="60" @change="updateProperties" size="small" controls-position="right" class="form-ctrl-sm" />
        <span class="unit-text">秒</span>
      </div>
      <div v-if="!formState.voiceCollect" class="form-row">
        <span class="form-label">位间超时</span>
        <el-input-number v-model="formState.interDigitTimeout" :min="1" :max="60" @change="updateProperties" size="small" controls-position="right" class="form-ctrl-sm" />
        <span class="unit-text">秒</span>
      </div>
      <div v-if="!formState.voiceCollect" class="form-row">
        <span class="form-label">防抖间隔</span>
        <el-input-number v-model="formState.debounceInterval" :min="0" :max="2000" :step="50" @change="updateProperties" size="small" controls-position="right" class="form-ctrl-sm" />
        <span class="unit-text">毫秒</span>
      </div>
      <div v-if="!formState.voiceCollect" class="form-row">
        <span class="form-label">结束按键</span>
        <el-input v-model="formState.endKey" @change="updateProperties" clearable size="small" class="form-ctrl-sm" />
      </div>
      <div class="form-row output-row">
        <span class="form-label">输出值</span>
        <OutputValue label="输出结果" output-key="result" />
      </div>
    </div>
  </div>
</template>

<script lang="ts">
import { defineComponent } from 'vue'
import PlaybackContent from './components/PlaybackContent.vue'
import OutputValue from './components/OutputValue.vue'
import { useIvrStore } from '../store/ivr'
import { generateRandomString } from '../utils/node'
import { stopFormEventBubble } from './utils/formEventGuard'
import { syncNodeSize } from './utils/nodeResize'
import { NodeType, PlaybackType } from '@/views/cc/ivr/consts/ivrEnum'

const message = useMessage()
const useStore = useIvrStore()

export default defineComponent({
  name: NodeType.RECEIVE_NODE,
  components: { PlaybackContent, OutputValue },
  inject: ['getNode', 'getGraph'],
  data() {
    return {
      formState: {
        playbackType: PlaybackType.VOICE_FILE,
        fileId: '',
        content: '',
        num: 1,
        interruptible: false,
        firstDigitTimeout: 5,
        interDigitTimeout: 2,
        debounceInterval: 200,
        endKey: '#',
        voiceCollect: false
      },
      name: '',
      id: NodeType.RECEIVE_NODE + '_'
    }
  },
  computed: {
    playbackContent: {
      get() {
        return {
          playbackType: this.formState.playbackType,
          fileId: this.formState.fileId,
          content: this.formState.content,
          num: this.formState.num
        }
      },
      set(value: any) {
        this.formState.playbackType = value.playbackType
        this.formState.fileId = value.fileId
        this.formState.content = value.content
        this.formState.num = value.num
      }
    }
  },
  mounted() {
    const node = (this as any).getNode()
    const graph = (this as any).getGraph()
    const { nodes } = graph
    const index = nodes.findIndex((item: any) => item && item.id == node.id)
    if (index === -1) {
      this.name = '收号并放音'
      return
    }
    const receiveArr = nodes.filter(
      (item: any) => item && item.properties && item.properties.businessType == NodeType.RECEIVE_NODE
    )
    const props = nodes[index].properties
    this.name = (props.name || '收号并放音') + (receiveArr.length - 1 == 0 ? '' : receiveArr.length - 1)
    Object.assign(this.formState, {
      playbackType: props.playbackType,
      fileId: props.fileId,
      content: props.content,
      num: props.num,
      interruptible: props.interruptible,
      firstDigitTimeout: props.firstDigitTimeout,
      interDigitTimeout: props.interDigitTimeout,
      debounceInterval: props.debounceInterval,
      endKey: props.endKey,
      voiceCollect: props.voiceCollect === true
    })
    // foreignObject 内首次挂载后强制重渲染，确保 playbackType 对应的 v-if 分支内容正确展示
    this.$nextTick(() => {
      this.$forceUpdate()
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
    /**
     * 将表单数据同步到 LogicFlow 节点属性
     * 放音类型切换会改变 DOM 高度，需在 nextTick 后同步 foreignObject 尺寸，
     * 否则节点会被裁剪导致内容展示不全。
     * —— 增加新旧内容深度比较：内容完全相同则跳过 setProperties，避免 LogicFlow 销毁重建节点导致的
     *    foreignObject DOM 与 Vue 响应式数据不同步（v-if 分支不切换、el-select 未重渲染）。
     */
    async updateProperties() {
      const node = (this as any).getNode()
      const graph = (this as any).getGraph()
      const { nodes } = graph
      const index = nodes.findIndex((item: any) => item.id === node.id)
      if (index !== -1) {
        const oldProps = nodes[index].properties
        const updatedNode = { ...oldProps, ...this.formState }
        if (JSON.stringify(updatedNode) !== JSON.stringify(oldProps)) {
          useStore.getLf.setProperties(node.id, updatedNode)
        }
      }
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
.node-receive {
}
.voice-collect-tip {
  padding: 4px 8px;
  font-size: 12px;
  line-height: 1.5;
  color: #909399;
}
</style>
