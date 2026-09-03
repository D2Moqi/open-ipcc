<template>
  <ContentWrap>
    <!-- 搜索工作栏 -->
    <el-form
      class="-mb-15px"
      :model="queryParams"
      ref="queryFormRef"
      :inline="true"
      label-width="68px"
    >
      <el-form-item label="名称" prop="name">
        <el-input
          v-model="queryParams.name"
          placeholder="请输入名称"
          clearable
          @keyup.enter="handleQuery"
          class="!w-240px"
        />
      </el-form-item>
      <el-form-item>
        <el-button @click="handleQuery"><Icon icon="ep:search" class="mr-5px" /> 搜索</el-button>
        <el-button @click="resetQuery"><Icon icon="ep:refresh" class="mr-5px" /> 重置</el-button>
        <el-button
          type="primary"
          plain
          @click="openForm('create')"
          v-hasPermi="['cc:fs-acl:create']"
        >
          <Icon icon="ep:plus" class="mr-5px" /> 新增
        </el-button>
        <el-button
          type="success"
          plain
          @click="handleExport"
          :loading="exportLoading"
          v-hasPermi="['cc:fs-acl:export']"
        >
          <Icon icon="ep:download" class="mr-5px" /> 导出
        </el-button>
        <el-button plain type="danger" @click="toggleExpandAll">
          <Icon class="mr-5px" icon="ep:sort" />
          展开/折叠
        </el-button>
        <el-button
          type="warning"
          plain
          @click="handleReloadAclConfig"
          :loading="reloadLoading"
          v-hasPermi="['cc:fs-acl:update']"
        >
          <Icon icon="ep:refresh-right" class="mr-5px" /> 重载ACL配置
        </el-button>
      </el-form-item>
    </el-form>
  </ContentWrap>

  <!-- 列表 -->
  <ContentWrap>
    <el-auto-resizer>
      <template #default="{ width }">
        <el-table-v2
          v-model:expanded-row-keys="expandedRowKeys"
          :columns="columns"
          :data="list"
          :expand-column-key="columns[0].key"
          :height="1000"
          :width="width"
          fixed
          row-key="id"
        />
      </template>
    </el-auto-resizer>
  </ContentWrap>

  <!-- 表单弹窗：添加/修改 -->
  <FsAclForm ref="formRef" @success="getList" />
</template>

<script lang="tsx" setup>
import { handleTree } from '@/utils/tree'
import download from '@/utils/download'
import request from '@/config/axios'
import { FsAclApi, FsAclVO } from '@/api/cc/fsacl'
import FsAclForm from './FsAclForm.vue'
import { ElButton, TableV2FixedDir } from 'element-plus'
import { checkPermi } from '@/utils/permission'
import { Icon } from '@/components/Icon'
import {DICT_TYPE} from "@/utils/dict";

/** cc freeSwitch访问控制 列表 */
defineOptions({ name: 'FsAcl' })

// 虚拟列表表格
const columns = [
  {
    key: 'name',
    title: '名称',
    dataKey: 'name',
    width: 250,
  },
  {
    key: 'cidr',
    title: 'IP地址',
    dataKey: 'cidr',
    width: 250,
  },
  {
    key: 'domain',
    title: '域地址',
    dataKey: 'domain',
    width: 250,
  },
  {
    key: 'remark',
    title: '备注',
    dataKey: 'remark',
    width: 250,
  },
  {
    key: 'type',
    title: '类型',
    dataKey: 'type',
    width: 80,
    fixed: TableV2FixedDir.RIGHT,
    cellRenderer: ({ rowData }) => {
      return <DictTag type={DICT_TYPE.CC_FS_ACL_TYPE} value={rowData.type} />
    }
  },
  {
    key: 'operations',
    title: '操作',
    align: 'center',
    width: 160,
    fixed: TableV2FixedDir.RIGHT,
    cellRenderer: ({ rowData }) => {
      // 定义按钮列表
      const buttons: InstanceType<typeof ElButton>[] = []

      // 检查权限并添加按钮
      if (checkPermi(['cc:fs-acl:update'])) {
        buttons.push(
          <ElButton key="edit" link type="primary" onClick={() => openForm('update', rowData.id)}>
            修改
          </ElButton>
        )
      }
      if (checkPermi(['cc:fs-acl:create'])) {
        buttons.push(
          <ElButton
            key="create"
            link
            type="primary"
            onClick={() => openForm('create', undefined, rowData.id)}
          >
            新增
          </ElButton>
        )
      }
      if (checkPermi(['cc:fs-acl:delete'])) {
        buttons.push(
          <ElButton key="delete" link type="danger" onClick={() => handleDelete(rowData.id)}>
            删除
          </ElButton>
        )
      }
      // 如果没有权限，返回 null
      if (buttons.length === 0) {
        return null
      }
      // 渲染按钮列表
      return <>{buttons}</>
    }
  }
]

const message = useMessage() // 消息弹窗
const { t } = useI18n() // 国际化

const loading = ref(true) // 列表的加载中
const list = ref<FsAclVO[]>([]) // 列表的数据
const queryParams = reactive({
  createTime: [],
  name: undefined,
  defaultType: undefined,
  listId: undefined,
  nodeType: undefined,
  cidr: undefined,
  domain: undefined
})
const queryFormRef = ref() // 搜索的表单
const exportLoading = ref(false) // 导出的加载中
const reloadLoading = ref(false) // 重载ACL配置的加载中

// 添加展开行控制
const expandedRowKeys = ref<number[]>([])

/** 查询列表 */
const getList = async () => {
  loading.value = true
  try {
    const data = await FsAclApi.getFsAclList(queryParams)
    list.value = handleTree(data, 'id', 'listId')
  } finally {
    loading.value = false
  }
}

/** 搜索按钮操作 */
const handleQuery = () => {
  getList()
}

/** 重置按钮操作 */
const resetQuery = () => {
  queryFormRef.value.resetFields()
  handleQuery()
}

/** 添加/修改操作 */
const formRef = ref()
const openForm = (type: string, id?: number, parentId?: number) => {
  formRef.value.open(type, id, parentId)
}

/** 删除按钮操作 */
const handleDelete = async (id: number) => {
  try {
    // 删除的二次确认
    await message.delConfirm()
    // 发起删除
    await FsAclApi.deleteFsAcl(id)
    message.success(t('common.delSuccess'))
    // 刷新列表
    await getList()
  } catch {}
}

/** 导出按钮操作 */
const handleExport = async () => {
  try {
    // 导出的二次确认
    await message.exportConfirm()
    // 发起导出
    exportLoading.value = true
    const data = await FsAclApi.exportFsAcl(queryParams)
    download.excel(data, 'cc freeSwitch访问控制.xls')
  } catch {
  } finally {
    exportLoading.value = false
  }
}

/** 展开/折叠操作 */
const isExpandAll = ref(true) // 是否展开，默认全部展开
const toggleExpandAll = () => {
  if (!isExpandAll.value) {
    // 展开所有
    expandedRowKeys.value = list.value.map((item) => item.id)
  } else {
    // 折叠所有
    expandedRowKeys.value = []
  }
  isExpandAll.value = !isExpandAll.value
}

/** 重载ACL配置 */
const handleReloadAclConfig = async () => {
  try {
    await message.confirm('确认重载所有FreeSWITCH的ACL配置？此操作将在所有已连接的FS节点执行reloadacl命令。')
  } catch {
    return
  }
  reloadLoading.value = true
  try {
    const data = await request.get({ url: '/cc/esl-command/reload-acl-config' })
    const connectedFsCount = data.connectedFsCount || 0
    const successCount = data.successCount || 0
    const failCount = data.failCount || 0
    const allSuccess = data.allSuccess
    let msg = `ACL重载完成！共${connectedFsCount}个FS节点：成功${successCount}个，失败${failCount}个`
    if (allSuccess) {
      message.success(msg)
    } else {
      message.warning(msg)
      console.log('[重载ACL配置]详细结果:', data)
    }
  } catch (e) {
    message.error('重载ACL配置失败: ' + (e as Error).message)
  } finally {
    reloadLoading.value = false
  }
}

/** 初始化 **/
onMounted(() => {
  getList()
})
</script>
