import request from '@/config/axios'

/** 自动外呼任务 VO */
export interface AutocallTaskVO {
  id?: number
  taskName: string
  targetNumbers: string
  gatewayId?: string
  ivrFlow?: string
  callerId?: string
  status: number
  priority?: number
  totalCount?: number
  successCount?: number
  failCount?: number
  variables?: string
  scheduleTime?: Date
  startTime?: Date
  endTime?: Date
  remark?: string
  createTime?: Date
}

/** 自动外呼任务记录 VO */
export interface AutocallTaskRecordVO {
  id: number
  taskId: number
  callId?: string
  targetNumber: string
  status: number
  callStartTime?: Date
  answerTime?: Date
  callEndTime?: Date
  hangupCause?: string
  dtmfCollected?: string
  duration?: number
  remark?: string
  createTime?: Date
}

/** 自动外呼任务 API */
export const AutocallTaskApi = {
  /** 查询外呼任务分页 */
  getAutocallTaskPage: async (params: any) => {
    return await request.get({ url: `/cc/autocall-task/page`, params })
  },

  /** 查询外呼任务详情 */
  getAutocallTask: async (id: number) => {
    return await request.get({ url: `/cc/autocall-task/get?id=` + id })
  },

  /** 新增外呼任务 */
  createAutocallTask: async (data: AutocallTaskVO) => {
    return await request.post({ url: `/cc/autocall-task/create`, data })
  },

  /** 修改外呼任务 */
  updateAutocallTask: async (data: AutocallTaskVO) => {
    return await request.put({ url: `/cc/autocall-task/update`, data })
  },

  /** 删除外呼任务 */
  deleteAutocallTask: async (id: number) => {
    return await request.delete({ url: `/cc/autocall-task/delete?id=` + id })
  },

  /** 批量删除外呼任务 */
  deleteAutocallTaskList: async (ids: number[]) => {
    return await request.delete({ url: `/cc/autocall-task/delete-list?ids=${ids.join(',')}` })
  },

  /** 导出外呼任务 Excel */
  exportAutocallTask: async (params: any) => {
    return await request.download({ url: `/cc/autocall-task/export-excel`, params })
  },

  /** 立即执行外呼任务 */
  executeAutocallTask: async (id: number) => {
    return await request.put({ url: `/cc/autocall-task/execute?id=` + id })
  },

  /** 暂停外呼任务 */
  pauseAutocallTask: async (id: number) => {
    return await request.put({ url: `/cc/autocall-task/pause?id=` + id })
  },

  /** 取消外呼任务 */
  cancelAutocallTask: async (id: number) => {
    return await request.put({ url: `/cc/autocall-task/cancel?id=` + id })
  },

  /** 刷新任务统计 */
  refreshTaskStats: async (id: number) => {
    return await request.put({ url: `/cc/autocall-task/refresh-stats?id=` + id })
  }
}

/** 自动外呼任务记录 API */
export const AutocallTaskRecordApi = {
  /** 查询任务记录分页 */
  getRecordPage: async (params: any) => {
    return await request.get({ url: `/cc/autocall-task-record/page`, params })
  },

  /** 查询任务记录详情 */
  getRecord: async (id: number) => {
    return await request.get({ url: `/cc/autocall-task-record/get?id=` + id })
  },

  /** 按任务ID查询所有记录(查看执行情况) */
  getListByTaskId: async (taskId: number) => {
    return await request.get({ url: `/cc/autocall-task-record/list-by-task?taskId=` + taskId })
  },

  /** 导出任务记录 Excel */
  exportRecord: async (params: any) => {
    return await request.download({ url: `/cc/autocall-task-record/export-excel`, params })
  }
}

/** 任务状态选项 */
export const TaskStatusOptions = [
  { label: '待执行', value: 0, tagType: 'info' },
  { label: '执行中', value: 1, tagType: 'warning' },
  { label: '已完成', value: 2, tagType: 'success' },
  { label: '已暂停', value: 3, tagType: 'danger' },
  { label: '已取消', value: 4, tagType: '' }
]

/** 记录状态选项 */
export const RecordStatusOptions = [
  { label: '待呼叫', value: 0, tagType: 'info' },
  { label: '呼叫中', value: 1, tagType: 'warning' },
  { label: '已接通', value: 2, tagType: 'success' },
  { label: '未接通', value: 3, tagType: 'danger' },
  { label: '呼叫失败', value: 4, tagType: 'danger' }
]
