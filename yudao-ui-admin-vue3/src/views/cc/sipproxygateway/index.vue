<template>
  <ContentWrap>
    <el-form
      class="-mb-15px"
      :model="queryParams"
      ref="queryFormRef"
      :inline="true"
      label-width="68px"
    >
      <el-form-item label="网关名称" prop="name">
        <el-input
          v-model="queryParams.name"
          placeholder="请输入网关名称"
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
            v-for="dict in getIntDictOptions(DICT_TYPE.COMMON_STATUS)"
            :key="dict.value"
            :label="dict.label"
            :value="dict.value"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="外线号码" prop="externalLineNumber">
        <el-input
          v-model="queryParams.externalLineNumber"
          placeholder="请输入外线号码"
          clearable
          @keyup.enter="handleQuery"
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
          v-hasPermi="['cc:sip-proxy-gateway:create']"
        >
          <Icon icon="ep:plus" class="mr-5px" /> 新增
        </el-button>
        <el-button
          type="success"
          plain
          @click="handleExport"
          :loading="exportLoading"
          v-hasPermi="['cc:sip-proxy-gateway:export']"
        >
          <Icon icon="ep:download" class="mr-5px" /> 导出
        </el-button>
        <el-button
            type="danger"
            plain
            :disabled="isEmpty(checkedIds)"
            @click="handleDeleteBatch"
            v-hasPermi="['cc:sip-proxy-gateway:delete']"
        >
          <Icon icon="ep:delete" class="mr-5px" /> 批量删除
        </el-button>
        <el-button
          type="warning"
          plain
          @click="handleRefreshCache"
          :loading="refreshLoading"
          v-hasPermi="['cc:sip-proxy-gateway:update']"
        >
          <Icon icon="ep:refresh-right" class="mr-5px" /> 刷新缓存
        </el-button>
      </el-form-item>
    </el-form>
  </ContentWrap>

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
      <el-table-column label="网关名称" align="center" prop="name" min-width="120" />
      <el-table-column label="网关类型" align="center" prop="type" width="100">
        <template #default="scope">
          <el-tag v-if="scope.row.type === 1" type="success">内部网关</el-tag>
          <el-tag v-else type="warning">外部网关</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="网关地址" align="center" min-width="150">
        <template #default="scope">
          {{ scope.row.address }}:{{ scope.row.port }}
        </template>
      </el-table-column>
      <el-table-column label="认证类型" align="center" prop="authType" width="100">
        <template #default="scope">
          <el-tag v-if="scope.row.authType === 0" type="info">不认证</el-tag>
          <el-tag v-else type="warning">密码认证</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="传输协议" align="center" prop="transportProtocol" width="100">
        <template #default="scope">
          <el-tag v-if="scope.row.transportProtocol === 1">UDP</el-tag>
          <el-tag v-else-if="scope.row.transportProtocol === 2" type="success">TCP</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="注册模式" align="center" prop="registerEnabled" width="110">
        <template #default="scope">
          <dict-tag :type="DICT_TYPE.CC_SIPPROXY_GATEWAY_REGISTER_MODE" :value="scope.row.registerEnabled" />
        </template>
      </el-table-column>
      <el-table-column label="注册域" align="center" min-width="110">
        <template #default="scope">
          <!-- 直连模式无注册域概念，显示空；注册域缺省时回显回退值提示 -->
          <span v-if="scope.row.registerEnabled === 1 && scope.row.registerRealm">{{ scope.row.registerRealm }}</span>
          <span v-else-if="scope.row.registerEnabled === 1">{{ scope.row.fromDomain || '默认(sipproxy公网IP)' }}</span>
          <span v-else>–</span>
        </template>
      </el-table-column>
      <el-table-column label="注册有效期(秒)" align="center" width="120">
        <template #default="scope">
          <!-- 直连模式无注册有效期概念，显示空；注册模式回显配置上限，缺省提示默认7200 -->
          <span v-if="scope.row.registerEnabled === 1">{{ scope.row.registerMaxExpires ?? 7200 }}</span>
          <span v-else>–</span>
        </template>
      </el-table-column>
      <el-table-column label="注册状态" align="center" width="100">
        <template #default="scope">
          <!-- 直连模式无注册状态，显示空；注册模式依据绑定存活展示在线/离线 -->
          <template v-if="scope.row.registerEnabled === 1">
            <dict-tag
              :type="DICT_TYPE.CC_SIPPROXY_GATEWAY_REGISTER_STATUS"
              :value="registerStatusMap[scope.row.id] ?? 0"
            />
          </template>
        </template>
      </el-table-column>
      <el-table-column label="账户" align="center" prop="username" min-width="100" />
      <el-table-column label="外线号码(DID)" align="center" prop="externalLineNumber" min-width="120" />
      <el-table-column label="From域" align="center" prop="fromDomain" min-width="120" />
      <el-table-column label="CallerId显示" align="center" prop="callerIdInFrom" width="120">
        <template #default="scope">
          <el-tag v-if="scope.row.callerIdInFrom === 0" type="success">是(真实主叫)</el-tag>
          <el-tag v-else type="info">否(使用DID)</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="状态" align="center" prop="status" width="100">
        <template #default="scope">
          <dict-tag :type="DICT_TYPE.COMMON_STATUS" :value="scope.row.status" />
        </template>
      </el-table-column>
      <el-table-column label="备注" align="center" prop="remark" min-width="120" />
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
            v-hasPermi="['cc:sip-proxy-gateway:update']"
          >
            编辑
          </el-button>
          <el-button
            link
            type="danger"
            @click="handleDelete(scope.row.id)"
            v-hasPermi="['cc:sip-proxy-gateway:delete']"
          >
            删除
          </el-button>
        </template>
      </el-table-column>
    </el-table>
    <Pagination
      :total="total"
      v-model:page="queryParams.pageNo"
      v-model:limit="queryParams.pageSize"
      @pagination="getList"
    />
  </ContentWrap>

  <SipProxyGatewayForm ref="formRef" @success="getList" />
</template>

<script setup lang="ts">
import { DICT_TYPE, getIntDictOptions } from '@/utils/dict'
import { isEmpty } from '@/utils/is'
import { dateFormatter } from '@/utils/formatTime'
import download from '@/utils/download'
import { SipProxyGatewayApi, SipProxyGatewayVO } from '@/api/cc/sipproxygateway'
import SipProxyGatewayForm from './SipProxyGatewayForm.vue'

/** 网关注册状态映射（gatewayId → 1在线/0离线），注册模式网关才有 key，直连模式不显示 */
const registerStatusMap = ref<Record<number, number>>({})

defineOptions({ name: 'SipProxyGateway' })

const message = useMessage()
const { t } = useI18n()

const loading = ref(true)
const list = ref<SipProxyGatewayVO[]>([])
const total = ref(0)
const refreshLoading = ref(false)
const queryParams = reactive({
  pageNo: 1,
  pageSize: 10,
  name: undefined,
  status: undefined,
  externalLineNumber: undefined,
})
const queryFormRef = ref()
const exportLoading = ref(false)

const getList = async () => {
  loading.value = true
  try {
    // 并行拉取列表与注册状态映射（状态接口失败不影响列表展示，降级为空 map）
    const [data, statusMap] = await Promise.all([
      SipProxyGatewayApi.getSipProxyGatewayPage(queryParams),
      SipProxyGatewayApi.getRegisterStatusList().catch(() => ({}))
    ])
    list.value = data.list
    total.value = data.total
    registerStatusMap.value = statusMap || {}
  } finally {
    loading.value = false
  }
}

const handleQuery = () => {
  queryParams.pageNo = 1
  getList()
}

const resetQuery = () => {
  queryFormRef.value.resetFields()
  handleQuery()
}

const formRef = ref()
const openForm = (type: string, id?: number) => {
  formRef.value.open(type, id)
}

const handleDelete = async (id: number) => {
  try {
    await message.delConfirm()
    await SipProxyGatewayApi.deleteSipProxyGateway(id)
    message.success(t('common.delSuccess'))
    await getList()
  } catch {}
}

const checkedIds = ref<number[]>([])
const handleRowCheckboxChange = (records: SipProxyGatewayVO[]) => {
  checkedIds.value = records.map((item) => item.id!).filter(Boolean)
}

const handleDeleteBatch = async () => {
  try {
    await message.delConfirm()
    await SipProxyGatewayApi.deleteSipProxyGatewayList(checkedIds.value)
    message.success(t('common.delSuccess'))
    await getList()
  } catch {}
}

const handleExport = async () => {
  try {
    await message.exportConfirm()
    exportLoading.value = true
    const data = await SipProxyGatewayApi.exportSipProxyGateway(queryParams)
    download.excel(data, 'SIP代理网关.xls')
  } catch {
  } finally {
    exportLoading.value = false
  }
}

const handleRefreshCache = async () => {
  try {
    await message.confirm('确认刷新网关缓存？')
    refreshLoading.value = true
    await SipProxyGatewayApi.refreshCache()
    message.success('缓存刷新成功')
  } catch {
  } finally {
    refreshLoading.value = false
  }
}

onMounted(() => {
  getList()
})
</script>
