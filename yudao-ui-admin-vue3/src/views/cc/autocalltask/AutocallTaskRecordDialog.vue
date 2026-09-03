<template>
  <Dialog
    title="外呼任务执行记录"
    v-model="dialogVisible"
    width="1100px"
    :scroll="true"
    max-height="600px"
    append-to-body
  >
    <!-- 任务统计概览 -->
    <div class="stats-overview" v-if="taskInfo">
      <el-descriptions :column="4" border size="small">
        <el-descriptions-item label="任务名称">{{ taskInfo.taskName }}</el-descriptions-item>
        <el-descriptions-item label="状态">
          <el-tag :type="getTaskStatusTag(taskInfo.status)">
            {{ getTaskStatusText(taskInfo.status) }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="总数">{{ taskInfo.totalCount || 0 }}</el-descriptions-item>
        <el-descriptions-item label="成功">
          <span class="success-text">{{ taskInfo.successCount || 0 }}</span>
        </el-descriptions-item>
        <el-descriptions-item label="失败">
          <span class="fail-text">{{ taskInfo.failCount || 0 }}</span>
        </el-descriptions-item>
        <el-descriptions-item label="待呼叫">{{ pendingCount }}</el-descriptions-item>
        <el-descriptions-item label="开始时间">
          {{ taskInfo.startTime ? formatDate(taskInfo.startTime) : '-' }}
        </el-descriptions-item>
        <el-descriptions-item label="结束时间">
          {{ taskInfo.endTime ? formatDate(taskInfo.endTime) : '-' }}
        </el-descriptions-item>
      </el-descriptions>
    </div>

    <!-- 搜索 -->
    <el-form class="record-search -mb-15px" :inline="true" :model="queryParams" style="margin-top: 16px">
      <el-form-item label="被叫号码" prop="targetNumber">
        <el-input
          v-model="queryParams.targetNumber"
          placeholder="请输入被叫号码"
          clearable
          @keyup.enter="handleQuery"
          class="!w-200px"
        />
      </el-form-item>
      <el-form-item label="呼叫状态" prop="status">
        <el-select
          v-model="queryParams.status"
          placeholder="请选择呼叫状态"
          clearable
          class="!w-200px"
        >
          <el-option
            v-for="item in RecordStatusOptions"
            :key="item.value"
            :label="item.label"
            :value="item.value"
          />
        </el-select>
      </el-form-item>
      <el-form-item>
        <el-button @click="handleQuery"><Icon icon="ep:search" class="mr-5px" /> 搜索</el-button>
        <el-button @click="resetQuery"><Icon icon="ep:refresh" class="mr-5px" /> 重置</el-button>
        <el-button type="primary" plain @click="handleRefreshStats" :loading="refreshLoading">
          <Icon icon="ep:refresh-right" class="mr-5px" /> 刷新统计
        </el-button>
        <el-button type="success" plain @click="handleExport">
          <Icon icon="ep:download" class="mr-5px" /> 导出
        </el-button>
      </el-form-item>
    </el-form>

    <!-- 记录列表 -->
    <el-table
      v-loading="loading"
      :data="list"
      :stripe="true"
      :show-overflow-tooltip="true"
      style="margin-top: 12px"
    >
      <el-table-column label="记录ID" align="center" prop="id" width="80" />
      <el-table-column label="被叫号码" align="center" prop="targetNumber" width="130" />
      <el-table-column label="呼叫状态" align="center" prop="status" width="100">
        <template #default="scope">
          <el-tag :type="getRecordStatusTag(scope.row.status)">
            {{ getRecordStatusText(scope.row.status) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="通话记录ID" align="center" prop="callId" width="140" show-overflow-tooltip />
      <el-table-column label="呼叫开始时间" align="center" prop="callStartTime" width="160">
        <template #default="scope">
          {{ scope.row.callStartTime ? formatDate(scope.row.callStartTime) : '-' }}
        </template>
      </el-table-column>
      <el-table-column label="接通时间" align="center" prop="answerTime" width="160">
        <template #default="scope">
          {{ scope.row.answerTime ? formatDate(scope.row.answerTime) : '-' }}
        </template>
      </el-table-column>
      <el-table-column label="结束时间" align="center" prop="callEndTime" width="160">
        <template #default="scope">
          {{ scope.row.callEndTime ? formatDate(scope.row.callEndTime) : '-' }}
        </template>
      </el-table-column>
      <el-table-column label="通话时长(秒)" align="center" prop="duration" width="100">
        <template #default="scope">
          {{ scope.row.duration != null ? scope.row.duration : '-' }}
        </template>
      </el-table-column>
      <el-table-column label="挂断原因" align="center" prop="hangupCause" width="140" show-overflow-tooltip />
      <el-table-column label="IVR按键" align="center" prop="dtmfCollected" width="100" show-overflow-tooltip />
    </el-table>

    <!-- 分页 -->
    <Pagination
      :total="total"
      v-model:page="queryParams.pageNo"
      v-model:limit="queryParams.pageSize"
      @pagination="getList"
    />
  </Dialog>
</template>

<script setup lang="ts">
import { dateFormatter } from '@/utils/formatTime'
import download from '@/utils/download'
import {
  AutocallTaskApi,
  AutocallTaskRecordApi,
  AutocallTaskVO,
  TaskStatusOptions,
  RecordStatusOptions
} from '@/api/cc/autocalltask'

/** 自动外呼任务记录 弹窗 */
defineOptions({ name: 'AutocallTaskRecordDialog' })

const message = useMessage()

const dialogVisible = ref(false)
const loading = ref(false)
const refreshLoading = ref(false)
const taskId = ref<number>(0)
const taskInfo = ref<AutocallTaskVO | null>(null)
const list = ref<any[]>([])
const total = ref(0)
const queryParams = reactive({
  pageNo: 1,
  pageSize: 10,
  taskId: undefined as number | undefined,
  targetNumber: undefined as string | undefined,
  status: undefined as number | undefined
})

/** 格式化日期 */
const formatDate = (date: any) => {
  if (!date) return ''
  return dateFormatter(null, null, date)
}

/** 获取任务状态文本 */
const getTaskStatusText = (status: number): string => {
  const item = TaskStatusOptions.find((o) => o.value === status)
  return item ? item.label : '未知'
}

/** 获取任务状态标签类型 */
const getTaskStatusTag = (status: number): any => {
  const item = TaskStatusOptions.find((o) => o.value === status)
  return item ? item.tagType : ''
}

/** 获取记录状态文本 */
const getRecordStatusText = (status: number): string => {
  const item = RecordStatusOptions.find((o) => o.value === status)
  return item ? item.label : '未知'
}

/** 获取记录状态标签类型 */
const getRecordStatusTag = (status: number): any => {
  const item = RecordStatusOptions.find((o) => o.value === status)
  return item ? item.tagType : ''
}

/** 待呼叫数(计算属性) */
const pendingCount = computed(() => {
  if (!taskInfo.value || !taskInfo.value.totalCount) return 0
  const total = taskInfo.value.totalCount
  const success = taskInfo.value.successCount || 0
  const fail = taskInfo.value.failCount || 0
  return total - success - fail
})

/** 打开弹窗 */
const open = async (id: number) => {
  dialogVisible.value = true
  taskId.value = id
  queryParams.taskId = id
  queryParams.pageNo = 1
  queryParams.targetNumber = undefined
  queryParams.status = undefined
  await Promise.all([loadTaskInfo(), getList()])
}
defineExpose({ open })

/** 加载任务详情 */
const loadTaskInfo = async () => {
  try {
    taskInfo.value = await AutocallTaskApi.getAutocallTask(taskId.value)
  } catch {
    taskInfo.value = null
  }
}

/** 查询记录列表 */
const getList = async () => {
  loading.value = true
  try {
    const data = await AutocallTaskRecordApi.getRecordPage(queryParams)
    list.value = data.list
    total.value = data.total
  } finally {
    loading.value = false
  }
}

/** 搜索 */
const handleQuery = () => {
  queryParams.pageNo = 1
  getList()
}

/** 重置 */
const resetQuery = () => {
  queryParams.targetNumber = undefined
  queryParams.status = undefined
  handleQuery()
}

/** 刷新任务统计 */
const handleRefreshStats = async () => {
  refreshLoading.value = true
  try {
    await AutocallTaskApi.refreshTaskStats(taskId.value)
    message.success('统计已刷新')
    await loadTaskInfo()
    await getList()
  } finally {
    refreshLoading.value = false
  }
}

/** 导出 */
const handleExport = async () => {
  try {
    await message.exportConfirm()
    const data = await AutocallTaskRecordApi.exportRecord(queryParams)
    download.excel(data, '外呼任务记录.xls')
  } catch {}
}
</script>

<style scoped>
.stats-overview {
  margin-bottom: 8px;
}

.success-text {
  color: #67c23a;
  font-weight: bold;
}

.fail-text {
  color: #f56c6c;
  font-weight: bold;
}
</style>
