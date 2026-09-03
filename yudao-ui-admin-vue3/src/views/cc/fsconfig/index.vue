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
      <el-form-item label="名称" prop="name">
        <el-input
          v-model="queryParams.name"
          placeholder="请输入名称"
          clearable
          @keyup.enter="handleQuery"
          class="!w-240px"
        />
      </el-form-item>
      <el-form-item label="客户端分组" prop="group">
        <el-input
          v-model="queryParams.group"
          placeholder="请输入客户端分组"
          clearable
          @keyup.enter="handleQuery"
          class="!w-240px"
        />
      </el-form-item>
      <el-form-item label="机器地址IP" prop="ip">
        <el-input
          v-model="queryParams.ip"
          placeholder="请输入机器地址IP"
          clearable
          @keyup.enter="handleQuery"
          class="!w-240px"
        />
      </el-form-item>
      <el-form-item label="状态" prop="status">
        <el-select
          v-model="queryParams.status"
          placeholder="请选择状态"
          clearable
          class="!w-240px"
        >
          <el-option
            v-for="dict in getStrDictOptions(DICT_TYPE.CC_FS_ONLINE_STATUS)"
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
          v-hasPermi="['cc:fs-config:create']"
        >
          <Icon icon="ep:plus" class="mr-5px" /> 新增
        </el-button>
        <el-button
          type="success"
          plain
          @click="handleExport"
          :loading="exportLoading"
          v-hasPermi="['cc:fs-config:export']"
        >
          <Icon icon="ep:download" class="mr-5px" /> 导出
        </el-button>
        <el-button
            type="danger"
            plain
            :disabled="isEmpty(checkedIds)"
            @click="handleDeleteBatch"
            v-hasPermi="['cc:fs-config:delete']"
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
      <el-table-column label="名称" align="center" prop="name" />
      <el-table-column label="客户端分组" align="center" prop="group" />
      <el-table-column label="机器地址IP" align="center" prop="ip" />
      <el-table-column label="端口" align="center" prop="port" />
      <el-table-column label="传输协议" align="center" prop="transportProtocol" width="110">
        <template #default="scope">
          <el-tag v-if="scope.row.transportProtocol === 1">UDP</el-tag>
          <el-tag v-else-if="scope.row.transportProtocol === 2" type="success">TCP</el-tag>
          <span v-else>跟随入站</span>
        </template>
      </el-table-column>
      <el-table-column label="esl端口" align="center" prop="eslPort" />
      <el-table-column label="密码" align="center" prop="password" />
      <el-table-column label="状态" align="center" prop="status">
        <template #default="scope">
          <dict-tag :type="DICT_TYPE.CC_FS_ONLINE_STATUS" :value="scope.row.status" />
        </template>
      </el-table-column>
      <el-table-column label="超时时间（秒）" align="center" prop="outTime" />
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
            v-hasPermi="['cc:fs-config:update']"
          >
            编辑
          </el-button>
          <el-button
            link
            type="danger"
            @click="handleDelete(scope.row.id)"
            v-hasPermi="['cc:fs-config:delete']"
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
  <FsConfigForm ref="formRef" @success="getList" />
</template>

<script setup lang="ts">
import { ElMessageBox } from 'element-plus'
import { getStrDictOptions, DICT_TYPE } from '@/utils/dict'
import { isEmpty } from '@/utils/is'
import { dateFormatter } from '@/utils/formatTime'
import download from '@/utils/download'
import { FsConfigApi, FsConfigVO } from '@/api/cc/fsconfig'
import FsConfigForm from './FsConfigForm.vue'

/** cc freeSwitch管理配置 列表 */
defineOptions({ name: 'FsConfig' })

const message = useMessage() // 消息弹窗
const { t } = useI18n() // 国际化

const loading = ref(true) // 列表的加载中
const list = ref<FsConfigVO[]>([]) // 列表的数据
const total = ref(0) // 列表的总页数
const queryParams = reactive({
  pageNo: 1,
  pageSize: 10,
  createTime: [],
  name: undefined,
  group: undefined,
  ip: undefined,
  status: undefined,
})
const queryFormRef = ref() // 搜索的表单
const exportLoading = ref(false) // 导出的加载中

/** 查询列表 */
const getList = async () => {
  loading.value = true
  try {
    const data = await FsConfigApi.getFsConfigPage(queryParams)
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
const openForm = async (type: string, id?: number) => {
  if (type === 'update') {
    try {
      await ElMessageBox.confirm(
        '修改FS配置会中断当前服务上的语音通话，请谨慎操作',
        '提示',
        {
          confirmButtonText: '确认',
          cancelButtonText: '取消',
          type: 'warning'
        }
      )
    } catch {
      return
    }
  }
  formRef.value.open(type, id)
}

/** 删除按钮操作 */
const handleDelete = async (id: number) => {
  try {
    await ElMessageBox.confirm(
      '删除FS配置会中断当前服务上的语音通话，请谨慎操作',
      '提示',
      {
        confirmButtonText: '确认',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )
    await FsConfigApi.deleteFsConfig(id)
    message.success(t('common.delSuccess'))
    await getList()
  } catch {}
}

/** 批量删除cc freeSwitch管理配置 */
const handleDeleteBatch = async () => {
  try {
    await ElMessageBox.confirm(
      '删除FS配置会中断当前服务上的语音通话，请谨慎操作',
      '提示',
      {
        confirmButtonText: '确认',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )
    await FsConfigApi.deleteFsConfigList(checkedIds.value);
    message.success(t('common.delSuccess'))
    await getList();
  } catch {}
}

const checkedIds = ref<number[]>([])
const handleRowCheckboxChange = (records: FsConfigVO[]) => {
  checkedIds.value = records.map((item) => item.id);
}

/** 导出按钮操作 */
const handleExport = async () => {
  try {
    // 导出的二次确认
    await message.exportConfirm()
    // 发起导出
    exportLoading.value = true
    const data = await FsConfigApi.exportFsConfig(queryParams)
    download.excel(data, 'cc freeSwitch管理配置.xls')
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
