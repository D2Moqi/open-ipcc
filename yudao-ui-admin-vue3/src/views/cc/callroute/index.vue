<template>
  <ContentWrap>
    <!-- 搜索工作栏 -->
    <el-form
      class="-mb-15px"
      :model="queryParams"
      ref="queryFormRef"
      :inline="true"
      label-width="68px"
    >
      <el-form-item label="路由名称" prop="name">
        <el-input
          v-model="queryParams.name"
          placeholder="请输入路由名称"
          clearable
          @keyup.enter="handleQuery"
          class="!w-240px"
        />
      </el-form-item>
      <el-form-item label="路由号码" prop="routeNum">
        <el-input
          v-model="queryParams.routeNum"
          placeholder="请输入路由号码"
          clearable
          @keyup.enter="handleQuery"
          class="!w-240px"
        />
      </el-form-item>
      <el-form-item label="路由方向" prop="type">
        <el-select
          v-model="queryParams.type"
          placeholder="请选择路由方向"
          clearable
          class="!w-240px"
        >
          <el-option
            v-for="dict in getIntDictOptions(DICT_TYPE.CC_CALL_ROUTE_DIRECTION_TYPE)"
            :key="dict.value"
            :label="dict.label"
            :value="dict.value"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="启用状态" prop="status">
        <el-select
          v-model="queryParams.status"
          placeholder="请选择启用状态"
          clearable
          class="!w-240px"
        >
          <el-option
            v-for="dict in getIntDictOptions(DICT_TYPE.CC_CALL_ROUTE_STATUS)"
            :key="dict.value"
            :label="dict.label"
            :value="dict.value"
          />
        </el-select>
      </el-form-item>
      <el-form-item>
        <el-button @click="handleQuery"><Icon icon="ep:search" class="mr-5px" /> 搜索</el-button>
        <el-button @click="resetQuery"><Icon icon="ep:refresh" class="mr-5px" /> 重置</el-button>
        <el-button
          type="primary"
          plain
          @click="openForm('create')"
          v-hasPermi="['cc:call-route:create']"
        >
          <Icon icon="ep:plus" class="mr-5px" /> 新增
        </el-button>
        <el-button
          type="success"
          plain
          @click="handleExport"
          :loading="exportLoading"
          v-hasPermi="['cc:call-route:export']"
        >
          <Icon icon="ep:download" class="mr-5px" /> 导出
        </el-button>
        <el-button
            type="danger"
            plain
            :disabled="isEmpty(checkedIds)"
            @click="handleDeleteBatch"
            v-hasPermi="['cc:call-route:delete']"
        >
          <Icon icon="ep:delete" class="mr-5px" /> 批量删除
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
      <el-table-column label="主键id" align="center" prop="id" />
      <el-table-column label="路由名称" align="center" prop="name" />
      <el-table-column label="路由号码" align="center" prop="routeNum" />
      <el-table-column label="删除前缀" align="center" prop="deletePrefix" min-width="90px">
        <template #default="scope">
          <span>{{ scope.row.deletePrefix || '-' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="路由方向" align="center" prop="type" >
        <template #default="scope">
          <dict-tag :type="DICT_TYPE.CC_CALL_ROUTE_DIRECTION_TYPE" :value="scope.row.type" />
        </template>
      </el-table-column>
      <el-table-column label="优先级" align="center" prop="level" />
      <el-table-column label="启用状态" align="center" prop="status" >
        <template #default="scope">
          <dict-tag :type="DICT_TYPE.CC_CALL_ROUTE_STATUS" :value="scope.row.status" />
        </template>
      </el-table-column>
      <el-table-column
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
            @click="openForm('update', scope.row.id)"
            v-hasPermi="['cc:call-route:update']"
          >
            编辑
          </el-button>
          <router-link :to="'/cc/ivr/edit/' + scope.row.flowId + '/' + scope.row.name">
            <el-button link type="primary">设计</el-button>
          </router-link>
          <el-button
            link
            type="danger"
            @click="handleDelete(scope.row.id)"
            v-hasPermi="['cc:call-route:delete']"
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
  <CallRouteForm ref="formRef" @success="getList" />
</template>

<script setup lang="ts">
import { getIntDictOptions, DICT_TYPE } from '@/utils/dict'
import { isEmpty } from '@/utils/is'
import { dateFormatter } from '@/utils/formatTime'
import download from '@/utils/download'
import { CallRouteApi, CallRouteVO } from '@/api/cc/callroute'
import CallRouteForm from './CallRouteForm.vue'

/** cc 号码路由 列表 */
defineOptions({ name: 'CallRoute' })

const message = useMessage() // 消息弹窗
const { t } = useI18n() // 国际化

const loading = ref(true) // 列表的加载中
const list = ref<CallRouteVO[]>([]) // 列表的数据
const total = ref(0) // 列表的总页数
const queryParams = reactive({
  pageNo: 1,
  pageSize: 10,
  createTime: [],
  name: undefined,
  routeNum: undefined,
  type: undefined,
  level: undefined,
  status: undefined,
  flowId: undefined
})
const queryFormRef = ref() // 搜索的表单
const exportLoading = ref(false) // 导出的加载中

/** 查询列表 */
const getList = async () => {
  loading.value = true
  try {
    const data = await CallRouteApi.getCallRoutePage(queryParams)
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
    // 删除的二次确认
    await message.delConfirm()
    // 发起删除
    await CallRouteApi.deleteCallRoute(id)
    message.success(t('common.delSuccess'))
    // 刷新列表
    await getList()
  } catch {}
}

/** 批量删除cc 号码路由 */
const handleDeleteBatch = async () => {
  try {
    // 删除的二次确认
    await message.delConfirm()
    await CallRouteApi.deleteCallRouteList(checkedIds.value);
    message.success(t('common.delSuccess'))
    await getList();
  } catch {}
}

const checkedIds = ref<number[]>([])
const handleRowCheckboxChange = (records: CallRouteVO[]) => {
  checkedIds.value = records.map((item) => item.id);
}

/** 导出按钮操作 */
const handleExport = async () => {
  try {
    // 导出的二次确认
    await message.exportConfirm()
    // 发起导出
    exportLoading.value = true
    const data = await CallRouteApi.exportCallRoute(queryParams)
    download.excel(data, 'cc 号码路由.xls')
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
