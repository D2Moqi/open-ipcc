<template>
  <Dialog :title="dialogTitle" v-model="dialogVisible">
    <el-form
      ref="formRef"
      :model="formData"
      :rules="formRules"
      label-width="120px"
      v-loading="formLoading"
    >
      <el-form-item label="坐席名称" prop="name">
        <el-input v-model="formData.name" placeholder="请输入坐席名" />
      </el-form-item>
      <el-form-item label="用户" prop="userId">
        <el-select
          v-model="formData.userId"
          filterable
          placeholder="请选择用户"
          clearable
          class="!w-240px"
        >
          <el-option v-for="usr in userList" :key="usr.id" :label="usr.nickname" :value="usr.id" />
        </el-select>
      </el-form-item>
      <el-form-item label="SIP密码" prop="password">
        <el-input
          v-model="formData.password"
          type="password"
          placeholder="请输入SIP密码"
          show-password
        />
      </el-form-item>
      <el-form-item label="开通状态" prop="status">
        <el-select v-model="formData.status" placeholder="请选择状态" clearable class="!w-240px">
          <el-option
            v-for="dict in getIntDictOptions(DICT_TYPE.CC_SIP_SUBSCRIBER_STATUS)"
            :key="dict.value"
            :label="dict.label"
            :value="dict.value"
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
import { SysAgentApi, SysAgentVO } from '@/api/cc/sysagent'
import { DICT_TYPE, getIntDictOptions } from '@/utils/dict'
import * as UserApi from '@/api/system/user'

defineOptions({ name: 'SysAgentForm' })

const { t } = useI18n()
const message = useMessage()

const dialogVisible = ref(false)
const dialogTitle = ref('')
const formLoading = ref(false)
const formType = ref('')
const formData = ref({
  id: undefined,
  name: undefined,
  userId: undefined,
  domain: undefined,
  password: undefined,
  status: undefined,
  onlineStatus: undefined
})
const formRules = reactive({
  name: [{ required: true, message: '坐席名不能为空', trigger: 'blur' }],
  password: [{ required: true, message: 'SIP密码不能为空', trigger: 'blur' }],
  userId: [{ required: true, message: '用户不能为空', trigger: 'blur' }],
  status: [{ required: true, message: '开通状态不能为空', trigger: 'blur' }]
})
const formRef = ref()
const userList = ref<UserApi.UserVO[]>([])

const open = async (type: string, id?: number) => {
  dialogVisible.value = true
  dialogTitle.value = t('action.' + type)
  formType.value = type
  userList.value = await UserApi.getSimpleUserList()
  resetForm()
  if (id) {
    formLoading.value = true
    try {
      formData.value = await SysAgentApi.getSysAgent(id)
    } finally {
      formLoading.value = false
    }
  }
}
defineExpose({ open })

const emit = defineEmits(['success'])
const submitForm = async () => {
  await formRef.value.validate()
  formLoading.value = true
  try {
    const data = formData.value as unknown as SysAgentVO
    if (formType.value === 'create') {
      await SysAgentApi.createSysAgent(data)
      message.success(t('common.createSuccess'))
    } else {
      await SysAgentApi.updateSysAgent(data)
      message.success(t('common.updateSuccess'))
    }
    dialogVisible.value = false
    emit('success')
  } finally {
    formLoading.value = false
  }
}

const resetForm = () => {
  formData.value = {
    id: undefined,
    name: undefined,
    userId: undefined,
    domain: undefined,
    password: undefined,
    status: undefined,
    onlineStatus: undefined
  }
  formRef.value?.resetFields()
}
</script>
