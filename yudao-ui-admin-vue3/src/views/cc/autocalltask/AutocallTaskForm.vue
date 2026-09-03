<template>
  <Dialog :title="dialogTitle" v-model="dialogVisible" width="700px">
    <el-form
      ref="formRef"
      :model="formData"
      :rules="formRules"
      label-width="120px"
      v-loading="formLoading"
    >
      <el-form-item label="任务名称" prop="taskName">
        <el-input v-model="formData.taskName" placeholder="请输入任务名称" />
      </el-form-item>
      <el-form-item label="被叫号码列表" prop="targetNumbers">
        <el-input
          v-model="formData.targetNumbers"
          type="textarea"
          :rows="4"
          placeholder="多个号码用英文逗号分隔，例如：13800138000,13900139000"
        />
        <div class="form-tip">支持批量外呼，多个号码用英文逗号(,)分隔</div>
      </el-form-item>
      <el-form-item label="IVR流程" prop="ivrFlow">
        <el-select
          v-model="formData.ivrFlow"
          placeholder="请选择IVR流程(为空时按被叫号码匹配号码路由)"
          clearable
          filterable
          class="!w-full"
        >
          <el-option
            v-for="item in ivrFlowOptions"
            :key="item.value"
            :label="item.label"
            :value="item.value"
          />
        </el-select>
        <div class="form-tip">数据取自号码路由管理中路由方向为呼出的记录；为空时按被叫号码匹配号码路由表(type=2呼出)取 level 最高的路由</div>
      </el-form-item>
      <el-form-item label="出局网关" prop="gatewayId">
        <el-select
          v-model="formData.gatewayId"
          placeholder="选择出局网关(非必填，为空走号码路由或FS兜底)"
          clearable
          filterable
          class="!w-full"
        >
          <el-option
            v-for="gw in gatewayList"
            :key="gw.id"
            :label="gw.name"
            :value="gw.id"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="对外主叫号码" prop="callerId">
        <el-input v-model="formData.callerId" placeholder="对外主叫号码(DID)，如 01012345678" />
      </el-form-item>
      <el-form-item label="优先级" prop="priority">
        <el-input-number v-model="formData.priority" :min="0" :max="999" controls-position="right" />
        <div class="form-tip">数字越大越优先</div>
      </el-form-item>
      <el-form-item label="计划执行时间" prop="scheduleTime">
        <el-date-picker
          v-model="formData.scheduleTime"
          value-format="YYYY-MM-DD HH:mm:ss"
          type="datetime"
          placeholder="选择计划执行时间(为空则立即执行)"
          class="!w-full"
        />
      </el-form-item>
      <el-form-item label="业务变量JSON" prop="variables">
        <el-input
          v-model="formData.variables"
          type="textarea"
          :rows="3"
          placeholder='业务变量JSON,例如: {"tts_text":"您好"}'
        />
      </el-form-item>
      <el-form-item label="备注" prop="remark">
        <el-input v-model="formData.remark" type="textarea" :rows="2" placeholder="请输入备注" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="dialogVisible = false">取 消</el-button>
      <el-button @click="submitForm" type="primary" :disabled="formLoading">确 定</el-button>
    </template>
  </Dialog>
</template>

<script setup lang="ts">
import { AutocallTaskApi, AutocallTaskVO } from '@/api/cc/autocalltask'
import { SipProxyGatewayApi } from '@/api/cc/sipproxygateway'
import { CallRouteApi } from '@/api/cc/callroute'

/** 自动外呼任务 表单 */
defineOptions({ name: 'AutocallTaskForm' })

const { t } = useI18n() // 国际化
const message = useMessage() // 消息弹窗

const dialogVisible = ref(false) // 弹窗的是否展示
const dialogTitle = ref('') // 弹窗的标题
const formLoading = ref(false) // 表单的加载中
const formType = ref('') // 表单的类型：create - 新增；update - 修改

const gatewayList = ref<any[]>([]) // 网关列表(下拉选择)
const ivrFlowOptions = ref<{ label: string; value: string }[]>([]) // IVR流程下拉选项(取自号码路由中呼出方向)

const formData = ref({
  id: undefined as number | undefined,
  taskName: undefined as string | undefined,
  targetNumbers: undefined as string | undefined,
  gatewayId: undefined as number | undefined,
  ivrFlow: undefined as string | undefined,
  callerId: undefined as string | undefined,
  priority: 0 as number | undefined,
  variables: undefined as string | undefined,
  scheduleTime: undefined as string | undefined,
  remark: undefined as string | undefined
})

const formRules = reactive({
  taskName: [{ required: true, message: '任务名称不能为空', trigger: 'blur' }],
  targetNumbers: [{ required: true, message: '被叫号码列表不能为空', trigger: 'blur' }]
})
const formRef = ref() // 表单 Ref

/** 打开弹窗 */
const open = async (type: string, id?: number) => {
  dialogVisible.value = true
  dialogTitle.value = t('action.' + type)
  formType.value = type
  resetForm()
  // 并行加载网关列表和 IVR 流程下拉选项
  await Promise.all([loadGatewayList(), loadIvrFlowOptions()])
  // 修改时，设置数据
  if (id) {
    formLoading.value = true
    try {
      const data = await AutocallTaskApi.getAutocallTask(id)
      formData.value = {
        id: data.id,
        taskName: data.taskName,
        targetNumbers: data.targetNumbers,
        gatewayId: data.gatewayId,
        ivrFlow: data.ivrFlow,
        callerId: data.callerId,
        priority: data.priority || 0,
        variables: data.variables,
        scheduleTime: data.scheduleTime,
        remark: data.remark
      }
    } finally {
      formLoading.value = false
    }
  }
}
defineExpose({ open }) // 提供 open 方法，用于打开弹窗

/** 加载网关列表(下拉选项) */
const loadGatewayList = async () => {
  try {
    gatewayList.value = await SipProxyGatewayApi.getSimpleList()
  } catch {
    gatewayList.value = []
  }
}

/**
 * 加载 IVR 流程下拉选项
 * 数据来源：号码路由管理中路由方向(type)为呼出(2)的记录
 * 使用 list 接口查询全部号码路由，前端按 type=2 过滤
 * 选项 value：号码路由 id（字符串形式，与后端 ivrFlow 字段约定一致）
 * 选项 label：路由名称 + 路由号码，便于在 IVR 流程下拉中识别
 */
const loadIvrFlowOptions = async () => {
  try {
    const data = await CallRouteApi.list()
    ivrFlowOptions.value = (data || [])
      .filter((item: any) => item.type === 2)
      .map((item: any) => ({
        label: item.name ? `${item.name}(${item.routeNum || '-'})` : item.routeNum,
        value: String(item.id)
      }))
  } catch {
    ivrFlowOptions.value = []
  }
}

/** 提交表单 */
const emit = defineEmits(['success']) // 定义 success 事件
const submitForm = async () => {
  await formRef.value.validate()
  formLoading.value = true
  try {
    const data = { ...formData.value } as unknown as AutocallTaskVO
    if (formType.value === 'create') {
      await AutocallTaskApi.createAutocallTask(data)
      message.success(t('common.createSuccess'))
    } else {
      await AutocallTaskApi.updateAutocallTask(data)
      message.success(t('common.updateSuccess'))
    }
    dialogVisible.value = false
    emit('success')
  } finally {
    formLoading.value = false
  }
}

/** 重置表单 */
const resetForm = () => {
  formData.value = {
    id: undefined,
    taskName: undefined,
    targetNumbers: undefined,
    gatewayId: undefined,
    ivrFlow: undefined,
    callerId: undefined,
    priority: 0,
    variables: undefined,
    scheduleTime: undefined,
    remark: undefined
  }
  formRef.value?.resetFields()
}
</script>

<style scoped>
.form-tip {
  font-size: 12px;
  color: #909399;
  line-height: 1.5;
  margin-top: 4px;
}
</style>
