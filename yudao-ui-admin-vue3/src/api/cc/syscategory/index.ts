import request from '@/config/axios'

// cc 分类配置 VO
export interface SysCategoryVO {
  id: number // 主键id
  type: number // 1-拨号计划
  name: string // 分类名称
  parentId: number // 父分类的id
  flag: number // 可删除标识 0 可删除 1 不可删除
}

// cc 分类配置 API
export const SysCategoryApi = {
  // 查询cc 分类配置分页
  getSysCategoryPage: async (params: any) => {
    return await request.get({ url: `/cc/sys-category/page`, params })
  },

  // 查询cc 分类配置详情
  getSysCategory: async (id: number) => {
    return await request.get({ url: `/cc/sys-category/get?id=` + id })
  },

  // 新增cc 分类配置
  createSysCategory: async (data: SysCategoryVO) => {
    return await request.post({ url: `/cc/sys-category/create`, data })
  },

  // 修改cc 分类配置
  updateSysCategory: async (data: SysCategoryVO) => {
    return await request.put({ url: `/cc/sys-category/update`, data })
  },

  // 删除cc 分类配置
  deleteSysCategory: async (id: number) => {
    return await request.delete({ url: `/cc/sys-category/delete?id=` + id })
  },

  // 导出cc 分类配置 Excel
  exportSysCategory: async (params) => {
    return await request.download({ url: `/cc/sys-category/export-excel`, params })
  }
}