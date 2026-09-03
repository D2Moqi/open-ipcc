<template>
  <Dialog :title="dialogTitle" v-model="dialogVisible">
    <el-form
      ref="formRef"
      :model="formData"
      :rules="formRules"
      label-width="150px"
      v-loading="formLoading"
    >
      <el-form-item label="计划名称" prop="name">
        <el-input v-model="formData.name" placeholder="请输入计划名称" />
      </el-form-item>
      <el-form-item label="数据类型" prop="type">
        <el-select v-model="formData.type" placeholder="请选择类型">
          <el-option
            v-for="dict in getStrDictOptions(DICT_TYPE.CC_FS_CONTEXT_FORMAT)"
            :key="dict.value"
            :label="dict.label"
            :value="dict.value"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="内容类型" prop="contextName">
        <el-select v-model="formData.contextName" placeholder="请选择内容类型 public、default">
          <el-option
            v-for="dict in getStrDictOptions(DICT_TYPE.CC_FS_DIALPLAN_CONTEXT_NAME)"
            :key="dict.value"
            :label="dict.label"
            :value="dict.value"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="内容" prop="content">
        <el-input v-model="formData.content" type="textarea" :rows="10"  placeholder="请输入内容" />
      </el-form-item>
      <el-form-item label="描述" prop="describe">
        <el-input v-model="formData.describe" placeholder="请输入描述" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="submitForm" type="primary" :disabled="formLoading">确 定</el-button>
      <el-button @click="dialogVisible = false">取 消</el-button>
    </template>
  </Dialog>
</template>
<script setup lang="ts">
import { getStrDictOptions, DICT_TYPE } from '@/utils/dict'
import { FsDialplanApi, FsDialplanVO } from '@/api/cc/fsdialplan'

/** cc freeSwitch拨号计划 表单 */
defineOptions({ name: 'FsDialplanForm' })

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
  contextName: undefined,
  content: undefined,
  describe: undefined,
})
const formRules = reactive({
  name: [{ required: true, message: '计划名称不能为空', trigger: 'blur' }],
  type: [{ required: true, message: '数据类型', trigger: 'change' }],
  contextName: [{ required: true, message: '内容类型', trigger: 'change' }],
  content: [{ required: true, message: '内容不能为空', trigger: 'blur' }],
  describe: [{ required: true, message: '描述不能为空', trigger: 'blur' }],
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
      formData.value = await FsDialplanApi.getFsDialplan(id)
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
    const data = formData.value as unknown as FsDialplanVO
    if (formType.value === 'create') {
      await FsDialplanApi.createFsDialplan(data)
      message.success(t('common.createSuccess'))
    } else {
      await FsDialplanApi.updateFsDialplan(data)
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
    contextName: undefined,
    content: undefined,
    describe: undefined,
  }
  formRef.value?.resetFields()
}
</script>
