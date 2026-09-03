import request from '@/config/axios'

// cc 电话归属地 VO
export interface PhoneLocationVO {
  id: number // 主键id
  pref: string // 号段前缀
  phone: string // 手机号
  province: string // 省份
  city: string // 城市
  isp: string // 运营商类型名称
  ispType: number // 运营商类型 1：移动 2：联通 3：电信 4：广电 5：工信
  postCode: string // 邮编
  cityCode: string // 区号
  areaCode: string // 行政区划编码
}

// cc 电话归属地 API
export const PhoneLocationApi = {
  // 查询cc 电话归属地分页
  getPhoneLocationPage: async (params: any) => {
    return await request.get({ url: `/cc/sys-phone-location/page`, params })
  },

  // 查询cc 电话归属地详情
  getPhoneLocation: async (id: number) => {
    return await request.get({ url: `/cc/sys-phone-location/get?id=` + id })
  },

  // 新增cc 电话归属地
  createPhoneLocation: async (data: PhoneLocationVO) => {
    return await request.post({ url: `/cc/sys-phone-location/create`, data })
  },

  // 修改cc 电话归属地
  updatePhoneLocation: async (data: PhoneLocationVO) => {
    return await request.put({ url: `/cc/sys-phone-location/update`, data })
  },

  // 删除cc 电话归属地
  deletePhoneLocation: async (id: number) => {
    return await request.delete({ url: `/cc/sys-phone-location/delete?id=` + id })
  },

  // 导出cc 电话归属地 Excel
  exportPhoneLocation: async (params) => {
    return await request.download({ url: `/cc/sys-phone-location/export-excel`, params })
  }
}
