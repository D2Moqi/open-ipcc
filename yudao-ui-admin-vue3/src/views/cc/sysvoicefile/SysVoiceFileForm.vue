<template>
  <Dialog :title="dialogTitle" v-model="dialogVisible">
    <el-form
      ref="formRef"
      :model="formData"
      :rules="formRules"
      label-width="100px"
      v-loading="formLoading"
    >
      <el-form-item label="文件名称" prop="name">
        <el-input v-model="formData.name" placeholder="请输入文件名称" />
      </el-form-item>
      <el-form-item label="类型" prop="type">
        <el-select
          v-model="formData.type"
          placeholder="请选择类型"
          @change="handleTypeChange"
        >
          <el-option
            v-for="dict in getIntDictOptions(DICT_TYPE.CC_SYS_VOICE_TYPE)"
            :key="dict.value"
            :label="dict.label"
            :value="dict.value"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="tts语音引擎" prop="tts" v-if="formData.type === VOICE_FILE_TYPE.SYNTHESIS">
        <el-select
          v-model="formData.tts"
          placeholder="请选择tts语音引擎"
          clearable
          class="!w-240px"
        >
          <el-option
            v-for="tts in ttsList"
            :key="tts.id"
            :label="tts.name"
            :value="tts.id"
          />
        </el-select>
      </el-form-item>
      <el-form-item v-if="formData.type === VOICE_FILE_TYPE.UPLOAD">
        <el-button type="primary" plain @click="openForm">
          <Icon icon="ep:upload" class="mr-5px" /> 上传文件
        </el-button>
      </el-form-item>
      <el-form-item label="合成文本" prop="speechText" v-if="formData.type === VOICE_FILE_TYPE.SYNTHESIS">
        <el-input type="textarea" v-model="formData.speechText" placeholder="请输入合成文本" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="submitForm" type="primary" :disabled="formLoading">确 定</el-button>
      <el-button @click="dialogVisible = false">取 消</el-button>
    </template>
  </Dialog>

  <!-- 文件弹窗 -->
  <FileForm ref="formFileRef" @success="handleSuccess"/>
</template>
<script setup lang="ts">
import { getIntDictOptions, DICT_TYPE } from '@/utils/dict'
import { SysVoiceFileApi, SysVoiceFileVO } from '@/api/cc/sysvoicefile'
import FileForm from '../../infra/file/VoiceFileForm.vue'
import { SysVoiceEngineApi, SysVoiceEngineVO } from '@/api/cc/sysvoiceengine'

/** 语音文件类型：1-手动上传 2-语音合成（取值须与后端字典 CC_SYS_VOICE_TYPE 一致） */
const VOICE_FILE_TYPE = {
  UPLOAD: 1,
  SYNTHESIS: 2
} as const

/** cc 语音文件 表单 */
defineOptions({ name: 'SysVoiceFileForm' })

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
  tts: undefined,
  speechText: undefined,
  fileUrl: undefined
})
const formRules = reactive({
  name: [{ required: true, message: '文件名称不能为空', trigger: 'blur' }],
  type: [{ required: true, message: '类型不能为空', trigger: 'change' }],
  /**
   * tts语音引擎：仅当类型为"语音合成"(type=2)时必填
   * 类型切换时 handleTypeChange 会统一清理校验状态与脏数据，避免切换后残留错误提示或无效值
   */
  tts: [
    {
      validator: (_rule: any, value: any, callback: any) => {
        if (formData.value.type === VOICE_FILE_TYPE.SYNTHESIS && (value === undefined || value === null || value === '')) {
          callback(new Error('请选择tts语音引擎'))
        } else {
          callback()
        }
      },
      trigger: ['change', 'blur']
    }
  ],
  /**
   * 合成文本：仅当类型为"语音合成"(type=2)时必填
   * 需求背景：选择语音合成方式时，必须提供待合成的文本内容，否则后端无法合成音频
   */
  speechText: [
    {
      validator: (_rule: any, value: any, callback: any) => {
        if (formData.value.type === VOICE_FILE_TYPE.SYNTHESIS && (!value || !String(value).trim())) {
          callback(new Error('请输入合成文本'))
        } else {
          callback()
        }
      },
      trigger: ['change', 'blur']
    }
  ]
})
const formRef = ref() // 表单 Ref
const ttsList = ref<SysVoiceEngineVO[]>([]) // tts语音引擎列表

/** 打开弹窗 */
const open = async (type: string, id?: number) => {
  dialogVisible.value = true
  dialogTitle.value = t('action.' + type)
  formType.value = type
  resetForm()
  // 查询tts语音引擎
  SysVoiceEngineApi.list({ type: VOICE_FILE_TYPE.SYNTHESIS }).then((res) => {
    if (res) {
      ttsList.value = res
    }
  })
  // 修改时，设置数据
  if (id) {
    formLoading.value = true
    try {
      formData.value = await SysVoiceFileApi.getSysVoiceFile(id)
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
  /**
   * 业务层兜底校验（防御规则绕过）
   * 需求明确：type=2（语音合成）时，TTS引擎必须选择；同时合成文本也不能为空，
   * 避免前端 rules 被绕过导致后端 400/500
   */
  const data = formData.value as unknown as SysVoiceFileVO
  if (data.type === VOICE_FILE_TYPE.SYNTHESIS) {
    if (!data.tts) {
      message.error('请选择tts语音引擎')
      return
    }
    if (!data.speechText || !String(data.speechText).trim()) {
      message.error('请输入合成文本')
      return
    }
  }
  // 提交请求
  formLoading.value = true
  try {
    if (formType.value === 'create') {
      await SysVoiceFileApi.createSysVoiceFile(data)
      message.success(t('common.createSuccess'))
    } else {
      await SysVoiceFileApi.updateSysVoiceFile(data)
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
    tts: undefined,
    speechText: undefined,
    fileUrl: undefined
  }
  formRef.value?.resetFields()
}

/**
 * 类型切换处理：
 * 1. 清空另一类型专属的字段（避免切换后残留脏数据，造成后端校验异常）
 * 2. 清除对应字段的校验错误状态，避免切回时仍显示上个类型的错误提示
 */
const handleTypeChange = (newType: number | undefined) => {
  if (newType === VOICE_FILE_TYPE.UPLOAD) {
    // 手动上传：清空语音合成相关字段
    formData.value.tts = undefined
    formData.value.speechText = undefined
    formRef.value?.clearValidate(['tts', 'speechText'])
  } else if (newType === VOICE_FILE_TYPE.SYNTHESIS) {
    // 语音合成：清空手动上传的文件地址
    formData.value.fileUrl = undefined
    formRef.value?.clearValidate(['fileUrl'])
  }
}

/** 上传文件操作 */
const formFileRef = ref()
const openForm = () => {
  formFileRef.value.open()
}

/** 上传文件成功处理 */
const handleSuccess = (url) => {
  formData.value.fileUrl = url
}
</script>
