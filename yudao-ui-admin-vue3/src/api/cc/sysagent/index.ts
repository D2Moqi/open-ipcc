import request from '@/config/axios'

export interface SysAgentVO {
  id: number
  name: string
  userId: number
  userName?: string
  domain: string
  status: number
  onlineStatus: number
}

export const SysAgentApi = {
  getSysAgentPage: async (params: any) => {
    return await request.get({ url: `/cc/sys-agent/page`, params })
  },
  list: async () => {
    return await request.get({ url: `/cc/sys-agent/list` })
  },
  getSysAgent: async (id: number) => {
    return await request.get({ url: `/cc/sys-agent/get?id=` + id })
  },
  createSysAgent: async (data: SysAgentVO) => {
    return await request.post({ url: `/cc/sys-agent/create`, data })
  },
  updateSysAgent: async (data: SysAgentVO) => {
    return await request.put({ url: `/cc/sys-agent/update`, data })
  },
  deleteSysAgent: async (id: number) => {
    return await request.delete({ url: `/cc/sys-agent/delete?id=` + id })
  },
  exportSysAgent: async (params) => {
    return await request.download({ url: `/cc/sys-agent/export-excel`, params })
  },
  deleteSysAgentList: async (ids: number[]) => {
    return await request.delete({ url: `/cc/sys-agent/delete-list?ids=${ids.join(',')}`})
  },
  getSysAgentByUserId: async () => {
    return await request.get({ url: `/cc/sys-agent/get-by-user-id`})
  },
}
