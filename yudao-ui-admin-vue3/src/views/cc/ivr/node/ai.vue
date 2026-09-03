<template>
  <div class="node-box node-ai" @mousedown="onNodeMouseDown" @pointerdown="onNodePointerDown" @click="onNodeClick">
    <div class="node-title">
      <div class="title-left">
        <div class="img-box" style="background:#36cfc9">
          <img src="@/assets/ivr/ai.svg" alt="" class="w-14 h-14" />
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
        <span class="form-label">聊天角色</span>
        <el-select
          v-model="formState.roleId"
          placeholder="请选择 AI 聊天角色"
          size="small"
          class="form-ctrl-sm"
          @change="updateProperties"
        >
          <el-option v-for="item in roleOptions" :key="item.id" :label="item.name" :value="item.id" />
        </el-select>
      </div>
      <div class="form-row">
        <span class="form-label">中断词</span>
        <div class="tag-input-wrap">
          <el-tag
            v-for="(word, index) in formState.interruptWords"
            :key="index"
            closable
            size="small"
            :disable-transitions="true"
            class="interrupt-tag"
            @close="removeInterruptWord(index)"
          >
            {{ word }}
          </el-tag>
          <el-input
            v-model="interruptInput"
            placeholder="输入后回车添加"
            size="small"
            class="tag-input"
            @keyup.enter="addInterruptWord"
          />
        </div>
      </div>
      <div v-if="formState.interruptWords && formState.interruptWords.length" class="form-row">
        <span class="form-label"></span>
        <span class="interrupt-tip">识别到任一中断词即结束本节点并输出该词</span>
      </div>
      <div class="form-row">
        <span class="form-label">开场语</span>
        <el-input
          v-model="formState.welcomeContent"
          type="textarea"
          :rows="3"
          resize="none"
          placeholder="进入节点先播报（可选）"
          size="small"
          class="ai-welcome-textarea"
          @change="updateProperties"
        />
      </div>
      <div class="form-row">
        <span class="form-label">最大轮次</span>
        <el-input-number
          v-model="formState.maxTurns"
          :min="0"
          :max="100"
          size="small"
          controls-position="right"
          class="form-ctrl-sm"
          @change="updateProperties"
        />
        <span class="unit-text">轮</span>
      </div>
      <div class="form-row">
        <span class="form-label">静默超时</span>
        <el-input-number
          v-model="formState.silenceTimeoutSeconds"
          :min="3"
          :max="120"
          size="small"
          controls-position="right"
          class="form-ctrl-sm"
          @change="updateProperties"
        />
        <span class="unit-text">秒</span>
      </div>
      <div class="form-row output-row">
        <span class="form-label">输出值</span>
        <OutputValue label="中断词" output-key="interruptWord" />
      </div>
      <el-alert
        type="warning"
        :closable="false"
        show-icon
        class="ai-fail-tip"
        title="AI 对话失败、识别异常或超时时，输出值「中断词」固定为 ai对话失败，可在判断器节点按该值配置分支"
      />
    </div>
  </div>
</template>

<script lang="ts">
import { defineComponent } from 'vue'
import OutputValue from './components/OutputValue.vue'
import { ChatRoleApi } from '@/api/ai/model/chatRole'
import { useIvrStore } from '../store/ivr'
import { generateRandomString } from '../utils/node'
import { stopFormEventBubble } from './utils/formEventGuard'
import { syncNodeSize } from './utils/nodeResize'
import { NodeType } from '@/views/cc/ivr/consts/ivrEnum'

const message = useMessage()
const useStore = useIvrStore()

interface RoleOption {
  id: number
  name: string
  category?: string
}

export default defineComponent({
  name: NodeType.AI_NODE,
  components: { OutputValue },
  inject: ['getNode', 'getGraph'],
  data() {
    return {
      formState: {
        roleId: undefined as number | undefined,
        interruptWords: [] as string[],
        welcomeContent: '',
        maxTurns: 10,
        silenceTimeoutSeconds: 10
      },
      interruptInput: '',
      roleOptions: [] as RoleOption[],
      name: '',
      id: NodeType.AI_NODE + '_'
    }
  },
  created() {
    this.loadRoleOptions()
  },
  mounted() {
    const node = (this as any).getNode()
    const graph = (this as any).getGraph()
    const { nodes } = graph
    const index = nodes.findIndex((item: any) => item && item.id == node.id)
    if (index === -1) {
      this.name = 'AI 对话'
      return
    }
    const aiArr = nodes.filter((item: any) => item && item.properties && item.properties.businessType == NodeType.AI_NODE)
    const props = nodes[index].properties
    this.name = (props.name || 'AI 对话') + (aiArr.length - 1 == 0 ? '' : aiArr.length - 1)
    Object.assign(this.formState, {
      roleId: props.roleId,
      interruptWords: props.interruptWords || [],
      welcomeContent: props.welcomeContent || '',
      maxTurns: props.maxTurns,
      silenceTimeoutSeconds: props.silenceTimeoutSeconds
    })
    // foreignObject 内首次挂载后强制重渲染，确保 v-if/v-for 分支内容正确展示
    this.$nextTick(() => {
      this.$forceUpdate()
    })
  },
  methods: {
    /**
     * 加载 AI 模块公开的聊天角色（免权限接口，供下拉选择）
     */
    async loadRoleOptions() {
      try {
        const data = await ChatRoleApi.getChatRoleSimpleList()
        this.roleOptions = (data || []) as RoleOption[]
      } catch (e) {
        console.error('[ai-node] 加载聊天角色列表失败', e)
        this.roleOptions = []
      }
    },
    /**
     * 添加中断词：回车触发，去重且忽略空白
     */
    addInterruptWord() {
      const word = this.interruptInput.trim()
      if (!word) {
        this.interruptInput = ''
        return
      }
      if (!this.formState.interruptWords.includes(word)) {
        this.formState.interruptWords.push(word)
        this.updateProperties()
      }
      this.interruptInput = ''
    },
    /**
     * 删除指定下标的中断词
     */
    removeInterruptWord(index: number) {
      this.formState.interruptWords.splice(index, 1)
      this.updateProperties()
    },
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
     * 内容变化会改变 DOM 高度，需在 nextTick 后同步 foreignObject 尺寸，
     * 否则节点会被裁剪导致内容展示不全。
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
.node-ai {
  width: 100%;
}
.tag-input-wrap {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  align-items: center;
  flex: 1;
  min-width: 0;
}
.interrupt-tag {
  margin-right: 0;
}
.tag-input {
  width: 90px;
  flex-shrink: 1;
}
.interrupt-tip {
  font-size: 12px;
  color: #909399;
  line-height: 1.4;
}
.ai-fail-tip {
  margin-top: 8px;
}
.ai-fail-tip :deep(.el-alert__title) {
  font-size: 12px;
  line-height: 1.5;
}
.ai-welcome-textarea {
  flex: 1;
  min-width: 0;
}
.ai-welcome-textarea :deep(.el-textarea__inner) {
  font-size: 12px;
  line-height: 1.5;
}
</style>