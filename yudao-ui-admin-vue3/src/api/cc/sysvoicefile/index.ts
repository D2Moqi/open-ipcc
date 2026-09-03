import request from '@/config/axios'

// cc 语音文件 VO
export interface SysVoiceFileVO {
  id: number // 主键id
  name: string // 文件名称
  type: number // 类型 1-手动上传 2-语音合成
  tts: number // tts方式 1-腾讯 2-阿里 3-讯飞(type=2生效)
  speechText: string // 合成文本
  fileId: number // 文件ID
}

// cc 语音文件 API
export const SysVoiceFileApi = {
  // 查询cc 语音文件分页
  getSysVoiceFilePage: async (params: any) => {
    return await request.get({ url: `/cc/sys-voice-file/page`, params })
  },

  // 查询cc 语音文件列表
  getSysVoiceFileList: async () => {
    return await request.get({ url: `/cc/sys-voice-file/list` })
  },

  // 查询cc 语音文件详情
  getSysVoiceFile: async (id: number) => {
    return await request.get({ url: `/cc/sys-voice-file/get?id=` + id })
  },

  // 新增cc 语音文件
  createSysVoiceFile: async (data: SysVoiceFileVO) => {
    return await request.post({ url: `/cc/sys-voice-file/create`, data })
  },

  // 修改cc 语音文件
  updateSysVoiceFile: async (data: SysVoiceFileVO) => {
    return await request.put({ url: `/cc/sys-voice-file/update`, data })
  },

  // 删除cc 语音文件
  deleteSysVoiceFile: async (id: number) => {
    return await request.delete({ url: `/cc/sys-voice-file/delete?id=` + id })
  },

  // 导出cc 语音文件 Excel
  exportSysVoiceFile: async (params) => {
    return await request.download({ url: `/cc/sys-voice-file/export-excel`, params })
  },
  // 批量删除cc 语音文件
  deleteSysVoiceFileList: async (ids: number[]) => {
    return await request.delete({ url: `/cc/sys-voice-file/delete-list?ids=${ids.join(',')}`})
  },
}
