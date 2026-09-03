import request from '@/config/axios'

// cc freeSwitch拨号计划 VO
export interface FsDialplanVO {
  id: number // 主键id
  name: string // 计划名称
  type: string // 类型 xml格式,json格式
  contextName: string // 内容类型 public、default
  content: string // 内容
  describe: string // 描述
}

// cc freeSwitch拨号计划 API
export const FsDialplanApi = {
  // 查询cc freeSwitch拨号计划分页
  getFsDialplanPage: async (params: any) => {
    return await request.get({ url: `/cc/fs-dialplan/page`, params })
  },

  // 查询cc freeSwitch拨号计划详情
  getFsDialplan: async (id: number) => {
    return await request.get({ url: `/cc/fs-dialplan/get?id=` + id })
  },

  // 新增cc freeSwitch拨号计划
  createFsDialplan: async (data: FsDialplanVO) => {
    return await request.post({ url: `/cc/fs-dialplan/create`, data })
  },

  // 修改cc freeSwitch拨号计划
  updateFsDialplan: async (data: FsDialplanVO) => {
    return await request.put({ url: `/cc/fs-dialplan/update`, data })
  },

  // 删除cc freeSwitch拨号计划
  deleteFsDialplan: async (id: number) => {
    return await request.delete({ url: `/cc/fs-dialplan/delete?id=` + id })
  },

    // 批量删除cc freeSwitch拨号计划
  deleteFsDialplanList: async (ids: number[]) => {
    return await request.delete({ url: `/cc/fs-dialplan/delete-list?ids=${ids.join(',')}`})
  },

  // 导出cc freeSwitch拨号计划 Excel
  exportFsDialplan: async (params) => {
    return await request.download({ url: `/cc/fs-dialplan/export-excel`, params })
  },
}
