import request from '@/config/axios'

// cc 呼叫记录 VO
export interface CallRecordVO {
  id: number // 主键id
  callId: string // 呼叫唯一ID
  callerNumber: string // 主叫号码
  callerDisplayNumber: string // 主叫显号
  calleeNumber: string // 被叫号码
  calleeDisplayNumber: string // 被叫显号
  numberLocation: string // 号码归属地
  agentId: number // 坐席ID
  agentNumber: string // 坐席号码
  agentName: string // 坐席名称
  callState: number // 呼叫状态 1-成功 2-失败
  direction: number // 呼叫方式 1-呼出 2-呼入
  callStartTime: Date // 呼叫开始时间
  callEndTime: Date // 呼叫结束时间
  answerFlag: number // 应答标识 0-接通 1-坐席未接用户未接 2-坐席接通用户未接通 3-用户接通坐席未接通
  answerTime: Date // 呼叫接通时间
  ringingTime: Date // 振铃时间
  hangupDir: number // 挂机方向 1-主叫挂机 2-被叫挂机 3-系统挂机
  hangupCauseCode: number // 挂机原因
  filePath: string // 录音文件地址
  ringingPath: string // 振铃文件地址
}

// cc 呼叫记录 API
export const CallRecordApi = {
  // 查询cc 呼叫记录分页
  getCallRecordPage: async (params: any) => {
    return await request.get({ url: `/cc/call-record/page`, params })
  },

  // 查询cc 呼叫记录详情
  getCallRecord: async (id: number) => {
    return await request.get({ url: `/cc/call-record/get?id=` + id })
  },

  // 新增cc 呼叫记录
  createCallRecord: async (data: CallRecordVO) => {
    return await request.post({ url: `/cc/call-record/create`, data })
  },

  // 修改cc 呼叫记录
  updateCallRecord: async (data: CallRecordVO) => {
    return await request.put({ url: `/cc/call-record/update`, data })
  },

  // 删除cc 呼叫记录
  deleteCallRecord: async (id: number) => {
    return await request.delete({ url: `/cc/call-record/delete?id=` + id })
  },

  // 导出cc 呼叫记录 Excel
  exportCallRecord: async (params) => {
    return await request.download({ url: `/cc/call-record/export-excel`, params })
  }
}
