<template>
  <div
    class="node-box node-playback"
    @mousedown="onNodeMouseDown"
    @pointerdown="onNodePointerDown"
    @click="onNodeClick"
  >
    <div class="node-title">
      <div class="title-left">
        <div class="img-box" style="background:linear-gradient(270deg,#9258f7 0%,#3370FF 100%)">
          <img src="@/assets/ivr/playback.svg" alt="" class="w-14 h-14" />
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
    </div>
  </div>
</template>

<script lang="ts">
import { defineComponent } from 'vue'
import { useIvrStore } from '../store/ivr'
import { generateRandomString } from '../utils/node'
import { stopFormEventBubble } from './utils/formEventGuard'
import { syncNodeSize } from './utils/nodeResize'
import { NodeType, PlaybackType } from '@/views/cc/ivr/consts/ivrEnum'
import PlaybackContent from './components/PlaybackContent.vue'

const message = useMessage()
const useStore = useIvrStore()

export default defineComponent({
  name: NodeType.PLAYBACK_NODE,
  components: { PlaybackContent },
  inject: ['getNode', 'getGraph'],
  data() {
    return {
      formState: {
        playbackType: PlaybackType.VOICE_FILE,
        fileId: '',
        content: '',
        num: 1
      },
      name: '',
      id: NodeType.PLAYBACK_NODE + '_'
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
      set(val: any) {
        Object.assign(this.formState, val)
      }
    }
  },
  mounted() {
    const node = (this as any).getNode()
    const graph = (this as any).getGraph()
    const { nodes } = graph
    const index = nodes.findIndex((item: any) => item && item.id == node.id)
    if (index === -1) {
      // 新添加节点，使用默认名称
      this.name = '放音'
      return
    }
    const playbackArr = nodes.filter(
      (item: any) => item && item.properties && item.properties.businessType == NodeType.PLAYBACK_NODE
    )
    const props = nodes[index].properties
    this.name = (props.name || '放音') + (playbackArr.length - 1 == 0 ? '' : playbackArr.length - 1)
    Object.assign(this.formState, {
      playbackType: props.playbackType,
      fileId: props.fileId,
      content: props.content,
      num: props.num
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
     * 放音类型切换等操作会改变 DOM 高度，需在 nextTick 后同步 foreignObject 尺寸，
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
.node-playback {
}
</style>
