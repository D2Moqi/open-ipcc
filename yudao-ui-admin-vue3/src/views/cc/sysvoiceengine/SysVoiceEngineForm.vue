<template>
  <Dialog :title="dialogTitle" v-model="dialogVisible">
    <el-form
      ref="formRef"
      :model="formData"
      :rules="formRules"
      label-width="100px"
      v-loading="formLoading"
    >
      <el-form-item label="名称" prop="name">
        <el-input v-model="formData.name" placeholder="请输入名称" />
      </el-form-item>
      <el-form-item label="引擎类型" prop="type">
        <el-select v-model="formData.type" placeholder="请选择引擎类型">
          <el-option
            v-for="dict in getIntDictOptions(DICT_TYPE.CC_SYS_VOICE_ENGINE)"
            :key="dict.value"
            :label="dict.label"
            :value="dict.value"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="引擎厂商" prop="manufacturerType">
        <el-select v-model="formData.manufacturerType" placeholder="请选择引擎厂商">
          <el-option
            v-for="dict in getIntDictOptions(DICT_TYPE.CC_SYS_VOICE_MANUFACTURER_TYPE)"
            :key="dict.value"
            :label="dict.label"
            :value="dict.value"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="appKey" prop="appKey">
        <el-input v-model="formData.appKey" placeholder="请输入appKey" />
      </el-form-item>
      <el-form-item label="accessKeyId" prop="accessKeyId">
        <el-input v-model="formData.accessKeyId" placeholder="请输入accessKeyId" />
      </el-form-item>
      <el-form-item label="accessKeySecret" prop="accessKeySecret">
        <el-input v-model="formData.accessKeySecret" placeholder="请输入accessKeySecret" />
      </el-form-item>
      <el-form-item label="接口地址" prop="url">
        <el-input v-model="formData.url" placeholder="请输入接口地址" />
      </el-form-item>
      <el-form-item label="音色" prop="voice" v-if="formData.type == 2">
        <el-input v-model="formData.voice" placeholder="请输入音色" />
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
import { SysVoiceEngineApi, SysVoiceEngineVO } from '@/api/cc/sysvoiceengine'

/** cc 语音引擎 表单 */
defineOptions({ name: 'SysVoiceEngineForm' })

const { t } = useI18n() // 国际化
const message = useMessage() // 消息弹窗

const dialogVisible = ref(false) // 弹窗的是否展示
const dialogTitle = ref('') // 弹窗的标题
const formLoading = ref(false) // 表单的加载中：1）修改时的数据加载；2）提交的按钮禁用
const formType = ref('') // 表单的类型：create - 新增；update - 修改
const formData = ref({
  id: undefined,
  name: undefined,
  type: undefined,
  manufacturerType: undefined,
  appKey: undefined,
  accessKeyId: undefined,
  accessKeySecret: undefined,
  url: undefined,
  voice: undefined,
})
const formRules = reactive({
  name: [{ required: true, message: '名称不能为空', trigger: 'blur' }],
  type: [{ required: true, message: '引擎类型不能为空', trigger: 'change' }],
  manufacturerType: [{ required: true, message: '引擎厂商不能为空', trigger: 'change' }],
  appKey: [{ required: true, message: 'appKey不能为空', trigger: 'blur' }],
  accessKeyId: [{ required: true, message: 'accessKeyId不能为空', trigger: 'blur' }],
  accessKeySecret: [{ required: true, message: 'accessKeySecret不能为空', trigger: 'blur' }],
  url: [{ required: true, message: '语音合成接口地址不能为空', trigger: 'blur' }],
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
      formData.value = await SysVoiceEngineApi.getSysVoiceEngine(id)
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
    const data = formData.value as unknown as SysVoiceEngineVO
    if (formType.value === 'create') {
      await SysVoiceEngineApi.createSysVoiceEngine(data)
      message.success(t('common.createSuccess'))
    } else {
      await SysVoiceEngineApi.updateSysVoiceEngine(data)
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
    type: undefined,
    manufacturerType: undefined,
    appKey: undefined,
    accessKeyId: undefined,
    accessKeySecret: undefined,
    url: undefined,
    voice: undefined,
  }
  formRef.value?.resetFields()
}
</script>
