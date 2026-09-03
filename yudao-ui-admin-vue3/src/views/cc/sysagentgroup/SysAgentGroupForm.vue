<template>
  <Dialog :title="dialogTitle" v-model="dialogVisible" width="70%">
    <el-form
      ref="formRef"
      :model="formData"
      :rules="formRules"
      label-width="150px"
      v-loading="formLoading"
    >
      <el-form-item label="坐席组名称" prop="name">
        <el-input v-model="formData.name" placeholder="请输入坐席组名称" />
      </el-form-item>
      <el-form-item label="选择坐席" prop="phoneList">
        <el-transfer
          v-model="formData.agentList"
          :data="agentListData"
          :titles="['可选择', '已选择']"
          :props="{
            key: 'id',
            label: 'name'
          }"
          :list-style="{
            width: '200px',
            height: '300px'
          }"
          filterable
          @change="handleChange"
        />
      </el-form-item>
      <el-form-item label="策略类型" prop="strategyType">
        <el-select v-model="formData.strategyType" placeholder="请选择策略类型">
          <el-option
            v-for="dict in getIntDictOptions(DICT_TYPE.CC_SYS_AGENT_GROUP_STRATEGY_TYPE)"
            :key="dict.value"
            :label="dict.label"
            :value="dict.value"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="全忙策略" prop="fullBusyType">
        <el-select v-model="formData.fullBusyType" clearable placeholder="请选择全忙策略">
          <el-option
            v-for="dict in getIntDictOptions(DICT_TYPE.CC_SYS_AGENT_GROUP_FULL_BUSY_TYPE)"
            :key="dict.value"
            :label="dict.label"
            :value="dict.value"
          />
        </el-select>
      </el-form-item>

      <el-form-item label="排队超时时间（秒）" prop="timeOut" v-if="formData.fullBusyType == 0">
        <el-input v-model="formData.timeOut" placeholder="请输入排队超时时间（秒）" />
      </el-form-item>
      <el-form-item label="最大排队人数" prop="queueLength" v-if="formData.fullBusyType == 0">
        <el-input v-model="formData.queueLength" placeholder="请输入最大排队人数" />
      </el-form-item>

      <el-form-item label="溢出策略" prop="overflowType" v-if="formData.fullBusyType == 1">
        <el-select v-model="formData.overflowType" clearable placeholder="请选择溢出策略">
          <el-option
            v-for="dict in getIntDictOptions(DICT_TYPE.CC_SYS_AGENT_GROUP_OVERFLOW_TYPE)"
            :key="dict.value"
            :label="dict.label"
            :value="dict.value"
          />
        </el-select>
      </el-form-item>
      <el-form-item
        label="溢出IVR流程"
        prop="overflowValue"
        v-if="formData.fullBusyType == 1 && formData.overflowType == 1"
      >
        <!-- overflowValue 取值为 IVR 流程 ID(后端按 Long 解析)，选项来自流程分页列表的 id；
             cc_flow_info 无名称列，label 以"流程#id"展示 -->
        <el-select v-model="formData.overflowValue" clearable placeholder="请选择溢出IVR流程">
          <el-option
            v-for="flow in flowListData"
            :key="flow.id"
            :label="flow.name"
            :value="flow.id"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="优先级" prop="priority">
        <el-input v-model="formData.priority" placeholder="请输入优先级" />
      </el-form-item>
      <el-form-item label="描述" prop="describe">
        <el-input v-model="formData.describe" placeholder="请输入描述" />
      </el-form-item>
      <el-form-item label="可用网关" prop="availableGatewayIds">
        <el-select
          v-model="formData.availableGatewayIds"
          multiple
          clearable
          collapse-tags
          collapse-tags-tooltip
          placeholder="请配置可用网关"
          style="width: 100%"
        >
          <el-option
            v-for="gw in gatewayListData"
            :key="gw.id"
            :label="gw.name"
            :value="gw.id"
          />
        </el-select>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="submitForm" type="primary" :disabled="formLoading">确 定</el-button>
      <el-button @click="dialogVisible = false">取 消</el-button>
    </template>
  </Dialog>
</template>
<script setup lang="ts">
import { getIntDictOptions, DICT_TYPE } from '@/utils/dict'
import { SysAgentGroupApi, SysAgentGroupVO } from '@/api/cc/sysagentgroup'
import { SysAgentApi, SysAgentVO } from '@/api/cc/sysagent'
import { CallRouteApi, CallRouteVO } from '@/api/cc/callroute'
import { SipProxyGatewayApi, SipProxyGatewayVO } from '@/api/cc/sipproxygateway'
import { CcIvrApi } from '@/api/cc/ivr'

/** cc 坐席组 表单 */
defineOptions({ name: 'SysAgentGroupForm' })

const { t } = useI18n() // 国际化
const message = useMessage() // 消息弹窗

const dialogVisible = ref(false) // 弹窗的是否展示
const dialogTitle = ref('') // 弹窗的标题
const formLoading = ref(false) // 表单的加载中：1）修改时的数据加载；2）提交的按钮禁用
const formType = ref('') // 表单的类型：create - 新增；update - 修改
interface SysAgentGroupFormFormData {
  id?: number
  name?: string
  priority?: number
  describe?: string
  strategyType?: number
  fullBusyType?: number
  overflowType?: number
  overflowValue?: string
  timeOut?: number
  queueLength?: number
  agentList: string[]
  availableGatewayIds?: number[]
}
const formData = ref<SysAgentGroupFormFormData>({
  id: undefined,
  name: undefined,
  priority: undefined,
  describe: undefined,
  strategyType: undefined,
  fullBusyType: undefined,
  overflowType: undefined,
  overflowValue: undefined,
  timeOut: undefined,
  queueLength: undefined,
  agentList: [],
  availableGatewayIds: []
})
const formRules = reactive({
  name: [{ required: true, message: '坐席组名称不能为空', trigger: 'blur' }],
  strategyType: [
    {
      required: true,
      message: '策略类型不能为空',
      trigger: 'change'
    }
  ]
})
const formRef = ref() // 表单 Ref
const agentListData = ref<SysAgentVO[]>([]) // 坐席列表
const routeListData = ref<CallRouteVO[]>([]) // 路由列表
const gatewayListData = ref<SipProxyGatewayVO[]>([]) // 网关列表
// IVR 流程列表(溢出转IVR 时 overflowValue 保存流程 ID, 下拉选项 value 取 flow.id)
const flowListData = ref<{ id: string; name: string }[]>([])

/** 打开弹窗 */
const open = async (type: string, id?: number) => {
  dialogVisible.value = true
  dialogTitle.value = t('action.' + type)
  formType.value = type
  resetForm()
  // 查询坐席列表
  SysAgentApi.list().then((res) => {
    if (res) {
      agentListData.value = res.map((item) => ({
        // 确保id为字符串类型
        id: item.id.toString(),
        // 穿梭框显示格式：坐席名称(用户名)，用户名缺失时仅显示坐席名称
        name: item.userName ? `${item.name}(${item.userName})` : item.name
      }))
    }
  })
  // 查询路由列表
  CallRouteApi.list().then((res) => {
    if (res) {
      routeListData.value = res.map((item) => ({
        // 确保id为字符串类型
        id: item.id.toString(),
        name: item.routeNum
      }))
    }
  })
  // 查询网关列表（simple-list返回所有网关，用于选择可用网关）
  SipProxyGatewayApi.getSimpleList().then((res) => {
    if (res) {
      gatewayListData.value = res
    }
  })
  // 查询 IVR 流程列表(全量, 供溢出转IVR 选择流程 ID; cc_flow_info 无名称列,
  // label 以"流程#id"展示, 与流程配置页入口保持一致; pageSize 上限 200)
  CcIvrApi.getPage({ pageNo: 1, pageSize: 200 }).then((res: any) => {
    if (res && res.list) {
      flowListData.value = res.list.map((item: any) => ({
        id: item.id.toString(),
        name: '流程#' + item.id
      }))
    }
  })
  // 修改时，设置数据
  if (id) {
    formLoading.value = true
    try {
      const result = await SysAgentGroupApi.getSysAgentGroup(id)
      formData.value = {
        ...result,
        agentList: result.agentList || [],
        availableGatewayIds: result.availableGatewayIds || []
      }
    } finally {
      formLoading.value = false
    }
  }
}
defineExpose({ open }) // 提供 open 方法，用于打开弹窗

/** 提交表单 */
const emit = defineEmits(['success']) // 定义 success 事件，用于操作成功后的回调
const submitForm = async () => {
  // 校验表单
  await formRef.value.validate()
  // 提交请求
  formLoading.value = true
  try {
    const data = formData.value as unknown as SysAgentGroupVO
    if (formType.value === 'create') {
      await SysAgentGroupApi.createSysAgentGroup(data)
      message.success(t('common.createSuccess'))
    } else {
      await SysAgentGroupApi.updateSysAgentGroup(data)
      message.success(t('common.updateSuccess'))
    }
    dialogVisible.value = false
    // 发送操作成功的事件
    emit('success')
  } finally {
    formLoading.value = false
  }
}

/** 重置表单 */
const resetForm = () => {
  formData.value = {
    id: undefined,
    name: undefined,
    priority: undefined,
    describe: undefined,
    strategyType: undefined,
    fullBusyType: undefined,
    overflowType: undefined,
    overflowValue: undefined,
    timeOut: undefined,
    queueLength: undefined,
    agentList: [],
    availableGatewayIds: []
  }
  formRef.value?.resetFields()
}

/**
 * 处理选择器的 change 事件
 */
const handleChange = (nextTargetKeys: string[]) => {
  // 显式更新选中的号码列表
  formData.value.agentList = nextTargetKeys
}
</script>
