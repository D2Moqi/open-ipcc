/** 节点类型枚举 */
export enum NodeType {
  START_NODE = 'start-node', // 开始节点
  END_NODE = 'end-node', // 结束节点
  PLAYBACK_NODE = 'playback-node', // 放音节点
  TRANSFER_NODE = 'transfer-node', // 转移节点
  RECEIVE_NODE = 'receive-node', // 收号节点
  CONDITION_NODE = 'condition-node', // 判断器节点
  METHOD_NODE = 'method-node', // 方法节点
  AI_NODE = 'ai-node' // AI 对话节点
}

/** 放音类型枚举：值需与后端 IVR 放音类型保持一致 */
export enum PlaybackType {
  VOICE_FILE = 1, // 语音文件
  TEXT = 2 // 文本内容
}
