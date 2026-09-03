import request from '@/config/axios'

// cc 号码路由 VO
export interface CallRouteVO {
  id: number // 主键id
  name: string // 路由名称
  routeNum: string // 路由号码
  deletePrefix?: string // 删除前缀：匹配成功后从被叫号码中去除的前缀
  type: number // 路由类型 1-呼入 2-呼出
  level: number // 路由优先级
  status: number // 状态  0-未启用 1-启用
  scheduleId: number // 日程ID
  routeType: number // 路由类型 1-坐席 2-外呼 3-sip 4-坐席组 5-放音 6-ivr
  routeValue: string // 路由类型值
}

// cc 号码路由 API
export const CallRouteApi = {
  // 查询cc 号码路由分页
  getCallRoutePage: async (params: any) => {
    return await request.get({ url: `/cc/call-route/page`, params })
  },

  // 查询cc 号码路由详情
  getCallRoute: async (id: number) => {
    return await request.get({ url: `/cc/call-route/get?id=` + id })
  },

  // 新增cc 号码路由
  createCallRoute: async (data: CallRouteVO) => {
    return await request.post({ url: `/cc/call-route/create`, data })
  },

  // 修改cc 号码路由
  updateCallRoute: async (data: CallRouteVO) => {
    return await request.put({ url: `/cc/call-route/update`, data })
  },

  // 删除cc 号码路由
  deleteCallRoute: async (id: number) => {
    return await request.delete({ url: `/cc/call-route/delete?id=` + id })
  },

  // 导出cc 号码路由 Excel
  exportCallRoute: async (params) => {
    return await request.download({ url: `/cc/call-route/export-excel`, params })
  },
  // 批量删除cc 号码路由
  deleteCallRouteList: async (ids: number[]) => {
    return await request.delete({ url: `/cc/call-route/delete-list?ids=${ids.join(',')}` })
  },
  // 查询cc 号码路由列表
  list: async () => {
    return await request.get({ url: `/cc/call-route/list` })
  }
}
