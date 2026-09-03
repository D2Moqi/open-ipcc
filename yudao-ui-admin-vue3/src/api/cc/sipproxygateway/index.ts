import request from '@/config/axios'

export interface SipProxyGatewayVO {
  id?: number
  name: string
  type: number
  // 注册模式（registerEnabled=1）地址由 REGISTER Contact 自动学习，可留空
  address?: string
  port?: number
  toSipProxyIp?: string
  authType: number
  transportProtocol: number
  registerEnabled?: number
  registerRealm?: string
  registerMaxExpires?: number
  authAddress?: string
  authPort?: number
  username?: string | null
  password?: string | null
  callerIdInFrom: number
  fromDomain?: string
  retrySeconds?: number
  pingSeconds?: number
  expireSeconds?: number
  externalLineNumber?: string
  status: number
  remark?: string
  createTime?: Date
}

export const SipProxyGatewayApi = {
  getSipProxyGatewayPage: async (params: any) => {
    return await request.get({ url: `/cc/sip-proxy-gateway/page`, params })
  },
  getSipProxyGateway: async (id: number) => {
    return await request.get({ url: `/cc/sip-proxy-gateway/get?id=` + id })
  },
  createSipProxyGateway: async (data: SipProxyGatewayVO) => {
    return await request.post({ url: `/cc/sip-proxy-gateway/create`, data })
  },
  updateSipProxyGateway: async (data: SipProxyGatewayVO) => {
    return await request.put({ url: `/cc/sip-proxy-gateway/update`, data })
  },
  deleteSipProxyGateway: async (id: number) => {
    return await request.delete({ url: `/cc/sip-proxy-gateway/delete?id=` + id })
  },
  deleteSipProxyGatewayList: async (ids: number[]) => {
    return await request.delete({ url: `/cc/sip-proxy-gateway/delete-list?ids=${ids.join(',')}` })
  },
  getSimpleList: async () => {
    return await request.get({ url: `/cc/sip-proxy-gateway/simple-list` })
  },
  getRegisterStatusList: async () => {
    return await request.get({ url: `/cc/sip-proxy-gateway/register-status-list` })
  },
  exportSipProxyGateway: async (params) => {
    return await request.download({ url: `/cc/sip-proxy-gateway/export-excel`, params })
  },
  refreshCache: async () => {
    return await request.post({ url: `/cc/sip-proxy-gateway/refresh-cache` })
  }
}
