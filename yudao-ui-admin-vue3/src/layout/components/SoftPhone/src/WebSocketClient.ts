
import { getRefreshToken } from '@/utils/auth'
import { ref } from 'vue'

/** WebSocket 业务消息通道路径(与后端 CcWebSocketMessageEndpoint 约定) */
const WS_BUSINESS_PATH = '/cc/ws'
/** URL 协议替换: HTTP → WebSocket */
const WS_PROTOCOL_HTTP = 'http'
const WS_PROTOCOL_WS = 'ws'
/** 鉴权查询参数前缀 */
const WS_TOKEN_QUERY = '?token='
/** WebSocket 主动关闭码(正常关闭) */
const WS_CLOSE_CODE_NORMAL = 1000
/** WebSocket 主动关闭原因 */
const WS_CLOSE_REASON_CLIENT = 'client closed'
/** waitForConnection 轮询检测间隔(毫秒) */
const CONNECTION_POLL_INTERVAL_MS = 100

/**
 * WebSocket 连接状态枚举
 * <p>
 * 用于外部组件订阅连接状态,实现 UI 同步和业务流程控制。
 * 状态流转:
 * <ul>
 *   <li>首次连接: DISCONNECTED → CONNECTING → CONNECTED</li>
 *   <li>断线重连: CONNECTED → DISCONNECTED → RECONNECTING → CONNECTED</li>
 *   <li>主动关闭: CONNECTED → DISCONNECTED (不触发重连)</li>
 * </ul>
 */
export enum WsConnectionState {
  /** 已断开(初始或主动关闭后) */
  DISCONNECTED = 'DISCONNECTED',
  /** 首次连接中 */
  CONNECTING = 'CONNECTING',
  /** 已连接,可正常收发消息 */
  CONNECTED = 'CONNECTED',
  /** 重连中(网络中断/服务重启后自动重试) */
  RECONNECTING = 'RECONNECTING'
}

/**
 * WebSocket 客户端实例
 */
const wsClient = ref<WebSocket | null>(null);

/**
 * 当前连接状态(响应式,外部组件可订阅)
 */
const wsConnectionState = ref<WsConnectionState>(WsConnectionState.DISCONNECTED);

/**
 * 是否为首次连接
 * <p>用于区分"首次连接成功"与"重连成功",仅重连成功时才触发状态同步回调。</p>
 */
let isFirstConnection = true;

/**
 * 重连尝试次数
 */
let reconnectAttempts = 0;

/**
 * 最大重连尝试次数
 * <p>
 * 设为 Infinity 表示无限重连。
 * 设计依据: 后端服务重启耗时通常在 30 秒~2 分钟之间,部分场景(如灰度发布、人工排障)可能更长,
 * 采用无限重连确保服务恢复后能自动重连成功,避免用户被迫刷新页面。
 * </p>
 */
const MAX_RECONNECT_ATTEMPTS = Infinity;

/**
 * 重连基础间隔(毫秒),首次重连延迟
 */
const RECONNECT_BASE_INTERVAL = 1000;

/**
 * 重连最大间隔(毫秒),指数退避上限
 */
const RECONNECT_MAX_INTERVAL = 60000;

/**
 * 心跳定时器
 */
const heartbeatInterval = ref<ReturnType<typeof setInterval> | null>(null);

/**
 * 心跳发送间隔(毫秒)
 */
const HEARTBEAT_INTERVAL_MS = 10000;

/**
 * 心跳超时阈值(毫秒)
 * <p>
 * 超过此时间未收到服务端任何消息(含心跳响应),则判定连接异常,主动断开触发重连。
 * 取值依据: 心跳间隔 10s × 3 次 + 5s 余量 = 35s,容忍偶发网络抖动。
 * </p>
 */
const HEARTBEAT_TIMEOUT_MS = 35000;

/**
 * 最后收到服务端消息的时间戳
 */
let lastMessageTime = Date.now();

/**
 * 心跳超时检测定时器
 */
let heartbeatCheckTimer: ReturnType<typeof setInterval> | null = null;

/**
 * 待发送消息队列项
 */
interface PendingMessage {
  /** 消息类型(对应后端 JsonWebSocketMessage.type) */
  type: string;
  /** 消息内容(JSON 字符串) */
  content: string;
  /** 入队时间戳(毫秒),用于日志追踪 */
  timestamp: number;
}

/**
 * 待发送消息队列
 * <p>
 * 连接断开期间,业务消息(如坐席状态变更)暂存于此队列,
 * 重连成功后通过 {@link flushPendingMessages} 自动按 FIFO 顺序发送,
 * 保障用户操作的连续性和数据一致性。
 * </p>
 */
const pendingMessages: PendingMessage[] = [];

/**
 * 待发送消息队列最大长度
 * <p>防止连接长时间断开导致内存溢出,超过阈值时丢弃最旧的消息(仅保留最新状态)。</p>
 */
const MAX_PENDING_MESSAGES = 100;

/**
 * 服务端返回的会话ID
 */
const sessionId = ref('');

/**
 * 坐席状态变更消息数据
 * 对应后端 AGENT_STATUS / AGENT_STATUS_CHANGED 事件 data 字段
 */
interface AgentStatusData {
  /** 坐席ID */
  agentId: number | string
  /** 在线状态码(1-空闲 2-忙碌 3-勿扰 4-离线 5-通话中 6-振铃中 7-话后) */
  onlineStatus: number | string
}

/**
 * WebSocket 消息内容接口
 * 对应后端 CcWebSocketMessagePayload
 */
interface WsMsgPayload {
  /** 会话ID */
  sessionId: string;
  /** 消息发送时间戳（毫秒） */
  timestamp: number;
  /** 事件类型 */
  event: EventEnum;
  /** 事件数据(HEARTBEAT 为空对象, AGENT_STATUS 为 AgentStatusData) */
  data: AgentStatusData | Record<string, never>;
}

/**
 * 服务端推送的消息接口
 * 对应后端 JsonWebSocketMessage
 */
interface WsServerMessage {
  /** 消息类型 */
  type: string;
  /** 消息内容（JSON字符串） */
  content: string;
}

/**
 * 服务端推送的 payload(content 解析结果)
 * 对应后端 CcWebSocketMessagePayload, event 决定 data 的具体结构
 */
interface WsServerPayload {
  /** 事件类型 */
  event: string
  /** 事件数据(结构由 event 决定, AGENT_STATUS_CHANGED 时为 AgentStatusData) */
  data: AgentStatusData | Record<string, unknown>
}

/**
 * WebSocket 消息类型常量，与后端 AgentStatusMessageListener.getType() 匹配
 */
const WS_TYPE = 'cc-message'

/**
 * WebSocket 事件类型枚举
 * 与后端 CcWebSocketEventEnum 保持一致
 */
enum EventEnum {
  /** 心跳包事件 */
  HEARTBEAT = 'HEARTBEAT',
  /** 坐席状态变更事件（前端 → 服务端） */
  AGENT_STATUS = 'AGENT_STATUS',
  /** 坐席状态变更通知事件（服务端 → 前端），用于实时更新坐席状态显示 */
  AGENT_STATUS_CHANGED = 'AGENT_STATUS_CHANGED',
  /** 未知事件类型 */
  UNKNOWN = 'UNKNOWN'
}

/**
 * 坐席状态变更回调函数类型
 *
 * @param agentId 坐席ID
 * @param onlineStatus 变更后的在线状态码（1-空闲 2-忙碌 3-勿扰 4-离线 5-通话中 6-振铃中 7-话后）
 */
type AgentStatusChangedHandler = (agentId: number, onlineStatus: number) => void

/**
 * 重连成功回调函数类型
 * <p>无参,触发时表示 WebSocket 已重新建立连接并完成待发送队列刷新。</p>
 */
type ReconnectedHandler = () => void

/**
 * 连接状态变更回调函数类型
 *
 * @param state 新的连接状态
 */
type ConnectionStateChangeHandler = (state: WsConnectionState) => void

/**
 * 坐席状态变更回调列表
 * <p>
 * 外部组件（如 SoftPhone.vue）通过 {@link onAgentStatusChanged} 注册回调，
 * 当收到服务端推送的 AGENT_STATUS_CHANGED 事件时依次触发。
 * </p>
 */
const agentStatusChangedHandlers: AgentStatusChangedHandler[] = []

/**
 * 重连成功回调列表
 * <p>
 * 外部组件通过 {@link onReconnected} 注册,WebSocket 重连成功并刷新待发送队列后触发。
 * 典型场景: SoftPhone.vue 在回调中重新查询坐席信息、同步当前状态到服务端、
 * 必要时触发 SIP 客户端重连,保障后端服务重启后业务连续性。
 * </p>
 */
const reconnectedHandlers: ReconnectedHandler[] = []

/**
 * 连接状态变更回调列表
 * <p>外部组件通过 {@link onConnectionStateChange} 注册,用于 UI 状态同步(如显示"重连中"提示)。</p>
 */
const connectionStateChangeHandlers: ConnectionStateChangeHandler[] = []

/**
 * 注册坐席状态变更回调
 * <p>
 * 当服务端推送 AGENT_STATUS_CHANGED 事件时，已注册的回调会被依次调用。
 * 典型场景：SoftPhone.vue 在 onMounted 中注册回调，更新 agentStatusValue。
 *
 * @param handler 回调函数，接收 agentId 和 onlineStatus
 */
export const onAgentStatusChanged = (handler: AgentStatusChangedHandler): void => {
  if (typeof handler === 'function' && !agentStatusChangedHandlers.includes(handler)) {
    agentStatusChangedHandlers.push(handler)
  }
};

/**
 * 移除坐席状态变更回调
 * <p>
 * 组件卸载时应调用以避免内存泄漏和重复触发。
 *
 * @param handler 待移除的回调函数
 */
export const offAgentStatusChanged = (handler: AgentStatusChangedHandler): void => {
  const idx = agentStatusChangedHandlers.indexOf(handler)
  if (idx >= 0) {
    agentStatusChangedHandlers.splice(idx, 1)
  }
};

/**
 * 注册重连成功回调
 * <p>
 * WebSocket 重连成功并完成待发送队列刷新后触发。
 * 典型场景: SoftPhone.vue 在 onMounted 中注册,用于:
 * <ul>
 *   <li>重新查询坐席信息(避免后端重启后内存中的坐席状态丢失)</li>
 *   <li>同步当前坐席状态到服务端(确保服务端状态与前端一致)</li>
 *   <li>必要时触发 SIP 客户端重连(因 SIP WebSocket 可能同时断开)</li>
 * </ul>
 *
 * @param handler 回调函数,无参
 */
export const onReconnected = (handler: ReconnectedHandler): void => {
  if (typeof handler === 'function' && !reconnectedHandlers.includes(handler)) {
    reconnectedHandlers.push(handler)
  }
};

/**
 * 注销重连成功回调
 * <p>组件卸载时应调用以避免内存泄漏。</p>
 *
 * @param handler 待移除的回调函数
 */
export const offReconnected = (handler: ReconnectedHandler): void => {
  const idx = reconnectedHandlers.indexOf(handler)
  if (idx >= 0) {
    reconnectedHandlers.splice(idx, 1)
  }
};

/**
 * 注册连接状态变更回调
 * <p>连接状态发生变化时触发,用于 UI 状态同步(如显示"连接中/重连中"提示)。</p>
 *
 * @param handler 回调函数,接收新的连接状态
 */
export const onConnectionStateChange = (handler: ConnectionStateChangeHandler): void => {
  if (typeof handler === 'function' && !connectionStateChangeHandlers.includes(handler)) {
    connectionStateChangeHandlers.push(handler)
  }
};

/**
 * 注销连接状态变更回调
 *
 * @param handler 待移除的回调函数
 */
export const offConnectionStateChange = (handler: ConnectionStateChangeHandler): void => {
  const idx = connectionStateChangeHandlers.indexOf(handler)
  if (idx >= 0) {
    connectionStateChangeHandlers.splice(idx, 1)
  }
};

/**
 * 获取当前 WebSocket 连接状态
 *
 * @returns 当前连接状态枚举值
 */
export const getWsConnectionState = (): WsConnectionState => {
  return wsConnectionState.value
};

/**
 * 判断 WebSocket 是否已连接(可发送消息)
 *
 * @returns true 表示连接已就绪
 */
export const isWsConnected = (): boolean => {
  return wsClient.value !== null && wsClient.value.readyState === WebSocket.OPEN
};

/**
 * 等待 WebSocket 连接就绪
 * <p>
 * 在发送消息前确保连接可用,适应服务重启后短暂等待重连完成的场景。
 *
 * @param timeoutMs 最大等待时间(毫秒),默认 5000ms
 * @returns true 表示连接已就绪; false 表示等待超时仍未连接
 */
export const waitForConnection = (timeoutMs: number = 5000): Promise<boolean> => {
  return new Promise((resolve) => {
    if (isWsConnected()) {
      resolve(true)
      return
    }
    const startTime = Date.now()
    const timer = setInterval(() => {
      if (isWsConnected()) {
        clearInterval(timer)
        resolve(true)
      } else if (Date.now() - startTime >= timeoutMs) {
        clearInterval(timer)
        resolve(false)
      }
    }, CONNECTION_POLL_INTERVAL_MS)
  })
};

/**
 * 设置连接状态并通知订阅者
 * <p>状态未变化时不触发回调,避免冗余通知。</p>
 *
 * @param state 新的连接状态
 */
const setConnectionState = (state: WsConnectionState): void => {
  if (wsConnectionState.value === state) return
  console.log(`[WebSocketClient] 连接状态变更: ${wsConnectionState.value} -> ${state}`)
  wsConnectionState.value = state
  connectionStateChangeHandlers.forEach((handler) => {
    try {
      handler(state)
    } catch (err) {
      console.error('[WebSocketClient] 连接状态变更回调执行异常:', err)
    }
  })
};


/**
 * 根据字符串值获取对应的事件枚举
 *
 * @param value 事件字符串
 * @returns 对应的事件枚举值
 */
function getEventFromValue(value: string): EventEnum {
  const result = Object.values(EventEnum).find(
      (v) => v === value
  );
  return result as EventEnum || EventEnum.UNKNOWN;
}

/**
 * 初始化 WebSocket 客户端连接
 * <p>
 * 使用 refreshToken 建立 WebSocket 连接，设置消息处理和重连机制。
 * 连接成功后自动启动心跳包定时发送和心跳超时检测。
 * </p>
 * <p>
 * 重连场景下(非首次连接),连接成功后会自动:
 * <ol>
 *   <li>刷新待发送队列({@link flushPendingMessages}),将断连期间缓存的消息按序发送</li>
 *   <li>触发重连成功回调({@link reconnectedHandlers}),供上层组件同步业务状态</li>
 * </ol>
 * </p>
 * <p>
 * 每次初始化前会清理旧连接及其回调,避免事件监听器泄漏和重复触发。
 * </p>
 */
export const initWebsocketClient = () => {
  // 清理已有连接及其事件监听器,避免重连时新旧连接并存导致回调重复触发
  if (wsClient.value) {
    try {
      wsClient.value.onopen = null
      wsClient.value.onmessage = null
      wsClient.value.onclose = null
      wsClient.value.onerror = null
      wsClient.value.close()
    } catch (e) {
      console.warn('[WebSocketClient] 关闭旧连接异常:', e)
    }
    wsClient.value = null
  }

  // 动态获取最新的 refreshToken,避免 token 过期导致重连失败
  const wsUrl = (import.meta.env.VITE_BASE_URL + WS_BUSINESS_PATH).replace(WS_PROTOCOL_HTTP, WS_PROTOCOL_WS)
    + WS_TOKEN_QUERY + getRefreshToken()

  setConnectionState(reconnectAttempts === 0 ? WsConnectionState.CONNECTING : WsConnectionState.RECONNECTING)

  wsClient.value = new WebSocket(wsUrl);

  wsClient.value.onopen = () => {
    console.log('[WebSocketClient] 连接已打开');
    reconnectAttempts = 0;
    lastMessageTime = Date.now();
    setConnectionState(WsConnectionState.CONNECTED);
    // 启动心跳包定时发送
    sendHeartbeat();
    // 启动心跳超时检测,主动发现隐性断连
    startHeartbeatCheck();
    // 重连场景(非首次连接): 刷新待发送队列并触发重连成功回调
    if (!isFirstConnection) {
      console.log('[WebSocketClient] 重连成功,开始刷新待发送队列并通知上层组件');
      flushPendingMessages();
      reconnectedHandlers.forEach((handler) => {
        try {
          handler()
        } catch (err) {
          console.error('[WebSocketClient] 重连成功回调执行异常:', err)
        }
      })
    } else {
      isFirstConnection = false
    }
  };

  wsClient.value.onmessage = (event) => {
    // 更新最后收到消息时间,供心跳超时检测使用
    lastMessageTime = Date.now();
    console.log('[WebSocketClient] 收到服务器消息:', event.data);
    handleServerMessage(event.data);
  };

  wsClient.value.onclose = (event) => {
    console.log('[WebSocketClient] 连接已关闭, code:', event.code);
    // 停止心跳和超时检测,避免对已关闭的连接发送消息
    stopHeartbeatCheck();
    if (heartbeatInterval.value) {
      clearInterval(heartbeatInterval.value);
      heartbeatInterval.value = null;
    }
    setConnectionState(WsConnectionState.DISCONNECTED);
    // 主动关闭(code=1000)不重试
    if (event.code === WS_CLOSE_CODE_NORMAL) {
      console.log('[WebSocketClient] 主动关闭，不进行重连');
      return;
    }
    reconnectWebSocket();
  };

  wsClient.value.onerror = (error) => {
    console.error('[WebSocketClient] 连接错误:', error);
    // 不在此处主动 close,由 onclose 统一处理重连,避免重复触发
  };
};

/**
 * 处理服务端推送的消息
 * <p>
 * 服务端推送的消息格式为 JsonWebSocketMessage：{ type: "xxx", content: "..." }
 * 其中 content 是 JSON 字符串，包含 event 和 data 字段。
 *
 * @param rawData 原始消息数据（字符串）
 */
const handleServerMessage = (rawData: string) => {
  try {
    // 先尝试解析为服务端 JsonWebSocketMessage 格式
    const serverMsg: WsServerMessage = JSON.parse(rawData);

    if (serverMsg.type && serverMsg.content) {
      // 标准格式：{ type, content }，解析 content
      try {
        const payload = JSON.parse(serverMsg.content) as WsServerPayload;
        dispatchEvent(payload);
      } catch {
        console.warn('[WebSocketClient] content JSON 解析失败:', serverMsg.content);
      }
      return;
    }

    console.warn('[WebSocketClient] 无法识别的消息格式:', rawData)
  } catch {
    // 非 JSON 消息（如 "pong"），忽略
  }
};

/**
 * 根据事件类型分发处理
 * <p>
 * 服务端推送的消息经 {@link handleServerMessage} 解析后调用此方法，
 * 根据 payload.event 分发到对应的处理逻辑。
 *
 * @param payload 消息内容对象，包含 event 和 data 字段
 */
const dispatchEvent = (payload: WsServerPayload) => {
  const event = getEventFromValue(payload.event);
  switch (event) {
    case EventEnum.AGENT_STATUS_CHANGED:
      handleAgentStatusChanged(payload.data as AgentStatusData);
      break;
    case EventEnum.HEARTBEAT:
      // 心跳包由 session 活跃时间管理，无需额外处理
      break;
    default:
      console.warn('[WebSocketClient] 未知事件类型:', payload.event);
  }
};

/**
 * 处理服务端推送的坐席状态变更通知
 * <p>
 * 从消息 data 中提取 agentId 和 onlineStatus，
 * 依次调用已注册的回调函数，通知外部组件（如 SoftPhone.vue）更新坐席状态显示。
 * <p>
 * 边界处理：
 *   - data 为空时打印警告并返回
 *   - agentId/onlineStatus 非法（NaN）时打印警告并返回
 *   - 单个回调抛异常不影响其他回调执行
 *
 * @param data 消息数据，包含 agentId 和 onlineStatus 字段
 */
const handleAgentStatusChanged = (data: AgentStatusData): void => {
  if (!data) {
    console.warn('[WebSocketClient] AGENT_STATUS_CHANGED 消息缺少 data 字段')
    return
  }
  const agentId = Number(data.agentId)
  const onlineStatus = Number(data.onlineStatus)
  if (Number.isNaN(agentId) || Number.isNaN(onlineStatus)) {
    console.warn('[WebSocketClient] AGENT_STATUS_CHANGED 消息字段非法, data:', data)
    return
  }
  console.log('[WebSocketClient] 收到坐席状态变更通知, agentId:', agentId, 'onlineStatus:', onlineStatus)
  // 依次触发已注册的回调，单个回调异常不影响其他回调
  agentStatusChangedHandlers.forEach((handler) => {
    try {
      handler(agentId, onlineStatus)
    } catch (err) {
      console.error('[WebSocketClient] 坐席状态变更回调执行异常:', err)
    }
  })
};

/**
 * 重连 WebSocket
 * <p>
 * 采用指数退避策略进行重连,重连次数无上限(MAX_RECONNECT_ATTEMPTS = Infinity),
 * 适应后端服务重启等长时间断连场景。
 * </p>
 * <p>
 * 重连间隔计算: min(RECONNECT_BASE_INTERVAL × 2^attempts, RECONNECT_MAX_INTERVAL)
 *   - 第 1 次: 1s
 *   - 第 2 次: 2s
 *   - 第 3 次: 4s
 *   - 第 4 次: 8s
 *   - 第 5 次: 16s
 *   - 第 6 次及以后: 60s(上限)
 * </p>
 * <p>
 * 设计依据: 后端服务重启耗时通常在 30 秒~2 分钟之间,
 * 短间隔快速重连覆盖瞬时抖动,长间隔(60s)避免长时间无效重连浪费资源。
 * </p>
 */
const reconnectWebSocket = () => {
  if (reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
    console.error('[WebSocketClient] 重连失败，已达最大重试次数:', MAX_RECONNECT_ATTEMPTS);
    return;
  }

  const delay = Math.min(
    RECONNECT_BASE_INTERVAL * Math.pow(2, reconnectAttempts),
    RECONNECT_MAX_INTERVAL
  );
  reconnectAttempts++;
  console.log(`[WebSocketClient] 第 ${reconnectAttempts} 次重连,延迟 ${delay}ms`);
  setConnectionState(WsConnectionState.RECONNECTING);

  setTimeout(() => {
    initWebsocketClient();
  }, delay);
};

/**
 * 启动心跳超时检测
 * <p>
 * 定时检查最后收到服务端消息的时间,超过 {@link HEARTBEAT_TIMEOUT_MS} 阈值
 * 则判定连接异常(如服务端进程被杀、网络链路单通),主动断开触发重连。
 * </p>
 * <p>
 * 必要性: 部分 TCP 半开连接(如 NAT 超时)不会触发 onclose 事件,
 * 仅靠心跳超时检测才能发现并恢复。
 * </p>
 */
const startHeartbeatCheck = () => {
  stopHeartbeatCheck();
  heartbeatCheckTimer = setInterval(() => {
    const elapsed = Date.now() - lastMessageTime;
    if (elapsed > HEARTBEAT_TIMEOUT_MS) {
      console.warn(`[WebSocketClient] 心跳超时 ${elapsed}ms,主动断开触发重连`);
      try {
        // 主动断开,onclose 中会触发重连
        wsClient.value?.close();
      } catch (e) {
        console.warn('[WebSocketClient] 主动关闭异常:', e);
      }
    }
  }, HEARTBEAT_INTERVAL_MS);
};

/**
 * 停止心跳超时检测
 */
const stopHeartbeatCheck = () => {
  if (heartbeatCheckTimer) {
    clearInterval(heartbeatCheckTimer);
    heartbeatCheckTimer = null;
  }
};

/**
 * 启动心跳包定时发送
 * <p>
 * 每 {@link HEARTBEAT_INTERVAL_MS} 向服务端发送一次 HEARTBEAT 消息，保持连接活跃。
 * 连接断开或重新初始化时会自动清除旧定时器。
 */
const sendHeartbeat = () => {
  if (heartbeatInterval.value) clearInterval(heartbeatInterval.value);
  heartbeatInterval.value = setInterval(() => {
    if (wsClient.value && wsClient.value.readyState === WebSocket.OPEN) {
      const payload: WsMsgPayload = {
        sessionId: sessionId.value,
        timestamp: Date.now(),
        event: EventEnum.HEARTBEAT,
        data: {},
      };
      const msg = {
        type: WS_TYPE,
        content: JSON.stringify(payload)
      };
      try {
        wsClient.value.send(JSON.stringify(msg));
      } catch (e) {
        console.error('[WebSocketClient] 发送心跳失败:', e);
      }
    }
  }, HEARTBEAT_INTERVAL_MS);
};

/**
 * 刷新待发送消息队列
 * <p>
 * 重连成功后自动调用,将连接断开期间缓存的消息按 FIFO 顺序发送到服务端。
 * 发送失败时将消息放回队列头部并终止刷新,等待下次重连成功后继续。
 * </p>
 * <p>
 * 业务意义: 保障用户在服务重启期间的操作(如切换就绪/忙碌状态)不丢失,
 * 服务恢复后自动同步到后端,确保坐席状态一致性。
 * </p>
 */
const flushPendingMessages = () => {
  if (pendingMessages.length === 0) return;
  console.log(`[WebSocketClient] 刷新待发送消息队列,共 ${pendingMessages.length} 条`);
  while (pendingMessages.length > 0 && isWsConnected()) {
    const msg = pendingMessages.shift();
    if (msg) {
      try {
        wsClient.value?.send(JSON.stringify({
          type: msg.type,
          content: msg.content
        }));
        console.log('[WebSocketClient] 已发送缓存消息,原始入队时间:', new Date(msg.timestamp).toISOString());
      } catch (e) {
        console.error('[WebSocketClient] 发送缓存消息失败,放回队列等待下次重连:', e);
        // 发送失败,放回队列头部
        pendingMessages.unshift(msg);
        break;
      }
    }
  }
};

/**
 * 将消息加入待发送队列
 * <p>
 * 队列满时丢弃最旧的消息(仅保留最新状态),避免内存溢出。
 * 业务场景: 坐席状态短时间内多次切换,仅需同步最终状态。
 * </p>
 *
 * @param msg 待入队的消息
 */
const enqueueMessage = (msg: { type: string; content: string }): void => {
  if (pendingMessages.length >= MAX_PENDING_MESSAGES) {
    const dropped = pendingMessages.shift();
    console.warn('[WebSocketClient] 待发送队列已满,丢弃最旧消息:', dropped);
  }
  pendingMessages.push({ ...msg, timestamp: Date.now() });
};

/**
 * 通过 WebSocket 发送坐席状态变更请求
 * <p>
 * 将坐席的新状态发送到服务端，服务端处理后返回 AGENT_STATUS_ACK 确认。
 * 同时更新数据库 cc_sys_agent.online_status 和 Redis Hash fs:agent:status。
 * </p>
 * <p>
 * 容错策略: WebSocket 未连接时,将消息加入待发送队列({@link pendingMessages}),
 * 重连成功后通过 {@link flushPendingMessages} 自动发送,
 * 避免后端服务重启期间用户操作丢失,保障数据一致性。
 * </p>
 *
 * @param agentId 坐席ID
 * @param status  在线状态值（字符串类型，如 "1"-空闲, "2"-忙碌, "4"-离线 等）
 */
export const updateAgentStatus = (agentId: number, status: string) => {
  const payload: WsMsgPayload = {
    sessionId: sessionId.value,
    timestamp: Date.now(),
    event: EventEnum.AGENT_STATUS,
    data: {
      agentId: agentId,
      onlineStatus: status,
    },
  };
  const msg = {
    type: WS_TYPE,
    content: JSON.stringify(payload)
  };

  if (isWsConnected()) {
    try {
      wsClient.value?.send(JSON.stringify(msg));
      console.log('[WebSocketClient] 发送坐席状态变更请求, agentId:', agentId, 'status:', status);
    } catch (e) {
      console.error('[WebSocketClient] 发送消息异常,加入待发送队列:', e);
      enqueueMessage(msg);
    }
  } else {
    console.warn('[WebSocketClient] WebSocket 未连接,消息已加入待发送队列,等待重连后发送; agentId:', agentId, 'status:', status);
    enqueueMessage(msg);
  }
};

/**
 * 主动关闭 WebSocket 连接
 * <p>
 * 供组件卸载或用户主动签出时调用,设置主动关闭标志(code=1000)避免触发重连。
 * 清理所有定时器和待发送队列,重置连接状态。
 * </p>
 */
export const closeWebsocketClient = (): void => {
  console.log('[WebSocketClient] 主动关闭连接');
  stopHeartbeatCheck();
  if (heartbeatInterval.value) {
    clearInterval(heartbeatInterval.value);
    heartbeatInterval.value = null;
  }
  if (wsClient.value) {
    // 移除事件监听器,避免 onclose 触发重连
    wsClient.value.onopen = null;
    wsClient.value.onmessage = null;
    wsClient.value.onclose = null;
    wsClient.value.onerror = null;
    try {
      wsClient.value.close(WS_CLOSE_CODE_NORMAL, WS_CLOSE_REASON_CLIENT);
    } catch (e) {
      console.warn('[WebSocketClient] 关闭异常:', e);
    }
    wsClient.value = null;
  }
  setConnectionState(WsConnectionState.DISCONNECTED);
  // 清空待发送队列,避免组件卸载后残留消息
  pendingMessages.length = 0;
  // 重置首次连接标志,允许下次 initWebsocketClient 触发重连回调
  isFirstConnection = true;
  reconnectAttempts = 0;
};
