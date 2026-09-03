<template>
  <Dialog :title="dialogTitle" v-model="dialogVisible">
    <el-form
      ref="formRef"
      :model="formData"
      :rules="formRules"
      label-width="100px"
      v-loading="formLoading"
    >
      <el-form-item label="路由名称" prop="name">
        <el-input v-model="formData.name" placeholder="请输入路由名称" />
      </el-form-item>
      <el-form-item label="路由号码" prop="routeNumArray">
        <el-select
          v-model="formData.routeNumArray"
          placeholder="请选择路由号码"
          multiple
          filterable
          clearable
        >
          <el-option
            v-for="item in callDisplayOptions"
            :key="item.value"
            :label="item.label"
            :value="item.value"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="删除前缀" prop="deletePrefix">
        <el-input v-model="formData.deletePrefix" placeholder="可选，如 9#，匹配后从被叫号码中去除该前缀" />
      </el-form-item>
      <el-form-item label="路由方向" prop="type">
        <el-select v-model="formData.type" placeholder="请选择路由方向">
          <el-option
            v-for="dict in getIntDictOptions(DICT_TYPE.CC_CALL_ROUTE_DIRECTION_TYPE)"
            :key="dict.value"
            :label="dict.label"
            :value="dict.value"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="优先级" prop="level">
        <el-input v-model="formData.level" placeholder="请输入优先级" />
      </el-form-item>
      <el-form-item label="状态" prop="status">
        <el-radio-group v-model="formData.status">
          <el-radio
            v-for="dict in getIntDictOptions(DICT_TYPE.CC_CALL_ROUTE_STATUS)"
            :key="dict.value"
            :label="dict.value"
          >
            {{ dict.label }}
          </el-radio>
        </el-radio-group>
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
import { CallRouteApi, CallRouteVO } from '@/api/cc/callroute'
import { CallDisplayApi, CallDisplayVO } from '@/api/cc/calldisplay'

/** 路由号码保存格式为 ^(num1|num2|...).* 正则表达式；前端以数组维护，保存时拼接为 ^(xxx|xxx).*，回显时反向解析 */

/**
 * 将路由号码数组拼接为后端保存的正则表达式格式
 * @param arr 路由号码数组，如 ['9#', '400123', '100000']
 * @returns 正则表达式字符串，如 '^(9#|400123|100000).*'；数组为空时返回空字符串
 */
const buildRouteNum = (arr: string[]): string => {
  if (!arr || arr.length === 0) return ''
  return '^(' + arr.join('|') + ').*'
}

/**
 * 从后端保存的正则表达式格式解析回路由号码数组
 * @param routeNum 后端存储的 routeNum 字符串，如 '^(9#|400123|100000).*'
 * @returns 路由号码数组，如 ['9#', '400123', '100000']；解析失败或为空时返回空数组
 */
const parseRouteNum = (routeNum: string | undefined): string[] => {
  if (!routeNum) return []
  const match = routeNum.match(/^\^\((.+)\)\.\*$/)
  if (!match || !match[1]) return []
  return match[1].split('|')
}

/** cc 号码路由 表单 */
defineOptions({ name: 'CallRouteForm' })

const { t } = useI18n() // 国际化
const message = useMessage() // 消息弹窗

const dialogVisible = ref(false) // 弹窗的是否展示
const dialogTitle = ref('') // 弹窗的标题
const formLoading = ref(false) // 表单的加载中：1）修改时的数据加载；2）提交的按钮禁用
const formType = ref('') // 表单的类型：create - 新增；update - 修改
const callDisplayOptions = ref<{ label: string; value: string }[]>([]) // 号码下拉选项
const formData = ref({
  id: undefined,
  name: undefined,
  routeNum: undefined,
  routeNumArray: [] as string[],
  deletePrefix: undefined,
  type: undefined,
  level: undefined,
  status: undefined,
  scheduleId: undefined,
  routeType: undefined,
  routeValue: undefined
})
const formRules = reactive({
  name: [{ required: true, message: '路由名称不能为空', trigger: 'blur' }],
  routeNumArray: [{ required: true, message: '路由号码不能为空', trigger: 'change' }]
})
const formRef = ref() // 表单 Ref

/** 打开弹窗 */
const open = async (type: string, id?: number) => {
  dialogVisible.value = true
  dialogTitle.value = t('action.' + type)
  formType.value = type
  resetForm()
  // 加载号码列表选项
  await loadCallDisplayOptions()
  // 修改时，设置数据
  if (id) {
    formLoading.value = true
    try {
      const data = await CallRouteApi.getCallRoute(id)
      formData.value = { ...data, routeNumArray: parseRouteNum(data.routeNum) }
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
    const submitData = { ...formData.value } as unknown as CallRouteVO
    submitData.routeNum = buildRouteNum(formData.value.routeNumArray)
    if (formType.value === 'create') {
      await CallRouteApi.createCallRoute(submitData)
      message.success(t('common.createSuccess'))
    } else {
      await CallRouteApi.updateCallRoute(submitData)
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
    routeNum: undefined,
    routeNumArray: [],
    deletePrefix: undefined,
    type: undefined,
    level: undefined,
    status: undefined,
    scheduleId: undefined,
    routeType: undefined,
    routeValue: undefined
  }
  formRef.value?.resetFields()
}

/** 加载号码列表选项 */
const loadCallDisplayOptions = async () => {
  const list = await CallDisplayApi.list()
  callDisplayOptions.value = list.map((item: CallDisplayVO) => ({
    label: item.remark ? `${item.phone}(${item.remark})` : item.phone,
    value: item.phone
  }))
}
</script>
