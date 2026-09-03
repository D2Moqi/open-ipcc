<template>
  <div class="soft-phone-bar">
    <div class="bar-section bar-auth">
      <el-button
        :type="isOnline ? 'primary' : 'default'"
        circle
        size="default"
        @click="toggleLogin"
        :loading="isLoginLoading"
      >
        <el-icon><Avatar /></el-icon>
      </el-button>
    </div>

    <div class="bar-divider"></div>

    <div class="bar-section bar-status">
      <span v-if="!isOnline" class="offline-tag">
        <span class="offline-dot"></span>
        离线
      </span>

      <div v-else class="switch-wrap">
        <el-switch
          :model-value="switchValue"
          @change="handleSwitchChange"
          :disabled="isInCall"
          style="--el-switch-on-color: #67c23a; --el-switch-off-color: #e6a23c"
        />
        <span :class="['switch-label', switchValue ? 'switch-label--ready' : 'switch-label--busy']">
          {{ switchValue ? '就绪' : '忙碌' }}
        </span>
      </div>
    </div>

    <template v-if="isOnline">
      <div class="bar-divider"></div>
      <div class="bar-section bar-dial">
        <el-button
          type="success"
          circle
          size="default"
          :disabled="isInCall"
          @click="showDialPopup = !showDialPopup"
        >
          <el-icon><PhoneFilled /></el-icon>
        </el-button>
      </div>
    </template>

    <!-- 拨号弹窗 (非通话中) -->
    <div v-if="showDialPopup && !isInCall" class="popover">
      <div class="popover-header">
        <span class="popover-title">拨号</span>
        <button class="popover-close" @click="showDialPopup = false">
          <el-icon><Close /></el-icon>
        </button>
      </div>
      <div class="popover-body">
        <!-- 呼叫类型单选：外呼(0,默认) / 内部呼叫(1) -->
        <el-radio-group v-model="callType" size="small" style="width: 100%; margin-bottom: 8px">
          <el-radio-button :value="0">外呼</el-radio-button>
          <el-radio-button :value="1">内部呼叫</el-radio-button>
        </el-radio-group>
        <!-- 外呼时显示网关选择（非必填）；内部呼叫时隐藏 -->
        <el-select
          v-if="callType === 0"
          v-model="gatewayId"
          placeholder="选择网关(非必填,可直接拨打)"
          clearable
          size="default"
          style="width: 100%; margin-bottom: 8px"
        >
          <el-option v-for="gw in gatewayList" :key="gw.id" :label="gw.name" :value="gw.id" />
        </el-select>
        <input
          class="dial-input"
          placeholder="输入号码"
          :value="phoneNumber"
          @input="handlePhoneNumberChange(($event.target as HTMLInputElement).value)"
        />
        <div class="dialpad-grid">
          <button
            v-for="key in ['1', '2', '3', '4', '5', '6', '7', '8', '9', '*', '0', '#']"
            :key="key"
            class="dialpad-key"
            @click="handleDialInput(key)"
          >
            {{ key }}
          </button>
        </div>
        <div class="dialpad-actions">
          <button class="dialpad-act dialpad-act--default" @click="handleDelete">
            <el-icon><Delete /></el-icon>
            回退
          </button>
          <button
            class="dialpad-act dialpad-act--primary"
            @click="makeCall(); showDialPopup = false"
          >
            <el-icon><PhoneFilled /></el-icon>
            拨打
          </button>
        </div>
      </div>
    </div>

    <!-- 通话中弹窗 -->
    <div v-if="isInCall" class="popover">
      <!-- 多通话列表 (有多个会话时显示) -->
      <div v-if="sessionList.length > 1" class="session-list">
        <div class="session-list-header">通话列表</div>
        <div
          v-for="item in sessionList"
          :key="item.callId"
          :class="['session-item', { 'session-item--active': item.callId === activeCallId }]"
          @click="switchActiveSession(item.callId)"
        >
          <span class="session-item-number">{{ item.number }}</span>
          <span :class="['session-item-status', `session-item-status--${item.status}`]">
            {{ sessionStatusText(item.status) }}
          </span>
        </div>
      </div>

      <!-- 当前焦点会话信息 -->
      <div class="active-call">
        <div class="active-call-timer">{{ statusDuration }}</div>
        <div class="active-call-number">{{ activeSessionNumber }}</div>

        <!-- 通话控制按钮: 保持/静音/转接 -->
        <div class="call-controls">
          <button
            :class="['call-ctrl-btn', isHeld ? 'call-ctrl-btn--active' : '']"
            :disabled="!canHold"
            @click="toggleHold"
          >
            {{ isHeld ? '恢复' : '保持' }}
          </button>
          <button
            :class="['call-ctrl-btn', isMuted ? 'call-ctrl-btn--active' : '']"
            :disabled="!canMute"
            @click="toggleMute"
          >
            {{ isMuted ? '取消静音' : '静音' }}
          </button>
          <button
            class="call-ctrl-btn call-ctrl-btn--transfer"
            :disabled="!canTransfer"
            @click="showTransferPopup = !showTransferPopup"
          >
            转接
          </button>
        </div>

        <!-- 转接弹窗(通话中) -->
        <div v-if="showTransferPopup && isInCall" class="transfer-panel">
          <div class="popover-header">
            <span class="popover-title">咨询转接</span>
            <button class="popover-close" @click="showTransferPopup = false">
              <el-icon><Close /></el-icon>
            </button>
          </div>
          <div class="popover-body">
            <!-- 转接类型: 咨询转接(默认) / 盲转 -->
            <el-radio-group
              v-model="transferType"
              size="small"
              style="width: 100%; margin-bottom: 8px"
            >
              <el-radio-button value="attended">咨询转接</el-radio-button>
              <el-radio-button value="blind">盲转</el-radio-button>
            </el-radio-group>
            <!-- 出局网关选择(非必填,未选则走号码路由) -->
            <el-select
              v-model="transferGatewayId"
              placeholder="选择网关(非必填)"
              clearable
              size="default"
              style="width: 100%; margin-bottom: 8px"
            >
              <el-option v-for="gw in gatewayList" :key="gw.id" :label="gw.name" :value="gw.id" />
            </el-select>
            <input
              class="dial-input"
              placeholder="输入转接目标号码"
              :value="transferTarget"
              @input="transferTarget = ($event.target as HTMLInputElement).value"
              @keyup.enter="handleTransfer"
            />
            <div class="dialpad-actions">
              <button class="dialpad-act dialpad-act--default" @click="showTransferPopup = false">
                取消
              </button>
              <button
                class="dialpad-act dialpad-act--primary"
                :disabled="!transferTarget.trim()"
                @click="handleTransfer"
              >
                确认转接
              </button>
            </div>
          </div>
        </div>

        <button class="hangup-full" @click="handleHangup">
          <el-icon><Close /></el-icon>
          挂断
        </button>

        <!-- DTMF拨号盘 (通话中发送DTMF信号) -->
        <div class="dialpad-grid dialpad-grid--incall">
          <button
            v-for="key in ['1', '2', '3', '4', '5', '6', '7', '8', '9', '*', '0', '#']"
            :key="key"
            class="dialpad-key dialpad-key--incall"
            @click="sendDTMF(key)"
          >
            {{ key }}
          </button>
        </div>
      </div>
    </div>
  </div>

  <!-- 来电弹窗 -->
  <Teleport to="body">
    <div v-if="incomingCallFlag" class="incoming-overlay"></div>
    <div v-if="incomingCallFlag" class="incoming-dialog">
      <div class="incoming-header">
        <div class="incoming-avatar">
          <el-icon :size="24"><PhoneFilled /></el-icon>
        </div>
        <div class="incoming-title">来电</div>
        <div class="incoming-number">{{ incomingCallNumber }}</div>
      </div>
      <div class="incoming-actions">
        <button class="incoming-btn incoming-btn--reject" @click="handleRejectIncoming">
          <el-icon><Close /></el-icon>
          挂断
        </button>
        <button class="incoming-btn incoming-btn--accept" @click="handleAnswer">
          <el-icon><PhoneFilled /></el-icon>
          接听
        </button>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, markRaw, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import JsSIP from 'jssip'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getRefreshToken } from '@/utils/auth'
import ringing from '@/assets/cc/ringing.wav'
import {
  initWebsocketClient,
  offAgentStatusChanged,
  offConnectionStateChange,
  offReconnected,
  onAgentStatusChanged,
  onConnectionStateChange,
  onReconnected,
  updateAgentStatus,
  WsConnectionState
} from './WebSocketClient'
import { SysSipAgentApi } from '@/api/cc/syssipagent'
import { Avatar, Close, Delete, PhoneFilled } from '@element-plus/icons-vue'

const message = ElMessage
const router = useRouter()

// ==================== ICE/STUN/TURN 配置开关 ====================
// 业务背景: 坐席软电话媒体走 WebRTC ICE 协商。NAT 后的浏览器仅靠 host 候选(私有IP)
// 无法让云端 FS 回程 RTP(实测挂断原因 INCOMPATIBLE_DESTINATION), 需 STUN 反射候选
// (srflx)通告公网可达地址。test-all 实测(sip_client.py): pjsua 关闭 ICE 仅用 STUN
// 改写 SDP 媒体地址即可双向通话, 说明 TURN 中继并非必需, 可关闭降低依赖与延迟。
// 控制方式: USE_ICE_CONFIG = true 保留原有行为(iceServers=STUN+TURN, 强制 relay);
//           false 时仅保留 STUN 反射(不强制 relay, 不用 TURN), 媒体直连优先。
// 注意: 修改后需重新构建, 通过前端远程部署脚本发布, 再以 test-all 场景验证通话。
const USE_ICE_CONFIG = false

const STUN_SERVERS = {
  urls: ['stun:39.107.224.184:3478']
}
const TURN_SERVERS = {
  urls: ['turn:39.107.224.184:3478'],
  username: 'yudao-cc',
  credential: 'yudao-cc'
}

/**
 * 构建 WebRTC pcConfig(ICE 配置)
 * <p>
 * 需求背景: 通过 USE_ICE_CONFIG 开关统一控制是否启用 ICE/STUN/TURN,
 * 便于在不同网络环境下切换媒体路径策略, 无需改动多个调用点。
 * 预期结果:
 * <ul>
 *   <li>true: 配置 STUN/TURN 并强制 relay, 媒体全部走 TURN 中继(NAT 后必通, 延迟较高)</li>
 *   <li>false: 仅配置 STUN 反射候选(不强制 relay, 不用 TURN), 媒体直连优先,
 *       依赖 ICE 协商 + FS 对称 RTP 学习机制回程(无 TURN 依赖)</li>
 * </ul>
 *
 * @return JsSIP pcConfig 对象(可直接用于 UA 注册/外呼/接听)
 */
const buildPcConfig = (): RTCConfiguration => {
  if (!USE_ICE_CONFIG) {
    // 关闭 TURN 中继与强制 relay: 仅保留 STUN 反射候选(srflx),
    // 与 test-all pjsua 关闭 ICE 仅用 STUN 的行为对齐, 不依赖 TURN
    return {
      iceServers: [STUN_SERVERS]
    }
  }
  return {
    iceServers: [STUN_SERVERS, TURN_SERVERS],
    // 强制前端和 fs 的 rtp 网络走 stun/turn 中继, 避免家庭网络等 NAT 场景回程不通
    iceTransportPolicy: 'relay'
  }
}

defineOptions({ name: 'SoftPhone' })

const loginValue = ref<string>('1')
const signInOutValue = ref<string>('2')
const agentStatusValue = ref<string>('4')
const isLoginLoading = ref<boolean>(false)
const isSignInDisabled = ref<boolean>(true)
const statusDuration = ref<string>('00:00:00')
const callTimer = ref<any>(null)
const phoneNumber = ref<string>('')
const incomingCallFlag = ref<boolean>(false)
const incomingCallNumber = ref<string>('')

const gatewayList = ref<any[]>([])
const gatewayId = ref<any>(null)
/** 呼叫类型：0-外呼（默认），1-内部呼叫；外呼显示网关下拉框，内部呼叫隐藏 */
const callType = ref<number>(0)
const showDialPopup = ref(false)

/** 转接弹窗显示状态 */
const showTransferPopup = ref(false)
/** 转接目标号码 */
const transferTarget = ref<string>('')
/** 转接类型: attended-咨询转接(默认), blind-盲转 */
const transferType = ref<string>('attended')
/** 转接出局网关ID(非必填,未选则走号码路由) */
const transferGatewayId = ref<any>(null)

const isOnline = computed(() => loginValue.value === '2')
const switchValue = computed(() => agentStatusValue.value === '1')

// ==================== 多会话管理 ====================

/** 会话信息接口，存储每个通话的完整状态 */
interface SessionInfo {
  session: any // JsSIP RTCSession 对象
  number: string // 对方号码
  status: 'ringing' | 'active' | 'held' // 会话状态
  isMuted: boolean // 静音状态
  isHeld: boolean // 保持状态
  direction: 'incoming' | 'outgoing' // 呼入/呼出
  startTime: Date | null // 通话确认时间，用于计时
  stream: MediaStream | null // 远端音频流
  iceController: IceGatheringController // ICE收集优化控制器
  // [MEDIA_DEBUG] 媒体诊断字段(仅测试用,验证完成后移除)
  statsTimer?: number | null // getStats 轮询定时器ID
  remoteAudioAnalyser?: AnalyserNode | null // 远端音频音量分析器
  remoteAudioContext?: AudioContext | null // 远端音频分析上下文
  testToneTimer?: number | null // 测试音播放定时器
}

/** 多会话Map: callId -> SessionInfo，支持多路通话 */
const sessions = ref(new Map<string, SessionInfo>())

/** 当前操作焦点的会话ID */
const activeCallId = ref<string | null>(null)

/** 来电弹窗对应的会话ID，用于区分来电拒绝和活跃会话挂断 */
const incomingCallId = ref<string | null>(null)

/** 向后兼容: 返回当前焦点会话的JsSIP Session对象 */
const currentSession = computed(() => {
  if (!activeCallId.value) return null
  return sessions.value.get(activeCallId.value)?.session ?? null
})

/** 当前焦点会话的SessionInfo */
const currentSessionInfo = computed(() => {
  if (!activeCallId.value) return null
  return sessions.value.get(activeCallId.value) ?? null
})

/** 是否在通话中: 有活跃会话即为通话中 */
const isInCall = computed(() => sessions.value.size > 0)

/** 当前焦点会话的对方号码 */
const activeSessionNumber = computed(() => currentSessionInfo.value?.number ?? '')

/** 当前焦点会话是否保持 */
const isHeld = computed(() => currentSessionInfo.value?.isHeld ?? false)

/** 当前焦点会话是否静音 */
const isMuted = computed(() => currentSessionInfo.value?.isMuted ?? false)

/** 是否可以操作保持: 通话已确认(非振铃)才可保持 */
const canHold = computed(() => {
  const info = currentSessionInfo.value
  return info != null && (info.status === 'active' || info.status === 'held')
})

/** 是否可以操作静音: 通话已确认(非振铃)才可静音 */
const canMute = computed(() => {
  const info = currentSessionInfo.value
  return info != null && (info.status === 'active' || info.status === 'held')
})

/** 是否可以操作转接: 通话已确认(非振铃)才可转接 */
const canTransfer = computed(() => {
  const info = currentSessionInfo.value
  return info != null && (info.status === 'active' || info.status === 'held')
})

/** 会话列表，用于UI渲染多通话切换 */
const sessionList = computed(() => {
  const list: Array<{ callId: string; number: string; status: string }> = []
  sessions.value.forEach((info, callId) => {
    list.push({ callId, number: info.number, status: info.status })
  })
  return list
})

/** 会话状态文本映射 */
const sessionStatusText = (status: string): string => {
  const map: Record<string, string> = {
    ringing: '振铃中',
    active: '通话中',
    held: '保持中'
  }
  return map[status] || status
}

// ==================== ICE收集优化控制器 ====================

interface IceGatheringController {
  timeout: any
  readyTriggered: boolean
}

const createIceGatheringController = (): IceGatheringController => ({
  timeout: null,
  readyTriggered: false
})

const handleIceCandidate = (
  data: { candidate: any; ready: () => void },
  controller: IceGatheringController,
  context: string = '',
  timeoutMs: number = 2000
) => {
  const { candidate, ready } = data

  if (candidate) {
    console.log(`${context} ICE candidate:`, candidate.candidate)

    if (!controller.timeout && !controller.readyTriggered) {
      const candidateStr = candidate.candidate as string
      if (candidateStr.includes('typ relay') || candidateStr.includes('typ srflx')) {
        controller.timeout = setTimeout(() => {
          if (!controller.readyTriggered) {
            controller.readyTriggered = true
            ready()
          }
        }, timeoutMs)
      }
    }
  } else {
    if (controller.timeout) {
      clearTimeout(controller.timeout)
      controller.timeout = null
    }
    controller.readyTriggered = false
  }
}

const cleanupIceController = (controller: IceGatheringController) => {
  if (controller.timeout) {
    clearTimeout(controller.timeout)
    controller.timeout = null
  }
  controller.readyTriggered = false
}

// ==================== 其他状态和工具函数 ====================

/**
 * 构建 sipproxy WebSocket URL
 * <p>
 * 业务背景：sipproxy Starter 独立提供 SIP over WebSocket 入口，路径由后端
 * {@code sipproxy.websocket.path}（默认 {@code /sipproxy/ws}）统一管理，
 * 与原 {@code /cc/ws}（业务消息通道）解耦。
 * <p>
 * 设计约束：
 * <ul>
 *   <li>仅携带 {@code token} 参数，供 {@code SipHandshakeInterceptor} 提取并交由
 *       {@code CcWsHandshakeAuthenticator}（基于 Spring Security 上下文）校验</li>
 *   <li>不再携带 {@code type=jssip}，sipproxy 仅依据子协议 {@code sip} 协商，
 *       避免与原业务 WebSocket 路径参数耦合</li>
 * </ul>
 *
 * @return 形如 {@code ws://host:port/sipproxy/ws?token=xxx} 的完整 WS URL
 */
const getSipWsUrl = () => {
  return (
    (import.meta.env.VITE_BASE_URL + '/sipproxy/ws').replace('http', 'ws') +
    '?token=' +
    getRefreshToken()
  )
}
const agentInfo = ref<any>(null)

let ua: JsSIP.UA | undefined
let audioView = new Audio()
let keepAliveTimer: any = null
// SIP OPTIONS 心跳间隔(毫秒): 30s。必须小于后端 sipproxy.heartbeat.idle-timeout(90s)，
// 否则坐席空闲超过 90s 后 WS 会话被清理，转接/来话 INVITE 无法送达(408)
const KEEP_ALIVE_INTERVAL = 30000

/**
 * 标志位：标识当前 agentStatusValue 变更是否由服务端推送触发
 * <p>用于避免"服务端推送 → 更新值 → watch → updateAgentStatus → 再推送"的循环。
 * 在 handleAgentStatusChangedEvent 中置 true，nextTick 后重置为 false。</p>
 */
let isUpdatingFromServer = false

/** 坐席状态码：话后（服务端在呼叫结束后推送，表示后端已确认通话结束） */
const AGENT_STATUS_AFTER_CALL = '7'

/**
 * 滞留会话兜底清理延迟（毫秒）
 * <p>
 * 业务消息通道（/cc/ws）的状态推送可能先于 SIP 通道（/sipproxy/ws）的 BYE 到达，
 * 延迟清理给 JsSIP 留出正常处理 BYE 并触发 'ended' 事件的时间，避免误清理健康会话。
 * </p>
 */
const STALE_SESSION_CLEANUP_DELAY = 3000

/** 滞留会话兜底清理定时器，避免重复调度 */
let staleSessionCleanupTimer: ReturnType<typeof setTimeout> | null = null

/**
 * 调度滞留会话兜底清理
 * <p>
 * 背景：JsSIP RTCSession 状态机存在竞态——坐席点击接听后
 * 会话进入 STATUS_ANSWERED，此时若对端 BYE 先于 200 发出到达（ICE 收集/SDP
 * 生成期间），JsSIP 以 403 Wrong Status 拒绝且不触发 'ended' 事件，会话滞留
 * sessions Map，导致通话条不回落、计时不停。同理 UA 找不到 dialog 时回 481
 * 也会滞留。前端通话条回落仅依赖 JsSIP 'ended'/'failed' 事件，故需兜底。
 * </p>
 * <p>
 * 触发条件：服务端推送话后状态（后端已确认呼叫结束）且本地 sessions 非空。
 * 延迟执行时再次校验 sessions，若 JsSIP 已正常处理 BYE（sessions 已清空）则不处理。
 * </p>
 */
const scheduleStaleSessionCleanup = () => {
  if (staleSessionCleanupTimer) return
  staleSessionCleanupTimer = setTimeout(() => {
    staleSessionCleanupTimer = null
    // JsSIP 已在延迟窗口内正常处理 BYE，无需兜底
    if (sessions.value.size === 0) return
    console.warn('[SoftPhone] 服务端已推送话后状态但本地会话滞留，兜底清理:', [
      ...sessions.value.keys()
    ])
    const callIds = [...sessions.value.keys()]
    callIds.forEach((callId) => {
      const info = sessions.value.get(callId)
      if (info?.session) {
        try {
          // terminate 会触发 'failed'/'ended' 事件完成本地资源释放；
          // 会话已处于 TERMINATED 等状态时可能抛异常，忽略即可
          info.session.terminate()
        } catch (e) {
          console.warn('[SoftPhone] terminate 滞留会话异常，忽略:', e)
        }
      }
      removeSession(callId)
    })
    clearCallTimer()
  }, STALE_SESSION_CLEANUP_DELAY)
}

/**
 * 处理服务端推送的坐席状态变更通知（AGENT_STATUS_CHANGED 事件回调）
 * <p>
 * 业务背景：服务端在坐席状态变更（如通话挂断、WebSocket 断连、其他端切换状态）后
 * 通过 AGENT_STATUS_CHANGED 事件推送，前端需同步更新 agentStatusValue 以保持 UI 一致。
 * <p>
 * 处理逻辑：
 *   1. 校验 agentInfo 已初始化且 agentId 匹配（避免跨坐席误更新）
 *   2. 状态相同则跳过，避免不必要的 watch 触发
 *   3. 设置 isUpdatingFromServer 标志跳过 watch 中的回推，避免循环
 *   4. nextTick 后重置标志，确保仅跳过当前同步触发的 watch
 *
 * @param agentId 坐席ID
 * @param onlineStatus 变更后的在线状态码（1-空闲 2-忙碌 3-勿扰 4-离线 5-通话中 6-振铃中 7-话后）
 */
const handleAgentStatusChangedEvent = (agentId: number, onlineStatus: number) => {
  // agentInfo 未初始化（未登录）或 agentId 不匹配时忽略，避免误更新
  if (!agentInfo.value || agentInfo.value.id !== agentId) return
  const newStatus = String(onlineStatus)
  // 服务端确认呼叫结束（话后）但本地仍有会话：JsSIP 未正确处理 BYE（403/481 竞态），
  // 调度延迟兜底清理，避免通话条永久不回落（须在状态相等早退判断之前，确保不被跳过）
  if (newStatus === AGENT_STATUS_AFTER_CALL && sessions.value.size > 0) {
    scheduleStaleSessionCleanup()
  }
  // 状态未变化时跳过，避免重复赋值触发 watch
  if (agentStatusValue.value === newStatus) return
  // 标记为服务端推送触发，跳过 watch 中的 updateAgentStatus 回推
  isUpdatingFromServer = true
  agentStatusValue.value = newStatus
  // nextTick 后重置标志，确保仅跳过当前同步触发的 watch 回调
  nextTick(() => {
    isUpdatingFromServer = false
  })
}

/**
 * WebSocket 重连成功后的业务状态同步处理
 * <p>
 * 业务背景: 后端服务重启会导致服务端内存中的坐席状态、WebSocket 会话信息丢失,
 * 即使前端 WebSocket 重连成功,服务端也无法识别当前坐席的真实状态,可能导致:
 * <ul>
 *   <li>坐席状态显示不一致(服务端将坐席置为离线,前端仍显示在线)</li>
 *   <li>INVITE 转发失败(服务端认为坐席离线,不在 FreeSWITCH 中订阅该坐席的状态)</li>
 *   <li>来电丢失(服务端找不到在线坐席,IVR 路由失败)</li>
 * </ul>
 * </p>
 * <p>
 * 处理逻辑:
 *   1. 未签入(loginValue='1')时无需同步,直接返回
 *   2. 重新查询坐席信息,确保 agentInfo 与后端最新数据一致
 *      (后端重启后 agentInfo 内存中的状态可能丢失,需重新加载)
 *   3. 主动将当前坐席状态推送到服务端,恢复服务端的坐席状态记录
 *   4. SIP UA 处理:
 *      - 若 ua 仍存在且已注册,JsSIP 自带连接恢复机制(connection_recovery_max_interval=60s),
 *        无需额外处理
 *      - 若 ua 不存在(从未签入或已卸载)但 loginValue='2'(用户此前已在线),
 *        说明 SIP 连接已彻底断开,需重新初始化 SIP 客户端完成注册
 * </p>
 * <p>
 * 设计约束:
 *   - 重连回调由 WebSocketClient 在 onopen 中触发,此时 WebSocket 已就绪可直接发送消息
 *   - isUpdatingFromServer 标志置 true 避免 watch 触发 updateAgentStatus 形成回推循环
 * </p>
 */
const handleWsReconnected = async () => {
  console.log('[SoftPhone] WebSocket 重连成功,开始同步业务状态')
  // 未签入时无需同步
  if (loginValue.value !== '2') {
    console.log('[SoftPhone] 坐席未签入,跳过状态同步')
    return
  }
  try {
    // 重新查询坐席信息,后端重启后内存中的状态可能丢失
    const newAgentInfo = await SysSipAgentApi.getSysSipAgentByUserId()
    if (!newAgentInfo) {
      console.warn('[SoftPhone] 重连后查询坐席信息为空,跳过状态同步')
      return
    }
    agentInfo.value = newAgentInfo
    console.log('[SoftPhone] 重连后坐席信息已刷新, agentId:', newAgentInfo.id)

    // 主动同步当前坐席状态到服务端,恢复服务端的坐席状态记录
    // 设置标志避免 watch 触发回推
    isUpdatingFromServer = true
    updateAgentStatus(newAgentInfo.id, agentStatusValue.value)
    nextTick(() => {
      isUpdatingFromServer = false
    })

    // SIP UA 不存在但前端显示在线,说明 SIP 连接已彻底断开,需重新初始化
    if (!ua) {
      console.warn('[SoftPhone] SIP UA 已卸载但前端显示在线,重新初始化 SIP 客户端')
      try {
        await initSipClient()
      } catch (e) {
        console.error('[SoftPhone] 重连后重新初始化 SIP 客户端失败:', e)
        message.error('SIP 重连失败,请重新签入')
      }
    } else {
      console.log('[SoftPhone] SIP UA 仍存在,依赖 JsSIP 自带连接恢复机制')
    }
  } catch (e) {
    console.error('[SoftPhone] 重连后状态同步异常:', e)
  }
}

/**
 * WebSocket 连接状态变更处理
 * <p>
 * 用于在控制台输出连接状态变化日志,便于排查连接问题。
 * 后续可扩展为 UI 提示(如在软电话栏显示"重连中"标识)。
 * </p>
 *
 * @param state 新的连接状态
 */
const handleWsConnectionStateChange = (state: WsConnectionState) => {
  switch (state) {
    case WsConnectionState.CONNECTED:
      console.log('[SoftPhone] WebSocket 已连接')
      break
    case WsConnectionState.RECONNECTING:
      console.warn('[SoftPhone] WebSocket 重连中,业务消息将缓存至队列')
      break
    case WsConnectionState.DISCONNECTED:
      console.warn('[SoftPhone] WebSocket 已断开')
      break
    case WsConnectionState.CONNECTING:
      console.log('[SoftPhone] WebSocket 连接中')
      break
  }
}

watch(agentStatusValue, (value) => {
  // 跳过由服务端推送触发的状态变更，避免回推形成循环
  if (isUpdatingFromServer) return
  handleAgentStatusChange(value)
})

watch(isInCall, (val) => {
  if (val) {
    showDialPopup.value = false
  }
})

/**
 * 监听呼叫类型切换：
 * - 切到内部呼叫时清空已选网关（内部呼叫不走网关）
 * - 切回外呼时不自动选择网关（由用户手动选择或留空）
 */
watch(callType, (val) => {
  if (val === 1) {
    gatewayId.value = null
  }
})

/**
 * 监听拨号弹窗显隐：
 * - 每次打开拨号弹窗时重新查询当前坐席所属坐席组绑定的可用网关列表，
 *   确保弹窗展示的网关数据始终为最新（坐席组配置可能在上次打开后被修改）
 */
watch(showDialPopup, (val) => {
  if (val) {
    loadGatewayList()
  }
})

onMounted(async () => {
  // 连接ws
  initWebsocketClient()
  // 订阅坐席状态变更通知,同步更新本地 agentStatusValue
  onAgentStatusChanged(handleAgentStatusChangedEvent)
  // 订阅 WebSocket 重连成功事件,后端服务重启后自动同步业务状态
  onReconnected(handleWsReconnected)
  // 订阅连接状态变更,用于 UI 提示(后续可扩展显示"重连中"标识)
  onConnectionStateChange(handleWsConnectionStateChange)
})

const ringAudio = new Audio(ringing)

const handleAgentStatusChange = (value: string) => {
  computeStatusDuration()
  // 坐席状态
  updateAgentStatus(agentInfo.value.id, value)
}

/**
 * 切换签入/签出状态
 *
 * 需求: 点击头像按钮触发 SIP REGISTER 注册/取消注册流程
 * 预期结果:
 *   - 签入: SIP REGISTER 成功后 UI 切换到在线状态(.switch-wrap 显示)
 *   - 签出: SIP unregister 后 UI 切换到离线状态(.offline-tag 显示)
 * 处理逻辑:
 *   1. 签入时不立即设置 loginValue='2',而是在 registerSipEvents 的 registered 事件回调中设置
 *      设计意图: UI 状态必须反映真实 REGISTER 状态,避免 UI 显示在线但实际未注册导致 INVITE 转发失败
 *   2. 签入失败(STUN 超时/WebSocket 错误/REGISTER 403)时 isLoginLoading 恢复 false,UI 保持离线
 *   3. 签出时立即设置离线,然后异步 unregister
 */
const toggleLogin = async () => {
  if (loginValue.value === '1') {
    // 不在此处设置 loginValue='2',等 REGISTER 成功后在 registerSipEvents 的 registered 事件中设置
    isLoginLoading.value = true
    isSignInDisabled.value = false
    computeStatusDuration()
    try {
      await initSipClient()
    } catch (e) {
      console.error('SIP 客户端初始化失败:', e)
      message.error('SIP 签入失败,请检查网络或联系管理员')
    } finally {
      isLoginLoading.value = false
    }
  } else if (loginValue.value === '2') {
    loginValue.value = '1'
    isLoginLoading.value = true
    signInOutValue.value = '2'
    isSignInDisabled.value = true
    clearCallTimer()
    agentStatusValue.value = '4'
    if (ua) {
      ua.unregister()
      console.log('sip-取消注册成功')
    }
    unregisterSipClient()
    isLoginLoading.value = false
  }
}

const clearCallTimer = () => {
  if (callTimer.value) {
    clearInterval(callTimer.value)
    statusDuration.value = '00:00:00'
  }
}

/**
 * 计算当前焦点会话的通话时长
 * 根据活跃会话的startTime持续更新显示
 */
const computeStatusDuration = () => {
  if (callTimer.value) {
    statusDuration.value = '00:00:00'
    clearInterval(callTimer.value)
  }
  const info = currentSessionInfo.value
  if (!info?.startTime) return

  const startTime = info.startTime
  callTimer.value = setInterval(() => {
    const now = new Date()
    const diff = now.getTime() - startTime.getTime()
    const hours = Math.floor(diff / 3600000)
      .toString()
      .padStart(2, '0')
    const minutes = Math.floor((diff % 3600000) / 60000)
      .toString()
      .padStart(2, '0')
    const seconds = Math.floor((diff % 60000) / 1000)
      .toString()
      .padStart(2, '0')
    statusDuration.value = `${hours}:${minutes}:${seconds}`
  }, 1000)
}

const handleDialInput = (digit: string) => {
  phoneNumber.value += digit
}

const handleDelete = () => {
  phoneNumber.value = phoneNumber.value.slice(0, -1)
}

const handlePhoneNumberChange = (value: string) => {
  const oldVal = phoneNumber.value
  const sanitizedInput = value.replace(/[^0-9*#]/g, '')
  if (sanitizedInput === '') {
    phoneNumber.value = ''
    return
  }
  if (sanitizedInput.length > oldVal.length) {
    const addedChar = sanitizedInput.slice(-1)
    handleDialInput(addedChar)
  } else if (sanitizedInput.length < oldVal.length) {
    handleDelete()
  }
}

/**
 * 加载当前坐席所属客服组绑定的可用网关列表
 * 需求：网关下拉框数据改为当前坐席所属客服组绑定的可用网关列表，而非全部网关；
 *       若坐席未绑定组或组未配置网关，则返回空列表（此时外呼将不携带网关信息）
 */
const loadGatewayList = async () => {
  try {
    gatewayList.value = await SysSipAgentApi.getAvailableGatewayList()
    // 网关改为非必填，不再自动选中第一个；若用户需要可选则手动选择
    gatewayId.value = null
  } catch (e) {
    console.error('加载可用网关列表失败:', e)
  }
}

const handleSwitchChange = (val: boolean) => {
  agentStatusValue.value = val ? '1' : '2'
}

// ==================== 会话管理辅助方法 ====================

/**
 * 从sessions Map中移除会话，并处理后续状态切换
 * 需求: 会话结束后清理Map，若为活跃会话则自动切换到下一个
 */
const removeSession = (callId: string | null) => {
  if (!callId) return
  const info = sessions.value.get(callId)
  if (info) {
    cleanupIceController(info.iceController)
    // [MEDIA_DEBUG] 清理媒体诊断资源(定时器/AudioContext)
    cleanupMediaDebug(info)
  }
  sessions.value.delete(callId)

  // 如果删除的是活跃会话，切换到另一个会话
  if (activeCallId.value === callId) {
    if (sessions.value.size > 0) {
      const nextCallId = sessions.value.keys().next().value
      switchActiveSession(nextCallId)
    } else {
      activeCallId.value = null
      agentStatusValue.value = '7'
      clearCallTimer()
    }
  }

  // 如果删除的是来电会话，关闭来电弹窗
  if (incomingCallId.value === callId) {
    incomingCallFlag.value = false
    incomingCallId.value = null
    ringAudio.pause()
  }

  // 根据剩余会话更新坐席状态
  updateAgentStatusBySessions()
}

/**
 * 根据当前所有会话状态更新坐席状态值
 * 需求: 有通话中会话为'5'，有振铃中会话为'6'，无会话不修改(由调用方处理)
 */
const updateAgentStatusBySessions = () => {
  if (sessions.value.size === 0) return
  let hasActive = false
  let hasRinging = false
  sessions.value.forEach((info) => {
    if (info.status === 'active' || info.status === 'held') hasActive = true
    if (info.status === 'ringing') hasRinging = true
  })
  if (hasActive) {
    agentStatusValue.value = '5'
  } else if (hasRinging) {
    agentStatusValue.value = '6'
  }
}

/**
 * 切换当前操作焦点的会话
 * 需求: 点击会话列表项切换焦点，更新音频播放和计时器
 */
const switchActiveSession = (callId: string) => {
  activeCallId.value = callId
  const info = sessions.value.get(callId)
  // 切换音频流到新焦点会话
  if (info?.stream) {
    audioView.srcObject = info.stream
    audioView.play().catch(() => {})
    audioView.volume = 1
  } else {
    audioView.srcObject = null
  }
  // 重新计算当前会话的通话时长
  computeStatusDuration()
}

// ==================== [MEDIA_DEBUG] 媒体诊断工具(仅测试用,验证完成后移除) ====================

/**
 * 启动 WebRTC 媒体统计监控
 * 需求: 通话建立后定时采集 getStats,记录 ICE/DTLS/RTP 收发状态,诊断无声音问题
 * 预期结果: console 输出 [MEDIA_DEBUG] 前缀日志,测试脚本可捕获判断媒体是否真实收发
 * 处理逻辑:
 *   1. 监听 iceconnectionstatechange / connectionstatechange,打印状态变化
 *   2. 每 2 秒调用 RTCPeerConnection.getStats(),提取音频收发统计
 *   3. 同时挂载远端音频 AnalyserNode,检测远端是否有实际音量
 * @param callId 会话ID
 */
const startMediaStatsMonitor = (callId: string) => {
  const info = sessions.value.get(callId)
  if (!info || !info.session?.connection) {
    console.error('[MEDIA_DEBUG] 无法启动媒体监控: session 或 connection 不存在', callId)
    return
  }
  const pc: RTCPeerConnection = info.session.connection
  const tag = `[MEDIA_DEBUG][${callId.substring(0, 8)}]`

  // 1. ICE 连接状态监听
  pc.addEventListener('iceconnectionstatechange', () => {
    console.log(`${tag} ICE状态变更: ${pc.iceConnectionState}`)
  })
  // 2. PeerConnection 连接状态监听(含 DTLS)
  pc.addEventListener('connectionstatechange', () => {
    console.log(`${tag} PC连接状态变更: ${pc.connectionState}`)
  })
  // 2.1 ICE 收集状态监听(诊断候选地址收集是否完成)
  pc.addEventListener('icegatheringstatechange', () => {
    console.log(`${tag} ICE收集状态变更: ${pc.iceGatheringState}`)
  })

  // 3. 远端音频音量检测: 用 AnalyserNode 采样远端 stream 的 RMS
  //    track 事件可能在 confirmed 之后才触发,因此此处只做首次尝试,
  //    定时器内会重试挂载直到成功
  const tryMountAnalyser = () => {
    if (info.remoteAudioAnalyser) return true
    const remoteStream = info.stream
    if (!remoteStream || remoteStream.getAudioTracks().length === 0) return false
    try {
      const AudioCtx = (window as any).AudioContext || (window as any).webkitAudioContext
      const audioCtx: AudioContext = new AudioCtx()
      const source = audioCtx.createMediaStreamSource(remoteStream)
      const analyser = audioCtx.createAnalyser()
      analyser.fftSize = 512
      source.connect(analyser)
      info.remoteAudioContext = audioCtx
      info.remoteAudioAnalyser = analyser
      console.log(`${tag} 远端音频 AnalyserNode 已挂载`)
      return true
    } catch (err) {
      console.error(`${tag} 挂载 AnalyserNode 失败:`, err)
      return false
    }
  }
  if (!tryMountAnalyser()) {
    console.warn(`${tag} 远端 stream 暂无音频轨道,将在定时器中重试挂载`)
  }

  // 4. 每 2 秒采集一次 getStats + 远端音量
  let tick = 0
  const timer = window.setInterval(async () => {
    tick++
    // 重试挂载 analyser(track 事件可能延迟触发)
    tryMountAnalyser()
    try {
      const stats = await pc.getStats()
      let outbound: any = null
      let inbound: any = null
      let remoteInbound: any = null
      let candidatePair: any = null
      let localCandidate: any = null
      let remoteCandidate: any = null
      stats.forEach((report: any) => {
        if (report.type === 'outbound-rtp' && report.kind === 'audio') outbound = report
        else if (report.type === 'inbound-rtp' && report.kind === 'audio') inbound = report
        else if (report.type === 'remote-inbound-rtp' && report.kind === 'audio')
          remoteInbound = report
        else if (report.type === 'candidate-pair' && report.nominated) candidatePair = report
        else if (
          report.type === 'local-candidate' &&
          candidatePair &&
          report.id === candidatePair.localCandidateId
        )
          localCandidate = report
        else if (
          report.type === 'remote-candidate' &&
          candidatePair &&
          report.id === candidatePair.remoteCandidateId
        )
          remoteCandidate = report
      })

      // 远端音量 RMS 计算
      let rms = 0
      if (info.remoteAudioAnalyser) {
        const buf = new Uint8Array(info.remoteAudioAnalyser.fftSize)
        info.remoteAudioAnalyser.getByteTimeDomainData(buf)
        let sum = 0
        for (let i = 0; i < buf.length; i++) {
          const v = (buf[i] - 128) / 128
          sum += v * v
        }
        rms = Math.sqrt(sum / buf.length)
      }

      console.log(
        `${tag}[tick${tick}] ` +
          `ICE=${pc.iceConnectionState} ` +
          `PC=${pc.connectionState} ` +
          `发送包=${outbound?.packetsSent ?? '?'} ` +
          `接收包=${inbound?.packetsReceived ?? '?'} ` +
          `发送字节=${outbound?.bytesSent ?? '?'} ` +
          `接收字节=${inbound?.bytesReceived ?? '?'} ` +
          `远端音量RMS=${rms.toFixed(4)} ` +
          `NOMINATED_PAIR=${candidatePair ? `${candidatePair.state}/${candidatePair.selected ?? '?'}` : 'none'}`
      )
      // 输出选中的候选地址对,诊断 ICE/NAT 穿透问题
      if (localCandidate && remoteCandidate) {
        console.log(
          `${tag}[tick${tick}] 候选对: 本地=${localCandidate.candidateType}:${localCandidate.address}:${localCandidate.port} → 远端=${remoteCandidate.candidateType}:${remoteCandidate.address}:${remoteCandidate.port}`
        )
      }
      if (remoteInbound) {
        console.log(
          `${tag}[tick${tick}] 远端反馈: 丢包率=${remoteInbound.packetsLost ?? '?'}, 抖动=${remoteInbound.jitter ?? '?'}`
        )
      }
    } catch (err) {
      console.error(`${tag} getStats 失败:`, err)
    }
  }, 2000)
  info.statsTimer = timer
  console.log(`${tag} 媒体统计监控已启动`)
}

/**
 * 清理指定会话的媒体诊断资源
 * 需求: 通话结束/移除会话时,停止定时器、关闭 AudioContext,避免内存泄漏
 * @param info 会话信息
 */
const cleanupMediaDebug = (info: SessionInfo | undefined) => {
  if (!info) return
  if (info.statsTimer) {
    clearInterval(info.statsTimer)
    info.statsTimer = null
  }
  if (info.testToneTimer) {
    clearTimeout(info.testToneTimer)
    info.testToneTimer = null
  }
  if (info.remoteAudioContext) {
    try {
      info.remoteAudioContext.close()
    } catch (e) {
      /* 忽略已关闭 */
    }
    info.remoteAudioContext = null
    info.remoteAudioAnalyser = null
  }
}

/**
 * 向对端注入测试提示音(主被叫均可调用,用不同频率区分方向)
 * 需求: 通话建立后用 OscillatorNode 生成提示音注入发送流,验证 RTP 媒体链路是否真实双向流通。
 *       主叫用 440Hz、被叫用 880Hz,错开播放时间避免互相干扰。
 * 预期结果: 注入期间对端 getStats inbound-rtp bytesReceived 明显增长,证明下行链路正常
 * 处理逻辑:
 *   1. 通过 RTCRtpSender.replaceTrack 临时替换音频源为 oscillator
 *   2. 2 秒后恢复原 track
 *   3. 主叫(confirmed 后 1 秒)和被叫(confirmed 后 4 秒)分别触发,用频率区分
 * @param callId     会话ID
 * @param frequency  提示音频率(Hz),主叫 440 / 被叫 880
 */
const playTestToneToRemote = (callId: string, frequency: number = 440) => {
  const info = sessions.value.get(callId)
  if (!info || !info.session?.connection) return
  const pc: RTCPeerConnection = info.session.connection
  const tag = `[MEDIA_DEBUG][${callId.substring(0, 8)}]`

  try {
    const senders = pc.getSenders()
    const audioSender = senders.find((s) => s.track?.kind === 'audio')
    if (!audioSender) {
      console.warn(`${tag} 未找到音频 sender,无法注入测试音`)
      return
    }
    const originalTrack = audioSender.track

    const AudioCtx = (window as any).AudioContext || (window as any).webkitAudioContext
    const audioCtx: AudioContext = new AudioCtx()
    const dest = audioCtx.createMediaStreamDestination()
    const osc = audioCtx.createOscillator()
    const gain = audioCtx.createGain()
    osc.frequency.value = frequency
    osc.type = 'sine'
    gain.gain.value = 0.3
    osc.connect(gain)
    gain.connect(dest)
    osc.start()

    const testTrack = dest.stream.getAudioTracks()[0]
    audioSender.replaceTrack(testTrack)
    console.log(`${tag} >>> 已向对端注入 ${frequency}Hz 测试提示音(2秒)`)

    info.testToneTimer = window.setTimeout(() => {
      audioSender.replaceTrack(originalTrack)
      osc.stop()
      audioCtx.close()
      console.log(`${tag} <<< ${frequency}Hz 测试提示音结束,已恢复原麦克风轨道`)
    }, 2000)
  } catch (err) {
    console.error(`${tag} 注入测试音失败:`, err)
  }
}

/**
 * 为会话注册通用的生命周期事件处理器
 * 需求: 统一处理confirmed/failed/ended/hold/unhold/muted/unmuted事件，更新SessionInfo
 */
const registerSessionEvents = (callId: string, direction: 'incoming' | 'outgoing') => {
  const info = sessions.value.get(callId)
  if (!info) return
  const session = info.session

  // 通话确认: 更新状态为active，记录开始时间
  session.on('confirmed', (e: any) => {
    console.log(`${direction === 'incoming' ? '呼入' : '拨打'}会话确认: 通话中`, e)
    const currentInfo = sessions.value.get(callId)
    if (currentInfo) {
      currentInfo.status = 'active'
      currentInfo.startTime = new Date()
    }
    agentStatusValue.value = '5'
    cleanupIceController(info.iceController)
    // [MEDIA_DEBUG] 通话建立后启动媒体统计监控
    startMediaStatsMonitor(callId)
    // [MEDIA_DEBUG] 把 peerConnection 暴露到 window,供测试脚本直接 evaluate 调用 getStats
    try {
      const debugPc = info.session?.connection as RTCPeerConnection
      ;(window as any).__MEDIA_DEBUG_PC__ = debugPc ?? null
      ;(window as any).__MEDIA_DEBUG_STREAM__ = currentInfo?.stream ?? null
      ;(window as any).__MEDIA_DEBUG_CALLID__ = callId
      console.log(
        `[MEDIA_DEBUG][${callId.substring(0, 8)}] peerConnection 已暴露到 window.__MEDIA_DEBUG_PC__`
      )
      // 输出 SDP 摘要,诊断 codec/DTLS/ICE 协商问题
      if (debugPc) {
        const localSdp = debugPc.localDescription?.sdp ?? 'null'
        const remoteSdp = debugPc.remoteDescription?.sdp ?? 'null'
        // 提取 SDP 关键行(m=audio/a=rtpmap/a=fingerprint/a=setup/a=candidate/a=ice-ufrag)
        const extractSdpKeyLines = (sdp: string) =>
          sdp
            .split('\r\n')
            .filter(
              (l) =>
                l.startsWith('m=audio') ||
                l.startsWith('a=rtpmap') ||
                l.startsWith('a=fingerprint') ||
                l.startsWith('a=setup') ||
                l.startsWith('a=candidate') ||
                l.startsWith('a=ice-ufrag') ||
                l.startsWith('a=ice-pwd') ||
                l.startsWith('c=IN IP4') ||
                l.startsWith('a=rtcp-mux') ||
                l.startsWith('a=ssrc')
            )
            .join(' | ')
        console.log(`[MEDIA_DEBUG][${callId.substring(0, 8)}] direction=${direction}`)
        console.log(
          `[MEDIA_DEBUG][${callId.substring(0, 8)}] ICE状态: ${debugPc.iceConnectionState}, PC状态: ${debugPc.connectionState}`
        )
        console.log(
          `[MEDIA_DEBUG][${callId.substring(0, 8)}] 本地SDP关键行: ${extractSdpKeyLines(localSdp)}`
        )
        console.log(
          `[MEDIA_DEBUG][${callId.substring(0, 8)}] 远端SDP关键行: ${extractSdpKeyLines(remoteSdp)}`
        )
      }
    } catch (e) {
      console.error('[MEDIA_DEBUG] 暴露 PC 到 window 失败:', e)
    }
    // [MEDIA_DEBUG] 双向测试提示音: 主叫440Hz(1秒后), 被叫880Hz(4秒后), 错开避免干扰
    //   主叫播放440Hz → 被叫应收到 → 验证下行(主叫→被叫)
    //   被叫播放880Hz → 主叫应收到 → 验证上行(被叫→主叫)
    if (direction === 'outgoing') {
      setTimeout(() => playTestToneToRemote(callId, 440), 1000)
    } else {
      setTimeout(() => playTestToneToRemote(callId, 880), 4000)
    }
    // 如果是当前焦点会话，启动计时器
    if (activeCallId.value === callId) {
      computeStatusDuration()
    }
  })

  // 会话失败: 清理会话，外呼时显示错误提示
  session.on('failed', (e: any) => {
    console.error(`${direction === 'incoming' ? '呼入' : '拨打'}会话失败:`, e)
    if (direction === 'outgoing') {
      message.error(`呼叫失败: ${e.cause || '未知原因'}`)
    }
    removeSession(callId)
  })

  // 会话被拒绝: 仅外呼场景
  session.on('rejected', (e: any) => {
    console.error('拨打呼叫被拒绝:', e)
    message.error(`呼叫被拒绝: ${e.cause || '未知原因'}`)
    removeSession(callId)
  })

  // 会话结束: 清理会话
  session.on('ended', (e: any) => {
    const currentInfo = sessions.value.get(callId)
    const startTime = currentInfo?.startTime?.getTime()
    const durationSec = startTime ? ((Date.now() - startTime) / 1000).toFixed(1) : '?'
    // [MEDIA_DEBUG] 记录通话结束信息,时长<10秒且非主动挂断时标记为异常自动挂断
    const tag = `[MEDIA_DEBUG][${callId.substring(0, 8)}]`
    console.warn(
      `${tag} 通话结束 direction=${direction} 时长=${durationSec}s cause=${(e as any)?.cause || 'normal'}`
    )
    if (currentInfo?.startTime) {
      const secs = (Date.now() - currentInfo.startTime.getTime()) / 1000
      if (secs < 10) {
        console.warn(
          `${tag} ⚠ 通话时长仅${secs.toFixed(1)}秒,疑似媒体协商失败导致自动挂断(RTP超时/DTLS握手失败/ICE未连接)`
        )
      }
    }
    removeSession(callId)
  })

  // 保持/恢复事件: 同步SessionInfo中的isHeld状态
  session.on('hold', () => {
    const currentInfo = sessions.value.get(callId)
    if (currentInfo) {
      currentInfo.isHeld = true
      currentInfo.status = 'held'
    }
    updateAgentStatusBySessions()
  })

  session.on('unhold', () => {
    const currentInfo = sessions.value.get(callId)
    if (currentInfo) {
      currentInfo.isHeld = false
      currentInfo.status = 'active'
    }
    updateAgentStatusBySessions()
  })

  // 静音/取消静音事件: 同步SessionInfo中的isMuted状态
  session.on('muted', () => {
    const currentInfo = sessions.value.get(callId)
    if (currentInfo) {
      currentInfo.isMuted = true
    }
  })

  session.on('unmuted', () => {
    const currentInfo = sessions.value.get(callId)
    if (currentInfo) {
      currentInfo.isMuted = false
    }
  })
}

// ==================== SIP客户端初始化 ====================

const initSipClient = async () => {
  console.log('初始化SIP客户端')
  // 先获取坐席信息,确保 agentInfo 在 SIP 初始化前就绑定完成
  // 需求: agentInfo 必须在 getPublicIPAndPort 之前赋值,否则 STUN 超时会导致 agentInfo 为 null,
  //       后续切换就绪状态时 handleAgentStatusChange 访问 agentInfo.value.id 会抛出 NPE
  agentInfo.value = await SysSipAgentApi.getSysSipAgentByUserId()
  if (!agentInfo.value) {
    message.error('坐席信息不存在')
    return
  }
  // 获取公网地址(构建 contact_uri); 禁用 ICE 配置时跳过 STUN 查询, 使用本地地址兜底
  // 背景: contact_uri 仅供 JsSIP 本地栈使用, sipproxy 会将其改写为代理可达地址
  //       (rewriteWsAgentContactForFs), 故 STUN 不可用/禁用时以 127.0.0.1 兜底不影响信令
  let publicIP = '127.0.0.1'
  let publicPort = '0'
  if (USE_ICE_CONFIG) {
    const result = await getPublicIPAndPort()
    publicIP = result.ip
    publicPort = result.port
    console.log('发现公网地址：', publicIP, publicPort)
  } else {
    console.log(
      '[SoftPhone][USE_ICE_CONFIG=false] 跳过 STUN 公网探测, contact_uri 使用本地地址兜底'
    )
  }
  console.log('开始启动jssip')
  // 动态获取最新的 refreshToken 构建 WebSocket URL，避免 token 在组件初始化时固化导致过期
  const socket = new JsSIP.WebSocketInterface(getSipWsUrl())
  JsSIP.debug.enable('JsSIP:*')
  let uri = `sip:${agentInfo.value.name}@${agentInfo.value.domain}`

  const cleanedIP = publicIP.replace(/^\[|\]$/g, '')
  const isIPv6 = cleanedIP.includes(':')
  const contactIP = isIPv6 ? `[${cleanedIP}]` : cleanedIP
  let configuration = {
    sockets: [socket],
    uri: uri,
    contact_uri: `sip:${agentInfo.value.name}@${contactIP}:${publicPort};transport=ws`,
    password: agentInfo.value.password,
    register: true,
    register_expires: 1800,
    connection_recovery_max_interval: 60,
    connection_recovery_min_interval: 5,
    no_answer_timeout: 60,
    pcConfig: buildPcConfig(),
    mediaConstraints: {
      audio: true,
      video: false
    },
    rtcOfferConstraints: {
      offerToReceiveAudio: true,
      offerToReceiveVideo: false
    },
    sessionTimersExpires: 180
  }
  ua = new JsSIP.UA(configuration)
  registerSipEvents()
  ua.start()
}

const unregisterSipClient = () => {
  if (!ua) {
    console.warn('SIP客户端未初始化')
    return
  }
  try {
    if (ua.isConnected()) {
      ua.stop()
    }
  } catch (error) {
    console.error('SIP登出失败:', error)
  }
  ua = undefined
}

const startKeepAlive = () => {
  if (keepAliveTimer) {
    clearInterval(keepAliveTimer)
  }

  keepAliveTimer = setInterval(() => {
    if (ua && ua.isRegistered()) {
      const target = (ua as any).configuration.uri
      ;(ua as any).sendOptions(target, null, {
        contentType: '',
        eventHandlers: {
          onSuccessResponse: (response: any) => {
            console.log('[SIP心跳] OPTIONS 保活成功')
          },
          onErrorResponse: (response: any) => {
            console.error('[SIP心跳] OPTIONS 保活失败', response)
            message.warning('SIP心跳保活失败，重新注册，请检查您的网络')
          }
        }
      })
    }
  }, KEEP_ALIVE_INTERVAL)
}

const stopKeepAlive = () => {
  if (keepAliveTimer) {
    clearInterval(keepAliveTimer)
    keepAliveTimer = null
    console.log('[SIP心跳] 已停止保活')
  }
}

/**
 * 注册SIP UA事件
 * 需求: 处理注册/取消注册/新会话事件，newRTCSession中将新会话保存到sessions Map
 */
const registerSipEvents = () => {
  ua.on('registered', () => {
    // REGISTER 成功后才设置在线状态,确保 UI 状态与实际注册状态同步
    // 设计意图: toggleLogin 中不再提前设置 loginValue='2',避免 UI 显示在线但实际未注册
    loginValue.value = '2'
    computeStatusDuration()
    console.log('SIP注册成功')
    agentStatusValue.value = '2'
    startKeepAlive()
    loadGatewayList()
  })

  ua.on('unregistered', () => {
    clearCallTimer()
    stopKeepAlive()
    console.log('SIP取消注册成功')
  })

  ua.on('registrationFailed', (response: any) => {
    // REGISTER 失败时恢复离线状态,确保 UI 反映真实注册状态
    loginValue.value = '1'
    isSignInDisabled.value = true
    console.error('SIP注册失败:', JSON.stringify(response))

    // 唯一登录检测：403 且原因短语为 "Duplicate Login" 表示同一坐席已在其他地方登录
    const reasonPhrase = response?.response?.reason_phrase || ''
    if (response?.response?.status_code === 403 && reasonPhrase === 'Duplicate Login') {
      // 弹出强制登录确认对话框
      ElMessageBox.confirm('该坐席已在其他地方已登录或未下线，是否强制登录？', '提示', {
        confirmButtonText: '是（强制登录）',
        cancelButtonText: '否',
        type: 'warning',
        distinguishCancelAndClose: true
      })
        .then(async () => {
          // 用户选择"是"：调用后端接口清理旧会话，然后重新发起 REGISTER
          console.log('[SoftPhone] 用户确认强制登录，清理旧会话后重试')
          try {
            await SysSipAgentApi.forceLogin({
              extension: agentInfo.value?.name || '',
              domain: agentInfo.value?.domain || ''
            })
            // 延迟 500ms 后重新发起 SIP 注册
            setTimeout(async () => {
              try {
                await initSipClient()
              } catch (e) {
                console.error('[SoftPhone] 强制登录重试 SIP 注册失败:', e)
                message.error('SIP 签入失败,请检查网络或联系管理员')
              }
            }, 500)
          } catch (e) {
            console.error('[SoftPhone] 强制登录清理旧会话失败:', e)
            message.error('强制登录失败，请稍后重试')
          }
        })
        .catch(() => {
          // 用户选择"否"或关闭对话框：不登录
          console.log('[SoftPhone] 用户取消强制登录')
        })
      return
    }

    message.error('SIP 注册失败,请检查坐席配置或网络后重试')
  })

  ua.on('newRTCSession', (data: any) => {
    // [DIAG] 无条件日志: 确认 newRTCSession 事件是否触发到 Vue (定位来电弹窗未显示)
    console.log('[DIAG] newRTCSession 触发, originator=', data.originator)
    const session = data.session
    const callId = session.id

    // 创建ICE收集控制器
    const iceController = createIceGatheringController()
    session.on('icecandidate', (candidateData: any) => {
      handleIceCandidate(
        candidateData,
        iceController,
        data.originator === 'local' ? '外呼' : '呼入'
      )
    })

    // 获取对方号码
    const remoteNumber = session.remote_identity?.uri?.user || ''

    // 将新会话保存到sessions Map，而非覆盖
    // 使用markRaw包裹JsSIP RTCSession对象,避免Vue响应式系统对其创建Proxy
    // 原因: JsSIP内部ReferSubscriber.sendRefer访问this._session._ua._configuration.uri时,
    //       若session被Vue Proxy代理,会因uri为只读非可配置属性触发TypeError
    sessions.value.set(callId, {
      session: markRaw(session),
      number: remoteNumber,
      status: 'ringing',
      isMuted: false,
      isHeld: false,
      direction: data.originator === 'local' ? 'outgoing' : 'incoming',
      startTime: null,
      stream: null,
      iceController
    })

    // 设置为活跃会话(如果没有活跃会话，或这是外呼会话)
    if (!activeCallId.value || data.originator === 'local') {
      activeCallId.value = callId
    }

    // 注册通用会话事件
    registerSessionEvents(callId, data.originator === 'local' ? 'outgoing' : 'incoming')

    if (data.originator === 'local') {
      // 外呼: 设置远端音频轨道
      session.connection.addEventListener('track', (event: any) => {
        const info = sessions.value.get(callId)
        if (info) {
          info.stream = event.streams[0]
        }
        // [MEDIA_DEBUG] track 事件触发时 PC 一定存在,在此暴露确保被叫也能采集
        try {
          ;(window as any).__MEDIA_DEBUG_PC__ = session.connection
          ;(window as any).__MEDIA_DEBUG_STREAM__ = event.streams[0]
          console.log(`[MEDIA_DEBUG][${callId.substring(0, 8)}] track事件: PC已暴露到window`)
        } catch (e) {
          /* 忽略 */
        }
        // 如果是当前焦点会话，立即播放
        if (activeCallId.value === callId) {
          audioView.srcObject = event.streams[0]
          audioView.play()
          audioView.volume = 1
        }
      })

      // 外呼特有事件
      session.on('connecting', (e: any) => {
        console.log('拨打会话连接中...:', e)
        agentStatusValue.value = '6'
      })

      session.on('progress', (e: any) => {
        console.log('拨打会话进度更新: 振铃中:', e)
        agentStatusValue.value = '6'
      })
    }

    if (data.originator === 'remote') {
      // 来电: 显示来电弹窗
      console.log('收到来电，显示对话框')
      incomingCallFlag.value = true
      incomingCallId.value = callId
      incomingCallNumber.value = remoteNumber

      // 业务示例: 来电时在系统标签页打开「业务示例」页面
      // 以 callId(session.id) 作为路由 fullPath 锚点，同一通话重复进入会聚焦已有标签页；
      // 不同通话的 callId 不同，故同名「业务示例」页面可开多个、互不干扰，关闭时按 fullPath 精确关闭。
      router.push({
        path: '/cc/biz-example',
        query: { callId, number: remoteNumber, direction: 'incoming' }
      })

      session.on('connecting', (e: any) => {
        console.log('呼入会话连接中...', e)
      })

      session.on('progress', (e: any) => {
        console.log('呼入会话进度更新: 振铃中', e)
        agentStatusValue.value = '6'
        ringAudio.loop = true
        ringAudio.play().catch((err) => {
          console.error('播放振铃录音失败:', err)
        })
      })

      session.on('sdp', (e: any) => {
        console.log('呼入通话sdp:', e)
      })
    }
  })
}

// ==================== 外呼 ====================

/**
 * 发起呼叫
 * 需求：
 * - 外呼(callType=0)：显示网关下拉框（非必填），选择网关时通过 X-Gateway-Id 头携带网关ID
 * - 内部呼叫(callType=1)：隐藏网关下拉框，不携带网关ID，直接拨打内线
 */
const makeCall = () => {
  if (!phoneNumber.value) {
    message.warning('请输入要拨打的号码')
    return
  }

  if (!ua || !ua.isRegistered()) {
    message.warning('请先登录SIP账号')
    return
  }

  const iceController = createIceGatheringController()

  const eventHandlers = {
    icecandidate: (data: any) => {
      handleIceCandidate(data, iceController, '外呼')
    }
  }
  // 内部呼叫不携带网关头；外呼时若选择了网关则携带 X-Gateway-Id 头，未选则不携带（不强制必填）
  const extraHeaders: string[] = []
  if (callType.value === 0 && gatewayId.value) {
    extraHeaders.push(`X-Gateway-Id: ${gatewayId.value}`)
  }
  const options = {
    extraHeaders,
    sessionTimersExpires: 180,
    pcConfig: buildPcConfig(),
    mediaConstraints: {
      audio: true,
      video: false
    },
    eventHandlers
  }
  ua.call(`${phoneNumber.value}`, options)
}

// ==================== 接听/挂断/拒绝 ====================

/**
 * 接听来电
 * 需求: 接听来电弹窗对应的会话，设置远端音频并切换为活跃会话
 */
const handleAnswer = () => {
  const callId = incomingCallId.value
  if (callId) {
    const info = sessions.value.get(callId)
    if (info?.session) {
      info.session.answer({
        sessionTimersExpires: 180,
        pcConfig: buildPcConfig(),
        mediaConstraints: {
          audio: true,
          video: false
        }
      })
      // 接听后切换为活跃会话
      activeCallId.value = callId
      agentStatusValue.value = '5'
      ringAudio.pause()

      // 设置远端音频轨道
      info.session.connection.addEventListener('track', (event: any) => {
        info.stream = event.streams[0]
        // [MEDIA_DEBUG] 被叫接听后 track 事件触发,暴露 PC 到 window 供测试脚本采集
        try {
          ;(window as any).__MEDIA_DEBUG_PC__ = info.session.connection
          ;(window as any).__MEDIA_DEBUG_STREAM__ = event.streams[0]
          console.log(`[MEDIA_DEBUG][${callId.substring(0, 8)}] 被叫track事件: PC已暴露到window`)
        } catch (e) {
          /* 忽略 */
        }
        if (activeCallId.value === callId) {
          audioView.srcObject = event.streams[0]
          audioView.play()
          audioView.volume = 1
        }
      })

      computeStatusDuration()
    }
  } else {
    ElMessage.warning('没有正在进行的通话')
  }
  incomingCallFlag.value = false
  incomingCallId.value = null
}

/**
 * 挂断当前焦点会话
 * 需求: 终止活跃会话，若有其他会话则自动切换，否则进入话后状态
 */
const handleHangup = () => {
  const callId = activeCallId.value
  if (!callId) {
    ElMessage.warning('没有正在进行的通话')
    return
  }

  const info = sessions.value.get(callId)
  if (info?.session) {
    ringAudio.pause()
    info.session.terminate()
    // removeSession会处理Map清理和状态切换
    removeSession(callId)
    ElMessage.success('通话已挂断')
  } else {
    ElMessage.warning('没有正在进行的通话')
  }
}

/**
 * 拒绝来电(来电弹窗的挂断按钮)
 * 需求: 仅终止来电会话，不影响其他活跃会话
 */
const handleRejectIncoming = () => {
  const callId = incomingCallId.value
  if (callId) {
    const info = sessions.value.get(callId)
    if (info?.session) {
      info.session.terminate()
    }
    ringAudio.pause()
    removeSession(callId)
  }
  incomingCallFlag.value = false
  incomingCallId.value = null
}

// ==================== 保持/静音/DTMF ====================

/**
 * 切换当前焦点会话的保持/恢复状态
 * 需求: 调用JsSIP toggleHold API发送re-INVITE切换sendonly/sendrecv,
 *       状态通过hold/unhold事件同步到SessionInfo
 * 异常处理: 捕获JsSIP内部异常(如session状态非CONFIRMED),输出到控制台便于排查
 * JsSIP API说明:
 *   - isOnHold() 返回对象 {local: boolean, remote: boolean},而非布尔值
 *   - local=true表示本端已发起hold,remote=true表示对端已发起hold
 *   - 判断"是否已保持"需检查 local || remote
 */
const toggleHold = () => {
  const session = currentSession.value
  if (!session) {
    console.warn('[toggleHold] 当前无焦点会话,无法操作保持')
    return
  }
  try {
    const holdState = session.isOnHold ? session.isOnHold() : { local: false, remote: false }
    const isHeldNow = holdState.local || holdState.remote
    console.log(
      '[toggleHold] 开始切换保持状态, isOnHold:',
      holdState,
      'isHeldNow:',
      isHeldNow,
      'callId:',
      activeCallId.value
    )
    const cb = (err: any, response?: any) => {
      if (err) {
        const statusCode = response?.status_code || 0
        const cause = response?.reason_phrase || (err as Error)?.message || '未知'
        console.warn(
          `[toggleHold] ${isHeldNow ? '恢复' : '保持'}协商失败, status=${statusCode}, cause=${cause}, 但会话未终止`
        )
        if (isHeldNow) {
          const info = sessions.value.get(activeCallId.value)
          if (info) {
            info.isHeld = true
          }
        } else {
          const info = sessions.value.get(activeCallId.value)
          if (info) {
            info.isHeld = false
          }
        }
      } else {
        console.log(`[toggleHold] ${isHeldNow ? '恢复' : '保持'}协商成功`)
      }
    }
    if (isHeldNow) {
      console.log('[toggleHold] 当前已保持,调用unhold()发送re-INVITE恢复')
      session.unhold({ eventHandlers: {} }, cb)
    } else {
      console.log('[toggleHold] 当前未保持,调用hold()发送re-INVITE保持')
      session.hold({ eventHandlers: {} }, cb)
    }
    console.log('[toggleHold] 保持状态切换调用完成')
  } catch (e) {
    console.error('[toggleHold] 切换保持状态异常:', e)
  }
}

/**
 * 切换当前焦点会话的静音/取消静音
 * 需求: 调用JsSIP mute/unmute API控制本地音频流，
 *       状态通过muted/unmuted事件同步到SessionInfo
 */
const toggleMute = () => {
  const session = currentSession.value
  if (session) {
    if (isMuted.value) {
      session.unmute({ audio: true })
    } else {
      session.mute({ audio: true })
    }
    // isMuted状态将通过muted/unmuted事件自动同步
  }
}

/**
 * 通话中发送DTMF信号
 * 需求: 在通话中对当前焦点会话发送DTMF按键音
 * @param digit - DTMF按键值(0-9, *, #)
 */
const sendDTMF = (digit: string) => {
  const session = currentSession.value
  if (session) {
    session.sendDTMF(digit)
  }
}

/**
 * 发起咨询转接/盲转
 * 需求: 通话中通过JsSIP refer()发送REFER请求,后端WsReferRequestHandler处理转接逻辑
 * 处理逻辑:
 *   1. 校验转接目标号码非空
 *   2. 构造自定义头域: X-Transfer-Type(attended/blind), X-Gateway-Id(可选)
 *   3. 调用session.refer()发送REFER请求
 *   4. 关闭转接弹窗
 * 业务说明:
 *   - 咨询转接(attended): hold住A-B通话 → originate呼叫C → A与C咨询 → A挂断确认 → B与C桥接
 *   - 盲转(blind): originate呼叫C → C应答后kill A → bridge B和C
 */
const handleTransfer = () => {
  const session = currentSession.value
  const target = transferTarget.value.trim()
  console.log(
    '[handleTransfer] 开始转接, session存在:',
    !!session,
    'target:',
    target,
    'transferType:',
    transferType.value
  )
  // 将调试信息写入window对象,便于Playwright通过page.evaluate读取(在if检查前设置,确保即使session为空也能捕获)
  ;(window as any)._transferDebug = {
    hasSession: !!session,
    sessionStatus: session ? (session as any)._status : null,
    sessionStatusPublic: session ? session.status : null,
    hasRefer: session ? typeof session.refer === 'function' : false,
    target,
    transferType: transferType.value,
    referResult: null,
    referResultType: null,
    error: null,
    step: 'init'
  }
  if (!session || !target) {
    console.warn('[handleTransfer] session或target为空, 退出')
    ;(window as any)._transferDebug.error = 'session或target为空'
    ;(window as any)._transferDebug.step = 'empty_session_or_target'
    return
  }
  // 构造REFER自定义头域
  const extraHeaders: string[] = [`X-Transfer-Type: ${transferType.value}`]
  if (transferGatewayId.value) {
    extraHeaders.push(`X-Gateway-Id: ${transferGatewayId.value}`)
  }
  ;(window as any)._transferDebug.step = 'before_refer'
  ;(window as any)._transferDebug.extraHeaders = extraHeaders
  console.log(
    '[handleTransfer] extraHeaders:',
    extraHeaders,
    'session._status:',
    (session as any)._status,
    'session存在refer方法:',
    typeof session.refer === 'function'
  )
  try {
    ;(window as any)._transferDebug.step = 'in_refer'
    // 调用JsSIP refer()发送REFER请求
    // 注意:JsSIP refer()在session状态非STATUS_CONFIRMED(9)/STATUS_WAITING_FOR_ACK(6)时返回false
    const referResult = session.refer(target, { extraHeaders })
    console.log('[handleTransfer] refer()返回值:', referResult)
    ;(window as any)._transferDebug.referResult = !!referResult
    ;(window as any)._transferDebug.referResultType = typeof referResult
    ;(window as any)._transferDebug.step = 'after_refer'
    if (!referResult) {
      console.error(
        '[handleTransfer] refer()返回false,REFER未发送! session._status:',
        (session as any)._status
      )
      ;(window as any)._transferDebug.step = 'refer_returned_false'
      message.error(
        '转接失败: 通话状态不允许转接(session._status=' + (session as any)._status + ')'
      )
      return
    }
    console.log('[handleTransfer] refer()调用成功(已发送REFER请求)')
    message.success(`已发起${transferType.value === 'attended' ? '咨询转接' : '盲转'}到 ${target}`)
  } catch (e) {
    console.error('[handleTransfer] 发送REFER失败:', e)
    ;(window as any)._transferDebug.error = e instanceof Error ? e.message : String(e)
    ;(window as any)._transferDebug.errorStack = e instanceof Error ? e.stack : null
    ;(window as any)._transferDebug.step = 'caught_exception'
    message.error(`转接失败: ${e instanceof Error ? e.message : String(e)}`)
  } finally {
    // 无论成功或失败都关闭弹窗,避免弹窗卡住无法操作
    showTransferPopup.value = false
    transferTarget.value = ''
    transferGatewayId.value = null
    transferType.value = 'attended'
  }
}

// ==================== 生命周期 ====================

onBeforeUnmount(() => {
  // 移除 WebSocket 事件回调，避免组件卸载后仍被触发导致内存泄漏
  offAgentStatusChanged(handleAgentStatusChangedEvent)
  offReconnected(handleWsReconnected)
  offConnectionStateChange(handleWsConnectionStateChange)
  // 清理滞留会话兜底定时器，避免组件卸载后触发
  if (staleSessionCleanupTimer) {
    clearTimeout(staleSessionCleanupTimer)
    staleSessionCleanupTimer = null
  }
  stopKeepAlive()
  unregisterSipClient()
})

interface PublicIPInfo {
  ip: string
  port: string
}
/**
 * 通过 STUN 获取公网 IP 和端口（用于 WebRTC 媒体协商）
 *
 * 需求背景: JsSIP 签入时需获取公网 IP 构建 contact_uri,供 WebRTC ICE 候选交换。
 * 预期结果: 返回 srflx/relay 类型的公网 IP+端口;STUN 不可达时返回本地兜底地址。
 * 处理逻辑:
 *   1. 创建 RTCPeerConnection,监听 onicecandidate 事件
 *   2. 收到 srflx/relay 类型候选时 resolve
 *   3. ICE 收集完成(null candidate)仍无公网候选时 resolve 本地兜底地址
 *   4. 10 秒超时兜底: STUN 服务器不可达时 Promise 不会永远挂起,返回本地地址继续 SIP 注册流程
 * 异常场景:
 *   - STUN 服务器宕机/网络隔离: 10 秒超时后兜底返回 127.0.0.1,SIP 信令走 WebSocket 不受影响
 *   - createOffer/setLocalDescription 失败: reject(由调用方 try-catch 处理)
 * 设计约束:
 *   - 兜底返回本地地址而非 reject,因为 SIP REGISTER/INVITE 信令走 WebSocket 不依赖公网 IP;
 *     媒体协商失败由 TURN 服务器兜底或本地局域网直连,不应阻塞签入流程
 */
async function getPublicIPAndPort(stunServers = STUN_SERVERS): Promise<PublicIPInfo> {
  return new Promise<PublicIPInfo>((resolve, reject) => {
    // STUN 超时兜底: 10 秒后返回本地地址,避免 STUN 不可达时 Promise 永远挂起阻塞签入流程
    const STUN_TIMEOUT_MS = 10000
    const timeout = setTimeout(() => {
      pc.close()
      console.warn('[getPublicIPAndPort][STUN 超时,使用本地地址兜底]')
      resolve({ ip: '127.0.0.1', port: '0' })
    }, STUN_TIMEOUT_MS)

    const pc = new RTCPeerConnection({
      iceServers: stunServers.urls.map((url) => ({ urls: url }))
    })

    pc.createDataChannel('dummy')

    pc.onicecandidate = (evt) => {
      if (!evt.candidate) {
        clearTimeout(timeout)
        pc.close()
        // ICE 收集完成仍未获取到 srflx/relay 候选,兜底返回本地地址
        console.warn('[getPublicIPAndPort][ICE 收集完成无公网候选,使用本地地址兜底]')
        resolve({ ip: '127.0.0.1', port: '0' })
        return
      }
      const parts = evt.candidate.candidate.split(' ') as Array<string>
      const [, , , , ip, port, , type] = parts
      if ((type === 'srflx' || type === 'relay') && ip && port) {
        clearTimeout(timeout)
        pc.close()
        resolve({ ip, port })
      }
    }

    pc.createOffer()
      .then((desc) => pc.setLocalDescription(desc))
      .catch((err) => {
        clearTimeout(timeout)
        pc.close()
        reject(err)
      })
  })
}
</script>

<style lang="scss" scoped>
.soft-phone-bar {
  margin-right: 12px;
  display: inline-flex;
  align-items: center;
  border: 1px solid var(--el-border-color-lighter);
  overflow: visible;
  padding: 2px 0px;
  border-radius: 12px;
}

.bar-section {
  display: flex;
  align-items: center;
  height: 100%;
  flex-shrink: 0;
}

.bar-auth {
  padding: 0 8px;
}

.bar-status {
  padding: 0 10px;
  gap: 8px;
}

.bar-dial {
  padding: 0 8px;
}

.bar-divider {
  width: 1px;
  height: 24px;
  background: var(--el-border-color-lighter);
  flex-shrink: 0;
}

.switch-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
}

.switch-label {
  font-size: 12px;
  font-weight: 500;
  white-space: nowrap;

  &--ready {
    color: var(--el-color-success);
  }

  &--busy {
    color: var(--el-color-warning);
  }
}

.offline-tag {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 0 10px;
  height: 24px;
  border-radius: 20px;
  font-size: 12px;
  font-weight: 500;
  background: var(--el-color-info-light-9);
  color: var(--el-color-info);
  border: 1px solid var(--el-color-info-light-8);
}

.offline-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--el-color-info);
}

.popover {
  position: absolute;
  top: calc(100% + 12px);
  left: 50%;
  transform: translateX(-50%);
  background: var(--el-bg-color);
  border-radius: 8px;
  box-shadow:
    0 4px 16px rgba(0, 0, 0, 0.1),
    0 0 1px rgba(0, 0, 0, 0.06);
  border: 1px solid var(--el-border-color-lighter);
  z-index: 2000;
  overflow: visible;
  width: 260px;

  &::before {
    content: '';
    position: absolute;
    top: -6px;
    left: 50%;
    transform: translateX(-50%) rotate(45deg);
    width: 12px;
    height: 12px;
    background: var(--el-bg-color);
    border-left: 1px solid var(--el-border-color-lighter);
    border-top: 1px solid var(--el-border-color-lighter);
  }
}

.popover-header {
  padding: 10px 16px;
  border-bottom: 1px solid var(--el-border-color-lighter);
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.popover-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.popover-close {
  width: 20px;
  height: 20px;
  border-radius: 4px;
  border: none;
  background: transparent;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  transition: all 0.15s;

  &:hover {
    background: var(--el-color-danger-light-9);
    color: var(--el-color-danger);
  }
}

.popover-body {
  padding: 14px 16px;
}

.dial-input {
  width: 100%;
  height: 34px;
  border: 1px solid var(--el-border-color);
  border-radius: 4px;
  padding: 0 10px;
  font-size: 15px;
  font-family: 'Menlo', 'Monaco', 'Consolas', monospace;
  letter-spacing: 2px;
  text-align: center;
  color: var(--el-text-color-primary);
  background: var(--el-bg-color);
  outline: none;
  margin-bottom: 10px;

  &:focus {
    border-color: var(--el-color-primary);
    box-shadow: 0 0 0 2px rgba(64, 158, 255, 0.12);
  }

  &::placeholder {
    color: var(--el-color-color-placeholder);
    font-family: inherit;
    letter-spacing: 0;
    font-size: 12px;
  }
}

.dialpad-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 4px;

  &--incall {
    margin-top: 10px;
  }
}

.dialpad-key {
  height: 38px;
  border-radius: 4px;
  border: 1px solid var(--el-border-color-lighter);
  background: var(--el-bg-color);
  font-size: 16px;
  font-weight: 500;
  color: var(--el-text-color-primary);
  cursor: pointer;
  transition: all 0.15s;
  display: flex;
  align-items: center;
  justify-content: center;

  &:hover {
    background: var(--el-color-primary-light-9);
    border-color: var(--el-color-primary-light-7);
    color: var(--el-color-primary);
  }

  &:active {
    background: var(--el-color-primary-light-7);
    transform: scale(0.97);
  }

  &--incall {
    height: 32px;
    font-size: 14px;
  }
}

.dialpad-actions {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 6px;
  margin-top: 8px;
}

.dialpad-act {
  height: 32px;
  border-radius: 4px;
  border: 1px solid transparent;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  transition: all 0.15s;

  &--default {
    background: var(--el-bg-color);
    border-color: var(--el-border-color);
    color: var(--el-text-color-regular);

    &:hover {
      color: var(--el-color-primary);
      border-color: var(--el-color-primary-light-3);
    }
  }

  &--primary {
    background: var(--el-color-primary);
    color: #fff;

    &:hover {
      background: var(--el-color-primary-light-3);
    }
  }
}

// ==================== 多通话列表样式 ====================

.session-list {
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.session-list-header {
  padding: 8px 16px;
  font-size: 12px;
  font-weight: 600;
  color: var(--el-text-color-secondary);
  background: var(--el-fill-color-light);
}

.session-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 16px;
  cursor: pointer;
  transition: background 0.15s;

  &:hover {
    background: var(--el-fill-color);
  }

  &--active {
    background: var(--el-color-primary-light-9);
    border-left: 3px solid var(--el-color-primary);
    padding-left: 13px;
  }
}

.session-item-number {
  font-family: 'Menlo', 'Monaco', 'Consolas', monospace;
  font-size: 13px;
  color: var(--el-text-color-primary);
  letter-spacing: 0.5px;
}

.session-item-status {
  font-size: 11px;
  font-weight: 500;
  padding: 2px 8px;
  border-radius: 10px;

  &--ringing {
    background: var(--el-color-warning-light-9);
    color: var(--el-color-warning);
  }

  &--active {
    background: var(--el-color-success-light-9);
    color: var(--el-color-success);
  }

  &--held {
    background: var(--el-color-info-light-9);
    color: var(--el-color-info);
  }
}

// ==================== 通话控制区域样式 ====================

.active-call {
  padding: 16px;
  text-align: center;
}

.active-call-timer {
  font-family: 'Menlo', 'Monaco', 'Consolas', monospace;
  font-size: 24px;
  font-weight: 600;
  color: var(--el-color-primary);
  margin-bottom: 6px;
  letter-spacing: 2px;
}

.active-call-number {
  font-family: 'Menlo', 'Monaco', 'Consolas', monospace;
  font-size: 13px;
  color: var(--el-text-color-regular);
  margin-bottom: 12px;
  letter-spacing: 1px;
}

.call-controls {
  display: flex;
  gap: 8px;
  margin-bottom: 10px;
}

.call-ctrl-btn {
  flex: 1;
  height: 32px;
  border-radius: 4px;
  border: 1px solid var(--el-border-color);
  background: var(--el-bg-color);
  font-size: 12px;
  font-weight: 500;
  color: var(--el-text-color-regular);
  cursor: pointer;
  transition: all 0.15s;

  &:hover:not(:disabled) {
    color: var(--el-color-primary);
    border-color: var(--el-color-primary-light-3);
  }

  &:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  &--active {
    background: var(--el-color-primary-light-9);
    border-color: var(--el-color-primary-light-5);
    color: var(--el-color-primary);

    &:hover:not(:disabled) {
      background: var(--el-color-primary-light-8);
    }
  }

  &--transfer {
    border-color: var(--el-color-warning-light-5);
    color: var(--el-color-warning);

    &:hover:not(:disabled) {
      background: var(--el-color-warning-light-9);
    }
  }
}

.transfer-panel {
  margin-top: 8px;
  padding: 12px;
  border-radius: 6px;
  background: var(--el-bg-color-page);
  border: 1px solid var(--el-border-color-lighter);
}

.hangup-full {
  width: 100%;
  height: 36px;
  border-radius: 4px;
  border: none;
  background: var(--el-color-danger);
  color: #fff;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  transition: all 0.15s;

  &:hover {
    background: var(--el-color-danger-light-3);
  }
}

// ==================== 来电弹窗样式 ====================

.incoming-dialog {
  position: fixed;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  background: var(--el-bg-color);
  border-radius: 12px;
  width: 280px;
  overflow: hidden;
  box-shadow: 0 12px 48px rgba(0, 0, 0, 0.12);
  border: 1px solid var(--el-border-color-lighter);
  z-index: 3000;
}

.incoming-overlay {
  position: fixed;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background: rgba(0, 0, 0, 0.3);
  z-index: 2999;
}

.incoming-header {
  background: var(--el-color-primary);
  padding: 24px 20px 18px;
  text-align: center;
  color: white;
}

.incoming-avatar {
  width: 48px;
  height: 48px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.2);
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0 auto 10px;
}

.incoming-title {
  font-size: 15px;
  font-weight: 600;
  margin-bottom: 4px;
}

.incoming-number {
  font-family: 'Menlo', 'Monaco', 'Consolas', monospace;
  font-size: 13px;
  opacity: 0.9;
  letter-spacing: 1px;
}

.incoming-actions {
  display: flex;
  gap: 10px;
  padding: 14px 20px 18px;
}

.incoming-btn {
  flex: 1;
  height: 36px;
  border-radius: 4px;
  border: 1px solid transparent;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  transition: all 0.2s;

  &--reject {
    background: var(--el-color-danger-light-9);
    color: var(--el-color-danger);
    border-color: var(--el-color-danger-light-7);

    &:hover {
      background: var(--el-color-danger-light-7);
    }
  }

  &--accept {
    background: var(--el-color-success);
    color: #fff;

    &:hover {
      background: var(--el-color-success-light-3);
    }
  }
}
</style>
