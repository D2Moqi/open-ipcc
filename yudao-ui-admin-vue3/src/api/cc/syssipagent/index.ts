import request from '@/config/axios'

// cc sip坐席管理 VO
export interface SysSipAgentVO {
  id: number // 主键id
  name: string // 坐席名称
  userId: number // 主键ID
  agentNumber: string // sip账号ID
  status: number // 开通状态 0-未开通 1-开通
  onlineStatus: number // 在线状态
  domain: string // sip域名
  password: string // sip密码
}

// 可用网关VO（复用FsSipGatewayVO结构）
export interface AvailableGatewayVO {
  id: number
  name: string
  [key: string]: any
}

// cc sip坐席管理 API
export const SysSipAgentApi = {
  // 查询cc sip坐席管理分页
  getSysSipAgentPage: async (params: any) => {
    return await request.get({ url: `/cc/sys-agent/page`, params })
  },
  // 查询cc sip坐席列表
  list: async () => {
    return await request.get({ url: `/cc/sys-agent/list` })
  },
  // 查询cc sip坐席管理详情
  getSysSipAgent: async (id: number) => {
    return await request.get({ url: `/cc/sys-agent/get?id=` + id })
  },

  // 新增cc sip坐席管理
  createSysSipAgent: async (data: SysSipAgentVO) => {
    return await request.post({ url: `/cc/sys-agent/create`, data })
  },

  // 修改cc sip坐席管理
  updateSysSipAgent: async (data: SysSipAgentVO) => {
    return await request.put({ url: `/cc/sys-agent/update`, data })
  },

  // 删除cc sip坐席管理
  deleteSysSipAgent: async (id: number) => {
    return await request.delete({ url: `/cc/sys-agent/delete?id=` + id })
  },

  // 导出cc sip坐席管理 Excel
  exportSysSipAgent: async (params) => {
    return await request.download({ url: `/cc/sys-agent/export-excel`, params })
  },

  // 批量删除cc sip坐席管理
  deleteSysSipAgentList: async (ids: number[]) => {
    return await request.delete({ url: `/cc/sys-agent/delete-list?ids=${ids.join(',')}`})
  },

  // 获得cc sip坐席管理,通过当前登录用户id
  getSysSipAgentByUserId: async () => {
    return await request.get({ url: `/cc/sys-agent/get-by-user-id`})
  },

  // 获取当前登录坐席所属客服组绑定的可用网关列表
  // 软电话外呼场景使用，根据坐席所属坐席组的availableGatewayIds过滤出可用网关
  // 若坐席未绑定任何组或组未配置网关，则返回空列表
  getAvailableGatewayList: async () => {
    return await request.get({ url: `/cc/sys-agent/available-gateway-list` })
  },

  // 强制登录：清理坐席旧会话的 SIP 注册信息，允许新会话重新注册
  // 当同一坐席已在其他地方登录时，新客户端调用此接口清理旧会话后重新发起 REGISTER
  forceLogin: async (data: { extension: string; domain: string }) => {
    return await request.post({ url: `/cc/sys-agent/force-login`, data })
  },
}
