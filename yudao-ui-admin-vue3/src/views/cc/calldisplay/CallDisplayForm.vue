<template>
  <Dialog :title="dialogTitle" v-model="dialogVisible">
    <el-form
      ref="formRef"
      :model="formData"
      :rules="formRules"
      label-width="100px"
      v-loading="formLoading"
    >
      <el-form-item label="电话号码" prop="phone">
        <el-input
          v-model="formData.phone"
          placeholder="请输入电话号码（支持数字、#、-、(、)）"
          @input="handlePhoneInput"
        />
      </el-form-item>
      <el-form-item label="备注" prop="remark">
        <el-input
          v-model="formData.remark"
          type="textarea"
          placeholder="请输入备注"
          :rows="3"
          maxlength="255"
          show-word-limit
        />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="submitForm" type="primary" :disabled="formLoading">确 定</el-button>
      <el-button @click="dialogVisible = false">取 消</el-button>
    </template>
  </Dialog>
</template>
<script setup lang="ts">
import { CallDisplayApi, CallDisplayVO } from '@/api/cc/calldisplay'

/** cc 号码管理 表单 */
defineOptions({ name: 'CallDisplayForm' })

const { t } = useI18n() // 国际化
const message = useMessage() // 消息弹窗

const dialogVisible = ref(false) // 弹窗的是否展示
const dialogTitle = ref('') // 弹窗的标题
const formLoading = ref(false) // 表单的加载中：1）修改时的数据加载；2）提交的按钮禁用
const formType = ref('') // 表单的类型：create - 新增；update - 修改
const formData = ref({
  id: undefined,
  phone: undefined,
  area: undefined,
  remark: undefined
})
const formRules = reactive({
  phone: [
    { required: true, message: '电话号码不能为空', trigger: 'blur' },
    {
      validator: (_rule: any, value: string, callback: any) => {
        if (!value) return callback()
        if (!/^[0-9#\-()]+$/.test(value)) {
          return callback(new Error('电话号码只允许数字、#、-、(、)'))
        }
        callback()
      },
      trigger: 'blur'
    }
  ]
})
const formRef = ref() // 表单 Ref

/** 打开弹窗 */
const open = async (type: string, id?: number) => {
  dialogVisible.value = true
  dialogTitle.value = t('action.' + type)
  formType.value = type
  resetForm()
  // 修改时，设置数据
  if (id) {
    formLoading.value = true
    try {
      formData.value = await CallDisplayApi.getCallDisplay(id)
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
    const data = formData.value as unknown as CallDisplayVO
    if (formType.value === 'create') {
      await CallDisplayApi.createCallDisplay(data)
      message.success(t('common.createSuccess'))
    } else {
      await CallDisplayApi.updateCallDisplay(data)
      message.success(t('common.updateSuccess'))
    }
    dialogVisible.value = false
    // 发送操作成功的事件
    emit('success')
  } finally {
    formLoading.value = false
  }
}

/**
 * 实时过滤电话号码输入中的非法字符，仅允许数字、#、-、(、)
 *
 * @param value 输入框当前值
 */
const handlePhoneInput = (value: string | Event) => {
  const raw = typeof value === 'string' ? value : (value.target as HTMLInputElement)?.value || ''
  const sanitized = raw.replace(/[^0-9#\-()]/g, '')
  if (sanitized !== raw) {
    formData.value.phone = sanitized
  }
}

/** 重置表单 */
const resetForm = () => {
  formData.value = {
    id: undefined,
    phone: undefined,
    area: undefined,
    remark: undefined
  }
  formRef.value?.resetFields()
}
</script>
