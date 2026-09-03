<template>
  <Dialog :title="dialogTitle" v-model="dialogVisible">
    <el-form
      ref="formRef"
      :model="formData"
      :rules="formRules"
      label-width="100px"
      v-loading="formLoading"
    >
      <el-form-item label="上级" prop="listId">
      <el-tree-select
        v-model="formData.listId"
        :data="fsAclTree"
        :default-expanded-keys="[0]"
        :props="defaultProps"
        check-strictly
        node-key="id"
        placeholder="请选择列表ID"
      />
    </el-form-item>
      <el-form-item v-if="formData.listId == 0"  label="名称" prop="name">
        <el-input v-model="formData.name" placeholder="请输入名称" />
      </el-form-item>
      <el-form-item label="类型" prop="type">
        <el-select v-model="formData.type" placeholder="请选择类型">
          <el-option
            v-for="dict in getStrDictOptions(DICT_TYPE.CC_FS_ACL_TYPE)"
            :key="dict.value"
            :label="dict.label"
            :value="dict.value"
          />
        </el-select>
      </el-form-item>
      <el-form-item label="建议：" prop="type">
        <el-text class="mx-1" type="info">类型选择时，顶层建议选拒绝，会拒绝所有未匹配到的ip，子项可以选允许</el-text>
      </el-form-item>
      <el-form-item v-if="formData.listId != 0" label="IP地址" prop="cidr">
        <el-input v-model="formData.cidr" placeholder="请输入IP地址" />
      </el-form-item>
      <el-form-item v-if="formData.listId != 0" label="域地址" prop="domain">
        <el-input v-model="formData.domain" placeholder="请输入域地址" />
      </el-form-item>
      <el-form-item  label="备注" prop="remark">
        <el-input v-model="formData.remark" placeholder="请输入备注" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="submitForm" type="primary" :disabled="formLoading">确 定</el-button>
      <el-button @click="dialogVisible = false">取 消</el-button>
    </template>
  </Dialog>
</template>
<script setup lang="ts">
import { FsAcl, FsAclApi } from '@/api/cc/fsacl'
import { defaultProps, handleTree } from '@/utils/tree'
import { DICT_TYPE, getStrDictOptions } from '@/utils/dict'

/** cc freeSwitch访问控制 表单 */
defineOptions({ name: 'FsAclForm' })

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
  listId: 0,
  cidr: undefined,
  domain: undefined,
  remark: undefined
})
const formRules = reactive({
  listId: [{ required: true, message: '列表ID不能为空', trigger: 'blur' }]
})
const formRef = ref() // 表单 Ref
const fsAclTree = ref() // 树形结构

/** 打开弹窗 */
const open = async (type: string, id?: number, parentId?: number) => {
  dialogVisible.value = true
  dialogTitle.value = t('action.' + type)
  formType.value = type
  resetForm()
  if (parentId) {
    formData.value.listId = parentId
  }
  // 修改时，设置数据
  if (id) {
    formLoading.value = true
    try {
      formData.value = await FsAclApi.getFsAcl(id)
    } finally {
      formLoading.value = false
    }
  }
  await getFsAclTree()
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
    const data = formData.value as unknown as FsAcl
    if (formType.value === 'create') {
      await FsAclApi.createFsAcl(data)
      message.success(t('common.createSuccess'))
    } else {
      await FsAclApi.updateFsAcl(data)
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
    listId: 0,
    cidr: undefined,
    domain: undefined,
    remark: undefined
  }
  formRef.value?.resetFields()
}

/** 获得cc freeSwitch访问控制树 */
const getFsAclTree = async () => {
  fsAclTree.value = []
  const data = await FsAclApi.getFsAclList()
  const root: Tree = { id: 0, name: '顶级', children: [] }
  root.children = handleTree(data, 'id', 'listId')
  fsAclTree.value.push(root)
}
</script>
