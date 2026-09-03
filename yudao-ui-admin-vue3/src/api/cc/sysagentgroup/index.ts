import request from '@/config/axios'

export interface SysAgentGroupVO {
  id: number
  name: string
  priority: number
  describe: string
  strategyType: number
  fullBusyType: number
  overflowType: number
  overflowValue: string
  timeOut: number
  queueLength: number
  availableGatewayIds?: number[] // 可用网关ID列表（多选，前端传数组，后端拼接英文逗号存储）
}

export const SysAgentGroupApi = {
  getSysAgentGroupPage: async (params: any) => {
    return await request.get({ url: `/cc/sys-agent-group/page`, params })
  },
  getSysAgentGroup: async (id: number) => {
    return await request.get({ url: `/cc/sys-agent-group/get?id=` + id })
  },
  createSysAgentGroup: async (data: SysAgentGroupVO) => {
    return await request.post({ url: `/cc/sys-agent-group/create`, data })
  },
  updateSysAgentGroup: async (data: SysAgentGroupVO) => {
    return await request.put({ url: `/cc/sys-agent-group/update`, data })
  },
  deleteSysAgentGroup: async (id: number) => {
    return await request.delete({ url: `/cc/sys-agent-group/delete?id=` + id })
  },
  exportSysAgentGroup: async (params) => {
    return await request.download({ url: `/cc/sys-agent-group/export-excel`, params })
  },
  deleteSysAgentGroupList: async (ids: number[]) => {
    return await request.delete({ url: `/cc/sys-agent-group/delete-list?ids=${ids.join(',')}`})
  },
  list: async () => {
    return await request.get({ url: `/cc/sys-agent-group/list` })
  },
}

