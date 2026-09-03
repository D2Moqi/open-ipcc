import { defineStore } from 'pinia'
import { store } from '@/store'

import playBackImg from '@/assets/ivr/playback.svg'
import endImg from '@/assets/ivr/end.svg'
import startImg from '@/assets/ivr/start.svg'
import transferImg from '@/assets/ivr/transfer.svg'
import receiveIcon from '@/assets/ivr/receive.svg'
import conditionIcon from '@/assets/ivr/condition.svg' // 判断器节点图标
import methodIcon from '@/assets/ivr/method.svg' // 方法调用节点图标
import aiIcon from '@/assets/ivr/ai.svg' // AI 对话节点图标
import { NodeType } from '@/views/cc/ivr/consts/ivrEnum'

/** 节点元数据映射 */
export const NodeMetadata = {
  [NodeType.START_NODE]: {
    id: NodeType.START_NODE,
    name: '开始',
    businessType: NodeType.START_NODE
  },
  [NodeType.END_NODE]: {
    id: NodeType.END_NODE,
    name: '结束',
    businessType: NodeType.END_NODE
  },
  [NodeType.PLAYBACK_NODE]: {
    id: NodeType.PLAYBACK_NODE,
    name: '放音',
    businessType: NodeType.PLAYBACK_NODE
  },
  [NodeType.TRANSFER_NODE]: {
    id: NodeType.TRANSFER_NODE,
    name: '转接',
    businessType: NodeType.TRANSFER_NODE
  },
  [NodeType.RECEIVE_NODE]: {
    id: NodeType.RECEIVE_NODE,
    name: '收号并放音',
    businessType: NodeType.RECEIVE_NODE
  },
  [NodeType.CONDITION_NODE]: {
    id: NodeType.CONDITION_NODE,
    name: '判断器',
    businessType: NodeType.CONDITION_NODE
  },
  [NodeType.METHOD_NODE]: {
    id: NodeType.METHOD_NODE,
    name: '方法调用',
    businessType: NodeType.METHOD_NODE
  },
  [NodeType.AI_NODE]: {
    id: NodeType.AI_NODE,
    name: 'AI 对话',
    businessType: NodeType.AI_NODE
  }
} as const // 使用 as const 确保类型安全，禁止运行时修改
/**
 * 节点定义接口
 * 统一管理节点的元数据和配置信息
 */
interface INodeDefinition {
  meta: {
    type: NodeType
    name: string
    des?: string
    bgc?: string
    img?: any
    businessType: string
  }
  config: {
    id: string
    x: number
    y: number
    properties: Record<string, any>
  }
}
/**
 * 所有节点的统一配置数组
 * 集中定义所有节点的元数据和配置信息
 */
const allNodeDefinitions: INodeDefinition[] = [
  {
    meta: {
      type: NodeType.START_NODE,
      name: NodeMetadata[NodeType.START_NODE].name,
      des: '流程起始节点，定义IVR流程的入口',
      bgc: 'linear-gradient(270deg, #00b42a 0%, #00a854 100%)',
      img: startImg,
      businessType: NodeMetadata[NodeType.START_NODE].businessType
    },
    config: {
      id: NodeType.START_NODE + '_',
      x: 600,
      y: 200,
      properties: {
        // 默认录音，前端无录音开关，后端默认录音
        asrEngine: '',
        ttsEngine: '',
        name: NodeMetadata[NodeType.START_NODE].name,
        businessType: NodeType.START_NODE
      }
    }
  },
  {
    meta: {
      type: NodeType.END_NODE,
      name: NodeMetadata[NodeType.END_NODE].name,
      des: '流程结束节点，定义IVR流程的出口',
      bgc: 'linear-gradient(270deg, #f53f3f 0%, #f77062 100%)',
      img: endImg,
      businessType: NodeMetadata[NodeType.END_NODE].businessType
    },
    config: {
      id: NodeType.END_NODE + '_',
      x: 600,
      y: 200,
      properties: {
        // 默认挂机，前端无挂机开关，后端默认挂机
        playbackType: 1,
        fileId: '',
        content: '',
        num: 1,
        name: NodeMetadata[NodeType.END_NODE].name,
        businessType: NodeType.END_NODE
      }
    }
  },
  {
    meta: {
      type: NodeType.PLAYBACK_NODE,
      name: NodeMetadata[NodeType.PLAYBACK_NODE].name,
      des: '用于播放音频文件或文字转语音，通常用作开场的欢迎语和模块间的过渡使用',
      bgc: 'linear-gradient(270deg, #9258f7 0%, #3370FF 100%)',
      img: playBackImg,
      businessType: NodeMetadata[NodeType.PLAYBACK_NODE].businessType
    },
    config: {
      id: NodeType.PLAYBACK_NODE + '_',
      x: 600,
      y: 200,
      properties: {
        playbackType: 1,
        fileId: '',
        content: '',
        num: 1,
        name: NodeMetadata[NodeType.PLAYBACK_NODE].name,
        businessType: NodeType.PLAYBACK_NODE
      }
    }
  },
  {
    meta: {
      type: NodeType.TRANSFER_NODE,
      name: NodeMetadata[NodeType.TRANSFER_NODE].name,
      des: '用于转接坐席、坐席组、外呼、sip',
      bgc: 'linear-gradient(270deg, #9258f7 0%, #3370FF 100%)',
      img: transferImg,
      businessType: NodeMetadata[NodeType.TRANSFER_NODE].businessType
    },
    config: {
      id: NodeType.TRANSFER_NODE + '_',
      x: 600,
      y: 200,
      properties: {
        routeType: '1',
        routeValue: '',
        routeNumber: '',
        // 转接前/未接通/接通三组播放内容默认值
        prePlaybackType: 1,
        preFileId: '',
        preContent: '',
        preNum: 1,
        failPlaybackType: 1,
        failFileId: '',
        failContent: '',
        failNum: 1,
        connPlaybackType: 1,
        connFileId: '',
        connContent: '',
        connNum: 1,
        name: NodeMetadata[NodeType.TRANSFER_NODE].name,
        businessType: NodeType.TRANSFER_NODE
      }
    }
  },
  {
    meta: {
      type: NodeType.RECEIVE_NODE,
      name: NodeMetadata[NodeType.RECEIVE_NODE].name,
      des: '播放内容并接收用户按键输入',
      bgc: 'linear-gradient(270deg, #14c0ff 0%, #3370ff 100%)',
      img: receiveIcon,
      businessType: NodeMetadata[NodeType.RECEIVE_NODE].businessType
    },
    config: {
      id: NodeType.RECEIVE_NODE + '_',
      x: 600,
      y: 300,
      properties: {
        playbackType: 1,
        fileId: '',
        content: '',
        num: 1,
        interruptible: false,
        firstDigitTimeout: 5,
        interDigitTimeout: 2,
        debounceInterval: 200,
        endKey: '#',
        voiceCollect: false,
        name: NodeMetadata[NodeType.RECEIVE_NODE].name,
        businessType: NodeType.RECEIVE_NODE
      }
    }
  },
  {
    meta: {
      type: NodeType.CONDITION_NODE,
      name: NodeMetadata[NodeType.CONDITION_NODE].name,
      des: '根据条件判断执行不同分支',
      bgc: 'linear-gradient(270deg, #722ed1 0%, #3370ff 100%)',
      img: conditionIcon,
      businessType: NodeMetadata[NodeType.CONDITION_NODE].businessType
    },
    config: {
      id: NodeType.CONDITION_NODE + '_',
      x: 600,
      y: 500,
      properties: {
        branches: [
          {
            branchType: 'IF',
            matchType: 'ALL',
            conditions: [
              { variable: '', operator: '', value: '' }
            ]
          },
          {
            branchType: 'ELSE',
            conditions: []
          }
        ],
        name: NodeMetadata[NodeType.CONDITION_NODE].name,
        businessType: NodeType.CONDITION_NODE
      }
    }
  },
  {
    meta: {
      type: NodeType.METHOD_NODE,
      name: NodeMetadata[NodeType.METHOD_NODE].name,
      des: '调用内置方法并可选播放等待内容',
      bgc: 'linear-gradient(270deg, #00c9b7 0%, #3370ff 100%)',
      img: methodIcon,
      businessType: NodeMetadata[NodeType.METHOD_NODE].businessType
    },
    config: {
      id: NodeType.METHOD_NODE + '_',
      x: 600,
      y: 700,
      properties: {
        method: 1,
        playbackType: 1,
        fileId: '',
        content: '',
        num: 1,
        name: NodeMetadata[NodeType.METHOD_NODE].name,
        businessType: NodeType.METHOD_NODE
      }
    }
  },
  {
    meta: {
      type: NodeType.AI_NODE,
      name: NodeMetadata[NodeType.AI_NODE].name,
      des: '接入 AI 智能客服，识别中断词退出或多轮对话后转人工/放音',
      bgc: 'linear-gradient(270deg, #36cfc9 0%, #3370ff 100%)',
      img: aiIcon,
      businessType: NodeMetadata[NodeType.AI_NODE].businessType
    },
    config: {
      id: NodeType.AI_NODE + '_',
      x: 600,
      y: 820,
      properties: {
        roleId: undefined,
        interruptWords: [],
        welcomeContent: '',
        maxTurns: 10,
        silenceTimeoutSeconds: 10,
        name: NodeMetadata[NodeType.AI_NODE].name,
        businessType: NodeType.AI_NODE
      }
    }
  }
]

/**
 * IVR状态接口定义
 * 定义了IVR系统中需要管理的状态数据结构
 */
interface IvrState {
  /** 画布引用，用于操作流程图画布 */
  lfRef: any
  /** 节点列表，存储所有IVR节点 */
  nodeList: any[]
  /** 节点配置对象，以节点ID为键存储节点详细配置 */
  nodes: Record<string, any>
}

/**
 * IVR Store
 * 用于管理IVR系统的状态、节点配置和画布操作
 */
export const useIvrStore = defineStore('ivr', {
  /**
   * 状态定义
   * 返回IVR系统的初始状态配置
   */
  state: (): IvrState => {
    return {
      // 画布引用，初始为null，将在组件中赋值
      lfRef: null,
      // 节点列表 从统一配置派生nodeList（仅提取meta信息）
      nodeList: allNodeDefinitions.map((def) => def.meta),
      // 节点配置对象 从统一配置派生nodes（组合config和type）
      nodes: Object.fromEntries(
        allNodeDefinitions.map((def) => [def.meta.type, { ...def.config, type: def.meta.type }])
      )
    }
  },

  /**
   * Getter函数
   * 提供对状态的只读访问和计算属性
   */
  getters: {
    /**
     * 获取画布引用
     * @returns 画布实例引用
     */
    getLf(): any {
      return this.lfRef
    },

    /**
     * 获取节点列表
     * @returns 所有IVR节点的数组
     */
    getNodeList(): any[] {
      return this.nodeList
    },

    /**
     * 获取节点配置对象
     * @returns 以节点ID为键的配置对象
     */
    getNodes(): Record<string, any> {
      return this.nodes
    }
  },

  /**
   * Action函数
   * 提供修改状态的方法，可以包含异步操作
   */
  actions: {
    /**
     * 设置画布引用
     * @param value - 画布实例
     */
    async setLfRef(value: any) {
      this.lfRef = value
    },

    /**
     * 设置节点配置
     * @param keys - 节点键名或键名数组
     * @param value - 要设置的节点配置值
     */
    async setNodes(keys: any, value: Object) {
      this.nodes[keys] = value
    }
  }
})

/**
 * 在Vue组件外使用IVR Store的辅助函数
 * @returns IVR Store实例
 */
export const useIvrStoreWithOut = () => {
  return useIvrStore(store)
}
