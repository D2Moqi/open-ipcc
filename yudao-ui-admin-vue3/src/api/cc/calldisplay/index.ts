import request from '@/config/axios'

// cc 号码管理 VO
export interface CallDisplayVO {
  id: number // 主键id
  phone: string // 电话号码
  area: string // 归属地
  remark?: string // 备注
}

// cc 号码管理 API
export const CallDisplayApi = {
  // 查询cc 号码管理分页
  getCallDisplayPage: async (params: any) => {
    return await request.get({ url: `/cc/call-display/page`, params })
  },

  // 查询cc 号码管理详情
  getCallDisplay: async (id: number) => {
    return await request.get({ url: `/cc/call-display/get?id=` + id })
  },

  // 新增cc 号码管理
  createCallDisplay: async (data: CallDisplayVO) => {
    return await request.post({ url: `/cc/call-display/create`, data })
  },

  // 修改cc 号码管理
  updateCallDisplay: async (data: CallDisplayVO) => {
    return await request.put({ url: `/cc/call-display/update`, data })
  },

  // 删除cc 号码管理
  deleteCallDisplay: async (id: number) => {
    return await request.delete({ url: `/cc/call-display/delete?id=` + id })
  },

  // 导出cc 号码管理 Excel
  exportCallDisplay: async (params) => {
    return await request.download({ url: `/cc/call-display/export-excel`, params })
  },

  // 批量删除cc 号码管理
  deleteCallDisplayList: async (ids: number[]) => {
    return await request.delete({ url: `/cc/call-display/delete-list?ids=${ids.join(',')}`})
  },
  // 查询cc 号码管理列表
  list: async () => {
    return await request.get({ url: `/cc/call-display/list` })
  },
}
