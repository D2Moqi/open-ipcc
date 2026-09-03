import { NodeType } from './ivrEnum'

/** 节点输出值描述 */
export interface NodeOutput {
  key: string
  label: string
}

/**
 * 组件输出值注册表
 * 按节点类型聚合该节点可对外暴露的变量，供后续节点（如判断器、方法节点）引用
 * key 为变量名，label 为中文描述，用于变量选择下拉展示
 */
export const NODE_OUTPUTS: Record<string, NodeOutput[]> = {
  [NodeType.START_NODE]: [
    { key: 'year', label: '当前年' },
    { key: 'month', label: '当前月' },
    { key: 'day', label: '当前日' },
    { key: 'time', label: '当前时' },
    { key: 'minute', label: '当前分' },
    { key: 'yearMonth', label: '当前年月' },
    { key: 'yearMonthDay', label: '当前年月日' },
    { key: 'yearMonthDayTime', label: '当前年月日时' },
    { key: 'yearMonthDayTimeMinute', label: '当前年月日时分' },
    { key: 'yearMonthDayTimeMinuteSecond', label: '当前年月日时分秒' },
    { key: 'caller', label: '当前主叫电话' },
    { key: 'callee', label: '当前被叫电话' }
  ],
  [NodeType.RECEIVE_NODE]: [{ key: 'result', label: '输出结果' }],
  [NodeType.METHOD_NODE]: [{ key: 'result', label: '输出结果' }],
  [NodeType.TRANSFER_NODE]: [{ key: 'answerNumber', label: '当前应答号码' }],
  [NodeType.AI_NODE]: [{ key: 'interruptWord', label: '中断词' }]
}
