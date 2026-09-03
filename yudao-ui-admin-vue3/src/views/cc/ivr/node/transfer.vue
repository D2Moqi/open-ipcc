<template>
  <div
    class="node-box node-transfer"
    @mousedown="onNodeMouseDown"
    @pointerdown="onNodePointerDown"
    @click="onNodeClick"
  >
    <div class="node-title">
      <div class="title-left">
        <div class="img-box" style="background:linear-gradient(270deg,#9258f7 0%,#3370FF 100%)">
          <img src="@/assets/ivr/transfer.svg" alt="" class="w-14 h-14" />
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
        <span class="form-label">路由类型</span>
        <el-select
          v-model="formState.routeType"
          placeholder="请选择路由类型"
          @change="handleRouteTypeChange"
          :teleported="true"
          clearable
          size="small"
          class="form-ctrl"
        >
          <el-option v-for="item in routeTypeOptions" :key="item.value" :label="item.label" :value="item.value" />
        </el-select>
      </div>
      <!-- 坐席 -->
      <div class="form-row" v-if="formState.routeType === ROUTE_TYPE.AGENT">
        <span class="form-label">{{ routeValueLabel }}</span>
        <el-select
          v-model="formState.routeValue"
          placeholder="请选择坐席或输入坐席号码/变量"
          @change="updateProperties"
          :teleported="true"
          clearable
          filterable
          allow-create
          default-first-option
          size="small"
          class="form-ctrl"
        >
          <el-option v-for="item in agentOptions" :key="item.id" :label="item.name" :value="item.name" />
        </el-select>
      </div>
      <!-- 外呼 -->
      <template v-if="formState.routeType === ROUTE_TYPE.OUTBOUND">
        <div class="form-row">
          <span class="form-label">网关</span>
          <el-select
            v-model="formState.routeValue"
            placeholder="请选择网关"
            @change="updateProperties"
            :teleported="true"
            clearable
            filterable
            size="small"
            class="form-ctrl"
          >
            <el-option v-for="item in gatewayOptions" :key="item.id" :label="item.name" :value="String(item.id)" />
          </el-select>
        </div>
        <div class="form-row">
          <span class="form-label">号码</span>
          <el-input
            v-model="formState.routeNumber"
            placeholder="请输入号码"
            @change="updateProperties"
            clearable
            size="small"
            class="form-ctrl"
          />
        </div>
      </template>
      <!-- 坐席组 -->
      <div class="form-row" v-if="formState.routeType === ROUTE_TYPE.AGENT_GROUP">
        <span class="form-label">坐席组</span>
        <el-select
          v-model="formState.routeValue"
          placeholder="请选择坐席组"
          @change="updateProperties"
          :teleported="true"
          clearable
          filterable
          size="small"
          class="form-ctrl"
        >
          <el-option v-for="item in agentGroupOptions" :key="item.id" :label="item.name" :value="String(item.id)" />
        </el-select>
      </div>
      <!-- SIP -->
      <div class="form-row" v-if="formState.routeType === ROUTE_TYPE.SIP">
        <span class="form-label">SIP</span>
        <el-input
          v-model="formState.routeValue"
          placeholder="请输入SIP地址"
          @change="updateProperties"
          clearable
          size="small"
          class="form-ctrl"
        />
      </div>
      <el-divider content-position="center">转接前播放内容</el-divider>
      <PlaybackContent v-model="prePlaybackContent" @update:modelValue="updateProperties" />
      <el-divider content-position="center">未接通播放内容</el-divider>
      <PlaybackContent v-model="failPlaybackContent" @update:modelValue="updateProperties" />
      <el-divider content-position="center">接通播放内容</el-divider>
      <PlaybackContent v-model="connPlaybackContent" @update:modelValue="updateProperties" />
      <div class="form-row output-row">
        <span class="form-label">输出值</span>
        <OutputValue label="当前应答号码" output-key="answerNumber" />
      </div>
    </div>
  </div>
</template>

<script lang="ts">
import { defineComponent } from 'vue'
import { useIvrStore } from '../store/ivr'
import { generateRandomString } from '../utils/node'
import { stopFormEventBubble } from './utils/formEventGuard'
import { syncNodeSize } from './utils/nodeResize'
import { SysAgentApi, SysAgentVO } from '@/api/cc/sysagent'
import { SysAgentGroupApi, SysAgentGroupVO } from '@/api/cc/sysagentgroup'
import { SipProxyGatewayApi, SipProxyGatewayVO } from '@/api/cc/sipproxygateway'
import { NodeType, PlaybackType } from '@/views/cc/ivr/consts/ivrEnum'
import PlaybackContent from './components/PlaybackContent.vue'
import OutputValue from './components/OutputValue.vue'

const ROUTE_TYPE = {
  AGENT: '1',
  OUTBOUND: '2',
  SIP: '3',
  AGENT_GROUP: '4'
} as const

const message = useMessage()
const useStore = useIvrStore()

export default defineComponent({
  name: NodeType.TRANSFER_NODE,
  components: { PlaybackContent, OutputValue },
  inject: ['getNode', 'getGraph'],
  data() {
    return {
      ROUTE_TYPE,
      formState: {
        routeType: ROUTE_TYPE.AGENT as string,
        routeValue: '',
        routeNumber: '',
        prePlaybackType: PlaybackType.VOICE_FILE,
        preFileId: '',
        preContent: '',
        preNum: 1,
        failPlaybackType: PlaybackType.VOICE_FILE,
        failFileId: '',
        failContent: '',
        failNum: 1,
        connPlaybackType: PlaybackType.VOICE_FILE,
        connFileId: '',
        connContent: '',
        connNum: 1
      },
      name: '',
      id: NodeType.TRANSFER_NODE + '_',
      routeTypeOptions: [
        { value: ROUTE_TYPE.AGENT, label: '坐席' },
        { value: ROUTE_TYPE.OUTBOUND, label: '外呼' },
        { value: ROUTE_TYPE.SIP, label: 'sip' },
        { value: ROUTE_TYPE.AGENT_GROUP, label: '坐席组' }
      ],
      agentOptions: [] as SysAgentVO[],
      agentGroupOptions: [] as SysAgentGroupVO[],
      gatewayOptions: [] as SipProxyGatewayVO[]
    }
  },
  computed: {
    routeValueLabel(): string {
      const typeMap: Record<string, string> = {
        [ROUTE_TYPE.AGENT]: '坐席',
        [ROUTE_TYPE.OUTBOUND]: '网关',
        [ROUTE_TYPE.SIP]: 'SIP',
        [ROUTE_TYPE.AGENT_GROUP]: '坐席组'
      }
      return typeMap[this.formState.routeType] || '路由值'
    },
    prePlaybackContent: {
      get() {
        return {
          playbackType: this.formState.prePlaybackType,
          fileId: this.formState.preFileId,
          content: this.formState.preContent,
          num: this.formState.preNum
        }
      },
      set(val: any) {
        Object.assign(this.formState, {
          prePlaybackType: val.playbackType,
          preFileId: val.fileId,
          preContent: val.content,
          preNum: val.num
        })
      }
    },
    failPlaybackContent: {
      get() {
        return {
          playbackType: this.formState.failPlaybackType,
          fileId: this.formState.failFileId,
          content: this.formState.failContent,
          num: this.formState.failNum
        }
      },
      set(val: any) {
        Object.assign(this.formState, {
          failPlaybackType: val.playbackType,
          failFileId: val.fileId,
          failContent: val.content,
          failNum: val.num
        })
      }
    },
    connPlaybackContent: {
      get() {
        return {
          playbackType: this.formState.connPlaybackType,
          fileId: this.formState.connFileId,
          content: this.formState.connContent,
          num: this.formState.connNum
        }
      },
      set(val: any) {
        Object.assign(this.formState, {
          connPlaybackType: val.playbackType,
          connFileId: val.fileId,
          connContent: val.content,
          connNum: val.num
        })
      }
    }
  },
  async mounted() {
    await Promise.all([
      this.loadAgentOptions(),
      this.loadAgentGroupOptions(),
      this.loadGatewayOptions()
    ])
    const node = (this as any).getNode()
    const graph = (this as any).getGraph()
    const { nodes } = graph
    const index = nodes.findIndex((item: any) => item && item.id == node.id)
    if (index === -1) {
      // 新添加节点，使用默认名称
      this.name = '转接'
      return
    }
    const transferArr = nodes.filter(
      (item: any) => item && item.properties && item.properties.businessType == NodeType.TRANSFER_NODE
    )
    const props = nodes[index].properties
    this.name = (props.name || '转接') + (transferArr.length - 1 == 0 ? '' : transferArr.length - 1)
    Object.assign(this.formState, {
      routeType: props.routeType || ROUTE_TYPE.AGENT,
      routeValue: props.routeValue || '',
      routeNumber: props.routeNumber || '',
      prePlaybackType: props.prePlaybackType,
      preFileId: props.preFileId,
      preContent: props.preContent,
      preNum: props.preNum,
      failPlaybackType: props.failPlaybackType,
      failFileId: props.failFileId,
      failContent: props.failContent,
      failNum: props.failNum,
      connPlaybackType: props.connPlaybackType,
      connFileId: props.connFileId,
      connContent: props.connContent,
      connNum: props.connNum
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
     * 路由类型切换时清空已选路由值和号码
     * 不同路由类型展示的表单项不同，切换后需同步节点尺寸
     */
    async handleRouteTypeChange() {
      this.formState.routeValue = ''
      this.formState.routeNumber = ''
      await this.updateProperties()
    },
    /**
     * 将表单数据同步到 LogicFlow 节点属性
     * 放音类型切换、路由类型切换均会改变 DOM 高度，需在 nextTick 后同步 foreignObject 尺寸，
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
    },
    async loadAgentOptions() {
      try {
        this.agentOptions = await SysAgentApi.list()
      } catch (e) {
        console.error('加载坐席列表失败', e)
      }
    },
    async loadAgentGroupOptions() {
      try {
        this.agentGroupOptions = await SysAgentGroupApi.list()
      } catch (e) {
        console.error('加载坐席组列表失败', e)
      }
    },
    async loadGatewayOptions() {
      try {
        this.gatewayOptions = await SipProxyGatewayApi.getSimpleList()
      } catch (e) {
        console.error('加载网关列表失败', e)
      }
    }
  }
})
</script>
<style scoped>
/* 转接节点样式已移至全局 node-common.css */
</style>
