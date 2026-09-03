import request from '@/config/axios'

// cc freeSwitch访问控制 VO
export interface FsAclVO {
  id: number // 主键id
  name: string // 名称
  listId: number // 列表ID
  type: string // 规则类型 allow-允许 deny-拒绝
  cidr: string // IP地址
  domain: string // 域地址
  remark: string // 备注
}

// cc freeSwitch访问控制 API
export const FsAclApi = {
  // 查询cc freeSwitch访问控制列表
  getFsAclList: async (params) => {
    return await request.get({ url: `/cc/fs-acl/list`, params })
  },

  // 查询cc freeSwitch访问控制详情
  getFsAcl: async (id: number) => {
    return await request.get({ url: `/cc/fs-acl/get?id=` + id })
  },

  // 新增cc freeSwitch访问控制
  createFsAcl: async (data: FsAclVO) => {
    return await request.post({ url: `/cc/fs-acl/create`, data })
  },

  // 修改cc freeSwitch访问控制
  updateFsAcl: async (data: FsAclVO) => {
    return await request.put({ url: `/cc/fs-acl/update`, data })
  },

  // 删除cc freeSwitch访问控制
  deleteFsAcl: async (id: number) => {
    return await request.delete({ url: `/cc/fs-acl/delete?id=` + id })
  },


  // 导出cc freeSwitch访问控制 Excel
  exportFsAcl: async (params) => {
    return await request.download({ url: `/cc/fs-acl/export-excel`, params })
  }
}
