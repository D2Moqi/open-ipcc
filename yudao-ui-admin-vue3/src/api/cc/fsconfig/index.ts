import request from '@/config/axios'

// cc freeSwitch管理配置 VO
export interface FsConfigVO {
  id: number // 主键id
  name: string // 名称
  group: string // 客户端分组
  ip: string // 机器地址IP
  port: number // 端口
  transportProtocol?: number // SIP传输协议：1-UDP，2-TCP（不配置则跟随入站腿协议）
  eslPort: number // esl端口
  password: string // 密码
  status: number // 状态 0-在线 1-下线
  outTime: number // 超时时间（秒）
}

// cc freeSwitch管理配置 API
export const FsConfigApi = {
  // 查询cc freeSwitch管理配置分页
  getFsConfigPage: async (params: any) => {
    return await request.get({ url: `/cc/fs-config/page`, params })
  },

  // 查询cc freeSwitch管理配置详情
  getFsConfig: async (id: number) => {
    return await request.get({ url: `/cc/fs-config/get?id=` + id })
  },

  // 新增cc freeSwitch管理配置
  createFsConfig: async (data: FsConfigVO) => {
    return await request.post({ url: `/cc/fs-config/create`, data })
  },

  // 修改cc freeSwitch管理配置
  updateFsConfig: async (data: FsConfigVO) => {
    return await request.put({ url: `/cc/fs-config/update`, data })
  },

  // 删除cc freeSwitch管理配置
  deleteFsConfig: async (id: number) => {
    return await request.delete({ url: `/cc/fs-config/delete?id=` + id })
  },

    // 批量删除cc freeSwitch管理配置
  deleteFsConfigList: async (ids: number[]) => {
    return await request.delete({ url: `/cc/fs-config/delete-list?ids=${ids.join(',')}`})
  },

  // 导出cc freeSwitch管理配置 Excel
  exportFsConfig: async (params) => {
    return await request.download({ url: `/cc/fs-config/export-excel`, params })
  },
}
