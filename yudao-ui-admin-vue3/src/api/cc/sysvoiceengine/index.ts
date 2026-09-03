import request from '@/config/axios'

// cc 语音引擎 VO
export interface SysVoiceEngineVO {
  id: number // 主键id
  name: string // 名称
  type: number // 引擎类型 1-asr 2-tts
  manufacturerType: number // 引擎厂商 2-阿里
  appKey: string // appKey
  accessKeyId: string // 应用ID
  accessKeySecret: string // 应用密钥
  url: string // 接口地址
  voice: string // 音色
}

// cc 语音引擎 API
export const SysVoiceEngineApi = {
  // 查询cc 语音引擎分页
  getSysVoiceEnginePage: async (params: any) => {
    return await request.get({ url: `/cc/sys-voice-engine/page`, params })
  },

  // 查询cc 语音引擎详情
  getSysVoiceEngine: async (id: number) => {
    return await request.get({ url: `/cc/sys-voice-engine/get?id=` + id })
  },

  // 新增cc 语音引擎
  createSysVoiceEngine: async (data: SysVoiceEngineVO) => {
    return await request.post({ url: `/cc/sys-voice-engine/create`, data })
  },

  // 修改cc 语音引擎
  updateSysVoiceEngine: async (data: SysVoiceEngineVO) => {
    return await request.put({ url: `/cc/sys-voice-engine/update`, data })
  },

  // 删除cc 语音引擎
  deleteSysVoiceEngine: async (id: number) => {
    return await request.delete({ url: `/cc/sys-voice-engine/delete?id=` + id })
  },

    // 批量删除cc 语音引擎
  deleteSysVoiceEngineList: async (ids: number[]) => {
    return await request.delete({ url: `/cc/sys-voice-engine/delete-list?ids=${ids.join(',')}`})
  },

  // 导出cc 语音引擎 Excel
  exportSysVoiceEngine: async (params) => {
    return await request.download({ url: `/cc/sys-voice-engine/export-excel`, params })
  },
  // 查询cc 语音引擎列表
  list: async (params: any) => {
    return await request.get({ url: `/cc/sys-voice-engine/list`, params })
  },
}
