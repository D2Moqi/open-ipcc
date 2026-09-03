<template>
  <Dialog :title="dialogTitle" v-model="dialogVisible">
    <el-form
      ref="formRef"
      :model="formData"
      :rules="formRules"
      label-width="100px"
      v-loading="formLoading"
    >
      <el-form-item label="省份名称" prop="provinceName">
        <el-input v-model="formData.provinceName" placeholder="请输入省份名称" />
      </el-form-item>
      <el-form-item label="城市名称" prop="cityName">
        <el-input v-model="formData.cityName" placeholder="请输入城市名称" />
      </el-form-item>
      <el-form-item label="省份地域编码" prop="provinceAdCode">
        <el-input v-model="formData.provinceAdCode" placeholder="请输入省份地域编码" />
      </el-form-item>
      <el-form-item label="省份中心坐标" prop="provinceCenter">
        <el-input v-model="formData.provinceCenter" placeholder="请输入省份中心坐标" />
      </el-form-item>
      <el-form-item label="城市区号" prop="cityCode">
        <el-input v-model="formData.cityCode" placeholder="请输入城市区号" />
      </el-form-item>
      <el-form-item label="城市地域编码" prop="cityAdCode">
        <el-input v-model="formData.cityAdCode" placeholder="请输入城市地域编码" />
      </el-form-item>
      <el-form-item label="城市中心坐标" prop="cityCenter">
        <el-input v-model="formData.cityCenter" placeholder="请输入城市中心坐标" />
      </el-form-item>
      <el-form-item label="区域映射" prop="districts">
        <el-input v-model="formData.districts" placeholder="请输入区域映射" />
      </el-form-item>
      <el-form-item label="省份国际ISO编码" prop="isoCode">
        <el-input v-model="formData.isoCode" placeholder="请输入省份国际ISO编码" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="submitForm" type="primary" :disabled="formLoading">确 定</el-button>
      <el-button @click="dialogVisible = false">取 消</el-button>
    </template>
  </Dialog>
</template>
<script setup lang="ts">
import { AreaCodeApi, AreaCode } from '@/api/cc/areacode'

/** cc 电话区号 表单 */
defineOptions({ name: 'AreaCodeForm' })

const { t } = useI18n() // 国际化
const message = useMessage() // 消息弹窗

const dialogVisible = ref(false) // 弹窗的是否展示
const dialogTitle = ref('') // 弹窗的标题
const formLoading = ref(false) // 表单的加载中：1）修改时的数据加载；2）提交的按钮禁用
const formType = ref('') // 表单的类型：create - 新增；update - 修改
const formData = ref({
  id: undefined,
  provinceName: undefined,
  cityName: undefined,
  provinceAdCode: undefined,
  provinceCenter: undefined,
  cityCode: undefined,
  cityAdCode: undefined,
  cityCenter: undefined,
  districts: undefined,
  isoCode: undefined
})
const formRules = reactive({
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
      formData.value = await AreaCodeApi.getAreaCode(id)
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
    const data = formData.value as unknown as AreaCode
    if (formType.value === 'create') {
      await AreaCodeApi.createAreaCode(data)
      message.success(t('common.createSuccess'))
    } else {
      await AreaCodeApi.updateAreaCode(data)
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
    provinceName: undefined,
    cityName: undefined,
    provinceAdCode: undefined,
    provinceCenter: undefined,
    cityCode: undefined,
    cityAdCode: undefined,
    cityCenter: undefined,
    districts: undefined,
    isoCode: undefined
  }
  formRef.value?.resetFields()
}
</script>