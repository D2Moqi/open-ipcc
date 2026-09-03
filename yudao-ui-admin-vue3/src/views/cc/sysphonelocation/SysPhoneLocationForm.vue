<template>
  <Dialog :title="dialogTitle" v-model="dialogVisible">
    <el-form
      ref="formRef"
      :model="formData"
      :rules="formRules"
      label-width="100px"
      v-loading="formLoading"
    >
      <el-form-item label="号段前缀" prop="pref">
        <el-input v-model="formData.pref" placeholder="请输入号段前缀" />
      </el-form-item>
      <el-form-item label="手机号" prop="phone">
        <el-input v-model="formData.phone" placeholder="请输入手机号" />
      </el-form-item>
      <el-form-item label="省份" prop="province">
        <el-input v-model="formData.province" placeholder="请输入省份" />
      </el-form-item>
      <el-form-item label="城市" prop="city">
        <el-input v-model="formData.city" placeholder="请输入城市" />
      </el-form-item>
      <el-form-item label="运营商类型名称" prop="isp">
        <el-input v-model="formData.isp" placeholder="请输入运营商类型名称" />
      </el-form-item>
      <el-form-item label="邮编" prop="postCode">
        <el-input v-model="formData.postCode" placeholder="请输入邮编" />
      </el-form-item>
      <el-form-item label="区号" prop="cityCode">
        <el-input v-model="formData.cityCode" placeholder="请输入区号" />
      </el-form-item>
      <el-form-item label="行政区划编码" prop="areaCode">
        <el-input v-model="formData.areaCode" placeholder="请输入行政区划编码" />
      </el-form-item>
    </el-form>
    <template #footer>
<!--      <el-button @click="submitForm" type="primary" :disabled="formLoading">确 定</el-button>-->
      <el-button @click="dialogVisible = false">取 消</el-button>
    </template>
  </Dialog>
</template>
<script setup lang="ts">
import { PhoneLocationApi, PhoneLocationVO } from '@/api/cc/phonelocation'

/** cc 电话归属地 表单 */
defineOptions({ name: 'PhoneLocationForm' })

const { t } = useI18n() // 国际化
const message = useMessage() // 消息弹窗

const dialogVisible = ref(false) // 弹窗的是否展示
const dialogTitle = ref('') // 弹窗的标题
const formLoading = ref(false) // 表单的加载中：1）修改时的数据加载；2）提交的按钮禁用
const formType = ref('') // 表单的类型：create - 新增；update - 修改
const formData = ref({
  id: undefined,
  pref: undefined,
  phone: undefined,
  province: undefined,
  city: undefined,
  isp: undefined,
  ispType: undefined,
  postCode: undefined,
  cityCode: undefined,
  areaCode: undefined
})
const formRules = reactive({
  phone: [{ required: true, message: '手机号不能为空', trigger: 'blur' }],
  ispType: [{ required: true, message: '运营商类型 1：移动 2：联通 3：电信 4：广电 5：工信不能为空', trigger: 'change' }],
  cityCode: [{ required: true, message: '区号不能为空', trigger: 'blur' }]
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
      formData.value = await PhoneLocationApi.getPhoneLocation(id)
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
    const data = formData.value as unknown as PhoneLocationVO
    if (formType.value === 'create') {
      await PhoneLocationApi.createPhoneLocation(data)
      message.success(t('common.createSuccess'))
    } else {
      await PhoneLocationApi.updatePhoneLocation(data)
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
    pref: undefined,
    phone: undefined,
    province: undefined,
    city: undefined,
    isp: undefined,
    ispType: undefined,
    postCode: undefined,
    cityCode: undefined,
    areaCode: undefined
  }
  formRef.value?.resetFields()
}
</script>
