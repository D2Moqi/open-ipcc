<template>
  <Dialog :title="dialogTitle" v-model="dialogVisible">
    <el-form
      ref="formRef"
      :model="formData"
      :rules="formRules"
      label-width="150px"
      v-loading="formLoading"
    >
      <el-form-item label="名称" prop="name">
        <el-input v-model="formData.name" placeholder="请输入名称" />
      </el-form-item>
      <el-form-item label="客户端分组" prop="group">
        <el-input v-model="formData.group" placeholder="请输入客户端分组" />
      </el-form-item>
      <el-form-item label="机器地址IP" prop="ip">
        <el-input v-model="formData.ip" placeholder="请输入机器地址IP" />
      </el-form-item>
      <el-form-item label="端口" prop="port">
        <el-input v-model="formData.port" placeholder="请输入端口" />
      </el-form-item>
      <el-form-item label="传输协议" prop="transportProtocol">
        <el-select v-model="formData.transportProtocol" placeholder="请选择传输协议（不配置则跟随入站协议）" clearable class="!w-full">
          <el-option label="UDP" :value="1" />
          <el-option label="TCP" :value="2" />
        </el-select>
      </el-form-item>
      <el-form-item label="esl端口" prop="eslPort">
        <el-input v-model="formData.eslPort" placeholder="请输入esl端口" />
      </el-form-item>
      <el-form-item label="密码" prop="password">
        <el-input v-model="formData.password" placeholder="请输入密码" />
      </el-form-item>
      <el-form-item label="状态" prop="status">
        <el-radio-group v-model="formData.status">
          <el-radio
            v-for="dict in getIntDictOptions(DICT_TYPE.CC_FS_ONLINE_STATUS)"
            :key="dict.value"
            :label="dict.value"
          >
            {{ dict.label }}
          </el-radio>
        </el-radio-group>
      </el-form-item>
      <el-form-item label="超时时间（秒）" prop="outTime">
        <el-input v-model="formData.outTime" placeholder="请输入超时时间（秒）" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="submitForm" type="primary" :disabled="formLoading">确 定</el-button>
      <el-button @click="dialogVisible = false">取 消</el-button>
    </template>
  </Dialog>
</template>
<script setup lang="ts">
import { DICT_TYPE, getIntDictOptions } from '@/utils/dict'
import { FsConfigApi, FsConfigVO } from '@/api/cc/fsconfig'

/** cc freeSwitch管理配置 表单 */
defineOptions({ name: 'FsConfigForm' })

const { t } = useI18n() // 国际化
const message = useMessage() // 消息弹窗

const dialogVisible = ref(false) // 弹窗的是否展示
const dialogTitle = ref('') // 弹窗的标题
const formLoading = ref(false) // 表单的加载中：1）修改时的数据加载；2）提交的按钮禁用
const formType = ref('') // 表单的类型：create - 新增；update - 修改
const formData = ref({
  id: undefined,
  name: undefined,
  group: undefined,
  ip: undefined,
  port: undefined,
  transportProtocol: undefined,
  eslPort: undefined,
  password: undefined,
  status: undefined,
  outTime: undefined
})
const formRules = reactive({
  name: [{ required: true, message: '名称不能为空', trigger: 'blur' }],
  group: [{ required: true, message: '客户端分组不能为空', trigger: 'blur' }],
  ip: [{ required: true, message: '机器地址IP不能为空', trigger: 'blur' }],
  port: [{ required: true, message: '端口不能为空', trigger: 'blur' }],
  eslPort: [{ required: true, message: 'esl端口不能为空', trigger: 'blur' }],
  password: [{ required: true, message: '密码不能为空', trigger: 'blur' }],
  status: [{ required: true, message: '状态 0-在线 1-下线不能为空', trigger: 'blur' }],
  outTime: [{ required: true, message: '超时时间（秒）不能为空', trigger: 'blur' }]
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
      formData.value = await FsConfigApi.getFsConfig(id)
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
    const data = formData.value as unknown as FsConfigVO
    if (formType.value === 'create') {
      await FsConfigApi.createFsConfig(data)
      message.success(t('common.createSuccess'))
    } else {
      await FsConfigApi.updateFsConfig(data)
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
    group: undefined,
    ip: undefined,
    port: undefined,
    transportProtocol: undefined,
    eslPort: undefined,
    password: undefined,
    status: undefined,
    outTime: undefined
  }
  formRef.value?.resetFields()
}
</script>
