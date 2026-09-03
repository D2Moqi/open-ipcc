<template>
  <span class="output-val output-val-copyable" :title="copyTitle" @click="handleCopy">
    <template v-if="label">{{ label }}：</template>{{ copyText }}
  </span>
</template>

<script setup lang="ts">
import { computed, inject } from 'vue'
import { copyTextToClipboard } from '../utils/copyOutput'

defineOptions({ name: 'OutputValue' })

const props = defineProps<{
  /** 输出值中文标签，展示在变量前（如"输出结果"）；为空时仅展示变量本身 */
  label?: string
  /** 输出值 key，如 result、caller 等 */
  outputKey: string
}>()

const message = useMessage()

/** LogicFlow 节点实例获取函数，由父级 Vue Node 注册时 provide */
const getNode = inject<() => any>('getNode', () => null)

/**
 * 展示的变量文本：`${节点ID.outputKey}`
 *
 * 复制时携带节点ID前缀（如 `${receive-node_abc123.result}`），
 * 确保多个同输出 key 的组件在粘贴到文本内容时可被后端精确匹配，
 * 与判断器组件的 "组件ID.输出值key" 变量引用方式保持一致。
 * getNode 未注入时降级为 `${outputKey}`（兼容非 LogicFlow 节点场景）。
 */
const copyText = computed(() => {
  const node = getNode?.()
  const nodeId = node?.id
  return nodeId ? `\${${nodeId}.${props.outputKey}}` : `\${${props.outputKey}}`
})

/** 悬浮提示 */
const copyTitle = computed(() => `点击复制 ${copyText.value}`)

/**
 * 单击复制输出值变量到剪贴板
 * 复制动作不影响节点选中/拖拽：事件冒泡由外层 node-box 的 formEventGuard 统一处理
 */
async function handleCopy() {
  const success = await copyTextToClipboard(copyText.value)
  if (success) {
    message.success('已复制')
  } else {
    message.error('复制失败，请手动复制')
  }
}
</script>
