import request from '@/config/axios'

// cc 电话区号 VO
export interface AreaCodeVO {
  id: number // 主键id
  provinceName: string // 省份名称
  cityName: string // 城市名称
  provinceAdCode: number // 省份地域编码
  provinceCenter: string // 省份中心坐标
  cityCode: string // 城市区号
  cityAdCode: number // 城市地域编码
  cityCenter: string // 城市中心坐标
  districts: string // 区域映射
  isoCode: string // 省份国际ISO编码
}

// cc 电话区号 API
export const AreaCodeApi = {
  // 查询cc 电话区号分页
  getAreaCodePage: async (params: any) => {
    return await request.get({ url: `/cc/area-code/page`, params })
  },

  // 查询cc 电话区号详情
  getAreaCode: async (id: number) => {
    return await request.get({ url: `/cc/area-code/get?id=` + id })
  },

  // 新增cc 电话区号
  createAreaCode: async (data: AreaCodeVO) => {
    return await request.post({ url: `/cc/area-code/create`, data })
  },

  // 修改cc 电话区号
  updateAreaCode: async (data: AreaCodeVO) => {
    return await request.put({ url: `/cc/area-code/update`, data })
  },

  // 删除cc 电话区号
  deleteAreaCode: async (id: number) => {
    return await request.delete({ url: `/cc/area-code/delete?id=` + id })
  },

  // 导出cc 电话区号 Excel
  exportAreaCode: async (params) => {
    return await request.download({ url: `/cc/area-code/export-excel`, params })
  }
}