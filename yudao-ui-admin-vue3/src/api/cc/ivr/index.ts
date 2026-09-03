import request from '@/config/axios'

// cc ivr API ivr流程
export const CcIvrApi = {
  // 查询cc ivr流程详情
  getDetail: async (id: number) => {
    return await request.get({ url: `/cc/flow-info/get?id=` + id })
  },

  // 修改cc ivr流程
  editIvr: async (data: object) => {
    return await request.put({ url: `/cc/flow-info/update`, data })
  },

  // 查询cc ivr流程分页(供坐席组表单"溢出IVR流程"下拉选择流程 ID)
  getPage: async (params: object) => {
    return await request.get({ url: '/cc/flow-info/page', params })
  },

}
