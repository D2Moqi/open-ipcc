<template>
  <ContentWrap>
    <!-- 搜索工作栏 -->
    <el-form
      class="-mb-15px"
      :model="queryParams"
      ref="queryFormRef"
      :inline="true"
      label-width="80px"
    >
      <el-form-item label="任务名称" prop="taskName">
        <el-input
          v-model="queryParams.taskName"
          placeholder="请输入任务名称"
          clearable
          @keyup.enter="handleQuery"
          class="!w-240px"
        />
      </el-form-item>
      <el-form-item label="任务状态" prop="status">
        <el-select
          v-model="queryParams.status"
          placeholder="请选择任务状态"
          clearable
          class="!w-240px"
        >
          <el-option
            v-for="item in TaskStatusOptions"
            :key="item.value"
            :label="item.label"
            :value="item.value"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="计划时间" prop="scheduleTime">
        <el-date-picker
          v-model="queryParams.scheduleTime"
          value-format="YYYY-MM-DD HH:mm:ss"
          type="datetimerange"
          start-placeholder="开始时间"
          end-placeholder="结束时间"
          class="!w-240px"
        />
      </el-form-item>
      <el-form-item>
        <el-button @click="handleQuery"><Icon icon="ep:search" class="mr-5px" /> 搜索</el-button>
        <el-button @click="resetQuery"><Icon icon="ep:refresh" class="mr-5px" /> 重置</el-button>
        <el-button
          type="primary"
          plain
          @click="openForm('create')"
          v-hasPermi="['cc:autocall-task:create']"
        >
          <Icon icon="ep:plus" class="mr-5px" /> 新增任务
        </el-button>
        <el-button
          type="success"
          plain
          @click="handleExport"
          :loading="exportLoading"
          v-hasPermi="['cc:autocall-task:export']"
        >
          <Icon icon="ep:download" class="mr-5px" /> 导出
        </el-button>
      </el-form-item>
    </el-form>
  </ContentWrap>

  <!-- 列表 -->
  <ContentWrap>
    <el-table
      v-loading="loading"
      :data="list"
      :stripe="true"
      :show-overflow-tooltip="true"
    >
      <el-table-column label="任务ID" align="center" prop="id" width="80" />
      <el-table-column label="任务名称" align="center" prop="taskName" min-width="150" />
      <el-table-column label="被叫号码" align="center" prop="targetNumbers" min-width="200" show-overflow-tooltip />
      <el-table-column label="网关ID" align="center" prop="gatewayId" width="100" />
      <el-table-column label="IVR流程" align="center" prop="ivrFlow" width="180" show-overflow-tooltip>
        <template #default="scope">
          {{ getIvrFlowName(scope.row.ivrFlow) }}
        </template>
      </el-table-column>
      <el-table-column label="主叫号码" align="center" prop="callerId" width="120" />
      <el-table-column label="状态" align="center" prop="status" width="100">
        <template #default="scope">
          <el-tag :type="getTaskStatusTag(scope.row.status)">
            {{ getTaskStatusText(scope.row.status) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="进度" align="center" width="160">
        <template #default="scope">
          <div class="progress-cell">
            <el-progress
              :percentage="getProgress(scope.row)"
              :status="getProgressStatus(scope.row)"
            />
            <span class="progress-text">
              {{ scope.row.successCount }}/{{ scope.row.totalCount }}
              <span v-if="scope.row.failCount > 0" class="fail-count">(失败{{ scope.row.failCount }})</span>
            </span>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="计划时间" align="center" prop="scheduleTime" width="160">
        <template #default="scope">
          {{ scope.row.scheduleTime ? formatDate(scope.row.scheduleTime) : '立即执行' }}
        </template>
      </el-table-column>
      <el-table-column label="创建时间" align="center" prop="createTime" width="160">
        <template #default="scope">
          {{ formatDate(scope.row.createTime) }}
        </template>
      </el-table-column>
      <el-table-column label="操作" align="center" min-width="280px" fixed="right">
        <template #default="scope">
          <el-button
            link
            type="primary"
            @click="openForm('update', scope.row.id)"
            v-hasPermi="['cc:autocall-task:update']"
            :disabled="scope.row.status !== 0"
          >
            编辑
          </el-button>
          <el-button
            link
            type="success"
            @click="handleExecute(scope.row.id)"
            v-hasPermi="['cc:autocall-task:execute']"
            :disabled="scope.row.status !== 0 && scope.row.status !== 3"
          >
            执行
          </el-button>
          <el-button
            link
            type="warning"
            @click="handlePause(scope.row.id)"
            v-hasPermi="['cc:autocall-task:update']"
            :disabled="scope.row.status !== 1"
          >
            暂停
          </el-button>
          <el-button
            link
            type="danger"
            @click="handleCancel(scope.row.id)"
            v-hasPermi="['cc:autocall-task:update']"
            :disabled="scope.row.status === 2 || scope.row.status === 4"
          >
            取消
          </el-button>
          <el-button
            link
            type="info"
            @click="handleViewRecords(scope.row.id)"
            v-hasPermi="['cc:autocall-task:query']"
          >
            记录
          </el-button>
          <el-button
            link
            type="danger"
            @click="handleDelete(scope.row.id)"
            v-hasPermi="['cc:autocall-task:delete']"
            :disabled="scope.row.status === 1"
          >
            删除
          </el-button>
        </template>
      </el-table-column>
    </el-table>
    <!-- 分页 -->
    <Pagination
      :total="total"
      v-model:page="queryParams.pageNo"
      v-model:limit="queryParams.pageSize"
      @pagination="getList"
    />
  </ContentWrap>

  <!-- 表单弹窗：添加/修改 -->
  <AutocallTaskForm ref="formRef" @success="getList" />

  <!-- 任务记录弹窗 -->
  <AutocallTaskRecordDialog ref="recordDialogRef" />
</template>

<script setup lang="ts">
import { dateFormatter } from '@/utils/formatTime'
import download from '@/utils/download'
import { AutocallTaskApi, AutocallTaskVO, TaskStatusOptions } from '@/api/cc/autocalltask'
import { CallRouteApi } from '@/api/cc/callroute'
import AutocallTaskForm from './AutocallTaskForm.vue'
import AutocallTaskRecordDialog from './AutocallTaskRecordDialog.vue'

/** 自动外呼任务 列表 */
defineOptions({ name: 'AutocallTask' })

const message = useMessage() // 消息弹窗
const { t } = useI18n() // 国际化

const loading = ref(true) // 列表的加载中
const list = ref<AutocallTaskVO[]>([]) // 列表的数据
const total = ref(0) // 列表的总页数
const ivrFlowMap = ref<Map<string, string>>(new Map()) // IVR流程映射: id -> 路由名称(路由号码)
const queryParams = reactive({
  pageNo: 1,
  pageSize: 10,
  taskName: undefined,
  status: undefined,
  scheduleTime: undefined as any
})
const queryFormRef = ref() // 搜索的表单
const exportLoading = ref(false) // 导出的加载中

/** 格式化日期(简化版,兼容字符串和Date) */
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

/**
 * 根据 IVR 流程 id 查找对应的名称展示
 * @param ivrFlow ivrFlow 字段值（号码路由 id 字符串）
 * @return 路由名称(路由号码) 格式的展示文本；为空或未匹配返回 '-'
 */
const getIvrFlowName = (ivrFlow?: string): string => {
  if (!ivrFlow) return '-'
  return ivrFlowMap.value.get(String(ivrFlow)) || '-'
}

/**
 * 加载号码路由列表（仅呼出方向）并构建 IVR 流程 id -> 名称映射
 * 数据来源：号码路由管理中 type=2 的记录
 */
const loadIvrFlowMap = async () => {
  try {
    const data = await CallRouteApi.list()
    const map = new Map<string, string>()
    ;(data || [])
      .filter((item: any) => item.type === 2)
      .forEach((item: any) => {
        const label = item.name ? `${item.name}(${item.routeNum || '-'})` : item.routeNum
        map.set(String(item.id), label)
      })
    ivrFlowMap.value = map
  } catch {
    ivrFlowMap.value = new Map()
  }
}

/** 计算任务进度百分比 */
const getProgress = (row: AutocallTaskVO): number => {
  if (!row.totalCount || row.totalCount === 0) return 0
  const finished = (row.successCount || 0) + (row.failCount || 0)
  return Math.round((finished / row.totalCount) * 100)
}

/** 获取进度条状态 */
const getProgressStatus = (row: AutocallTaskVO): any => {
  if (row.status === 2) return 'success'
  if (row.status === 4) return 'exception'
  return undefined
}

/** 查询列表 */
const getList = async () => {
  loading.value = true
  try {
    const data = await AutocallTaskApi.getAutocallTaskPage(queryParams)
    list.value = data.list
    total.value = data.total
  } finally {
    loading.value = false
  }
}

/** 搜索按钮操作 */
const handleQuery = () => {
  queryParams.pageNo = 1
  getList()
}

/** 重置按钮操作 */
const resetQuery = () => {
  queryFormRef.value.resetFields()
  handleQuery()
}

/** 添加/修改操作 */
const formRef = ref()
const openForm = (type: string, id?: number) => {
  formRef.value.open(type, id)
}

/** 删除按钮操作 */
const handleDelete = async (id: number) => {
  try {
    await message.delConfirm()
    await AutocallTaskApi.deleteAutocallTask(id)
    message.success(t('common.delSuccess'))
    await getList()
  } catch {}
}

/** 立即执行任务 */
const handleExecute = async (id: number) => {
  try {
    await message.confirm('确认立即执行此外呼任务？将拆分号码并逐个发起ESL外呼。')
    await AutocallTaskApi.executeAutocallTask(id)
    message.success('任务已开始执行')
    await getList()
  } catch {}
}

/** 暂停任务 */
const handlePause = async (id: number) => {
  try {
    await message.confirm('确认暂停此外呼任务？已发起的外呼不受影响，仅停止后续号码发起。')
    await AutocallTaskApi.pauseAutocallTask(id)
    message.success('任务已暂停')
    await getList()
  } catch {}
}

/** 取消任务 */
const handleCancel = async (id: number) => {
  try {
    await message.confirm('确认取消此外呼任务？取消后不可恢复。')
    await AutocallTaskApi.cancelAutocallTask(id)
    message.success('任务已取消')
    await getList()
  } catch {}
}

/** 查看任务记录 */
const recordDialogRef = ref()
const handleViewRecords = (taskId: number) => {
  recordDialogRef.value.open(taskId)
}

/** 导出按钮操作 */
const handleExport = async () => {
  try {
    await message.exportConfirm()
    exportLoading.value = true
    const data = await AutocallTaskApi.exportAutocallTask(queryParams)
    download.excel(data, '自动外呼任务.xls')
  } catch {
  } finally {
    exportLoading.value = false
  }
}

/** 初始化 */
onMounted(async () => {
  await loadIvrFlowMap()
  await getList()
})
</script>

<style scoped>
.progress-cell {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
}

.progress-text {
  font-size: 12px;
  color: #909399;
}

.fail-count {
  color: #f56c6c;
}
</style>
