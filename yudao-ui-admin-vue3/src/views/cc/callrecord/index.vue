<template>
  <ContentWrap>
    <!-- 搜索工作栏 -->
    <el-form
      class="-mb-15px"
      :model="queryParams"
      ref="queryFormRef"
      :inline="true"
      label-width="100px"
    >
      <el-form-item label="呼叫唯一ID" prop="callId">
        <el-input
          v-model="queryParams.callId"
          placeholder="请输入呼叫唯一ID"
          clearable
          @keyup.enter="handleQuery"
          class="!w-240px"
        />
      </el-form-item>
      <el-form-item label="主叫号码" prop="callerNumber">
        <el-input
          v-model="queryParams.callerNumber"
          placeholder="请输入主叫号码"
          clearable
          @keyup.enter="handleQuery"
          class="!w-240px"
        />
      </el-form-item>
      <el-form-item label="被叫号码" prop="calleeNumber">
        <el-input
          v-model="queryParams.calleeNumber"
          placeholder="请输入被叫号码"
          clearable
          @keyup.enter="handleQuery"
          class="!w-240px"
        />
      </el-form-item>
      <el-form-item label="呼叫开始时间" prop="callStartTime">
        <el-date-picker
          v-model="queryParams.callStartTime"
          value-format="YYYY-MM-DD HH:mm:ss"
          type="daterange"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          :default-time="[new Date('1 00:00:00'), new Date('1 23:59:59')]"
          class="!w-220px"
        />
      </el-form-item>
      <el-form-item label="呼叫结束时间" prop="callEndTime">
        <el-date-picker
          v-model="queryParams.callEndTime"
          value-format="YYYY-MM-DD HH:mm:ss"
          type="daterange"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          :default-time="[new Date('1 00:00:00'), new Date('1 23:59:59')]"
          class="!w-220px"
        />
      </el-form-item>
      <el-form-item>
        <el-button @click="handleQuery"><Icon icon="ep:search" class="mr-5px" /> 搜索</el-button>
        <el-button @click="resetQuery"><Icon icon="ep:refresh" class="mr-5px" /> 重置</el-button>
        <el-button
          type="success"
          plain
          @click="handleExport"
          :loading="exportLoading"
          v-hasPermi="['cc:call-record:export']"
        >
          <Icon icon="ep:download" class="mr-5px" /> 导出
        </el-button>
      </el-form-item>
    </el-form>
  </ContentWrap>

  <!-- 列表 -->
  <ContentWrap>
    <el-table
        row-key="id"
        v-loading="loading"
        :data="list"
        :stripe="true"
        :show-overflow-tooltip="true"
        @selection-change="handleRowCheckboxChange"
    >
    <el-table-column type="selection" width="55" />
      <el-table-column label="呼叫唯一ID" align="center" prop="callId" width="100" />
      <el-table-column label="主叫号码" align="center" prop="callerNumber" />
      <el-table-column label="主叫显号" align="center" prop="callerDisplayNumber" />
      <el-table-column label="被叫号码" align="center" prop="calleeNumber" />
      <el-table-column label="被叫显号" align="center" prop="calleeDisplayNumber" />
      <el-table-column label="号码归属地" align="center" prop="numberLocation" width="100" />
      <el-table-column label="坐席号码" align="center" prop="agentNumber" />
      <el-table-column label="坐席名称" align="center" prop="agentName" />
      <el-table-column label="呼叫状态" align="center" prop="callState" >
        <template #default="scope">
          <dict-tag :type="DICT_TYPE.CC_CALL_STATE" :value="scope.row.callState" />
        </template>
      </el-table-column>
      <el-table-column label="呼叫方式" align="center" prop="direction" >
        <template #default="scope">
          <dict-tag :type="DICT_TYPE.CC_CALL_DIRECTION" :value="scope.row.direction" />
        </template>
      </el-table-column>
      <el-table-column
        label="呼叫开始时间"
        align="center"
        prop="callStartTime"
        :formatter="dateFormatter"
        width="180px"
      />
      <el-table-column
        label="呼叫结束时间"
        align="center"
        prop="callEndTime"
        :formatter="dateFormatter"
        width="180px"
      />
      <el-table-column label="应答标识" align="center" prop="answerFlag" >
        <template #default="scope">
          <dict-tag :type="DICT_TYPE.CC_CALL_ANSWER_FLAG" :value="scope.row.answerFlag" />
        </template>
      </el-table-column>
      <el-table-column
        label="呼叫接通时间"
        align="center"
        prop="answerTime"
        :formatter="dateFormatter"
        width="180px"
      />
      <el-table-column
        label="振铃时间"
        align="center"
        prop="ringingTime"
        :formatter="dateFormatter"
        width="180px"
      /> <el-table-column
      label="创建时间"
      align="center"
      prop="createTime"
      :formatter="dateFormatter"
      width="180px"
    />
      <el-table-column label="操作" align="center" min-width="120px">
        <template #default="scope">
          <el-button
            link
            type="primary"
            @click="openForm('detail', scope.row.id)"
            v-hasPermi="['cc:call-record:query']"
          >
            查看
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
  <CallRecordForm ref="formRef" @success="getList" />
</template>

<script setup lang="ts">
import { dateFormatter } from '@/utils/formatTime'
import download from '@/utils/download'
import { CallRecordApi, CallRecordVO } from '@/api/cc/callrecord'
import CallRecordForm from './CallRecordForm.vue'
import { DICT_TYPE } from '@/utils/dict'

/** cc 呼叫记录 列表 */
defineOptions({ name: 'CallRecord' })

const message = useMessage() // 消息弹窗

const loading = ref(true) // 列表的加载中
const list = ref<CallRecordVO[]>([]) // 列表的数据
const total = ref(0) // 列表的总页数
const queryParams = reactive({
  pageNo: 1,
  pageSize: 10,
  createTime: [],
  callId: undefined,
  callerNumber: undefined,
  callerDisplayNumber: undefined,
  calleeNumber: undefined,
  calleeDisplayNumber: undefined,
  numberLocation: undefined,
  agentId: undefined,
  agentNumber: undefined,
  agentName: undefined,
  callState: undefined,
  direction: undefined,
  callStartTime: [],
  callEndTime: [],
  answerFlag: undefined,
  answerTime: [],
  ringingTime: [],
  hangupDir: undefined,
  hangupCauseCode: undefined,
  filePath: undefined,
  ringingPath: undefined
})
const queryFormRef = ref() // 搜索的表单
const exportLoading = ref(false) // 导出的加载中

/** 查询列表 */
const getList = async () => {
  loading.value = true
  try {
    const data = await CallRecordApi.getCallRecordPage(queryParams)
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

const checkedIds = ref<number[]>([])
const handleRowCheckboxChange = (records: CallRecordVO[]) => {
  checkedIds.value = records.map((item) => item.id);
}

/** 导出按钮操作 */
const handleExport = async () => {
  try {
    // 导出的二次确认
    await message.exportConfirm()
    // 发起导出
    exportLoading.value = true
    const data = await CallRecordApi.exportCallRecord(queryParams)
    download.excel(data, 'cc 呼叫记录.xls')
  } catch {
  } finally {
    exportLoading.value = false
  }
}

/** 初始化 **/
onMounted(() => {
  getList()
})
</script>
