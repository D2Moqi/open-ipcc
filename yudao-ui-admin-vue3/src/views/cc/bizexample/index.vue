<template>
  <ContentWrap title="业务示例">
    <!-- 通话信息卡片：展示当前通话的核心信息 -->
    <el-card class="biz-example__card" shadow="never">
      <template #header>
        <div class="flex items-center justify-between">
          <span class="font-bold text-14px">当前通话信息</span>
          <el-tag effect="dark" type="success">通话中</el-tag>
        </div>
      </template>

      <el-descriptions :column="2" border class="!mt-16px">
        <el-descriptions-item label="通话 ID">
          <span class="font-mono">{{ callId || '-' }}</span>
        </el-descriptions-item>
        <el-descriptions-item label="呼叫方向">
          {{ directionText }}
        </el-descriptions-item>
        <el-descriptions-item label="主叫电话">
          <el-tag type="primary">{{ number || '-' }}</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="通话时间">
          {{ currentTime }}
        </el-descriptions-item>
      </el-descriptions>
    </el-card>

    <!-- 业务场景联动：来电触发工单 / 客户 / 销售系统等业务入口 -->
    <el-card class="biz-example__card" shadow="never">
      <template #header>
        <div class="flex items-center justify-between">
          <span class="font-bold text-14px">业务场景联动</span>
          <el-tag size="small" type="info">来电触发</el-tag>
        </div>
      </template>

      <el-alert
        :closable="false"
        class="!mb-16px"
        show-icon
        title="电话呼入后，系统在标签页打开本页面，展示当前通话信息，并可根据主叫号码联动到工单、客户、销售等业务系统。"
        type="info"
      />

      <el-row :gutter="16">
        <el-col v-for="action in sceneActions" :key="action.key" :span="8">
          <el-card class="biz-example__scene" shadow="hover">
            <div class="flex flex-col items-center gap-8px py-12px">
              <el-icon :color="action.color" :size="28">
                <component :is="action.icon" />
              </el-icon>
              <span class="text-14px font-bold">{{ action.label }}</span>
              <span class="text-12px text-gray-400">{{ action.desc }}</span>
              <el-button link type="primary" @click="handleSceneAction(action.key)">
                打开{{ action.label }}
              </el-button>
            </div>
          </el-card>
        </el-col>
      </el-row>
    </el-card>

    <!-- 页面操作：关闭本页（仅关闭当前指定标签页，不影响同名其它标签页） -->
    <div class="flex justify-end pt-8px">
      <el-button plain type="danger" @click="handleClosePage">
        <el-icon class="mr-4px"><Close /></el-icon>
        关闭本页
      </el-button>
    </div>
  </ContentWrap>
</template>

<script lang="ts" setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useTagsView } from '@/hooks/web/useTagsView'
import { useTagsViewStore } from '@/store/modules/tagsView'
import { Sell, Ticket, User } from '@element-plus/icons-vue'

defineOptions({ name: 'CcBizExample' })

/** 当前路由（用于读取并汇总标签页冲突处理所需的 query 参数） */
const route = useRoute()
const router = useRouter()
const { closeCurrent } = useTagsView()
const tagsViewStore = useTagsViewStore()

/**
 * 业务示例页面通过路由 query 参数获取通话上下文：
 * - callId：当前通话的唯一标识（JsSIP session.id），作为标签页去重/关闭的锚点
 * - number：主叫电话
 * - direction：呼叫方向（呼入/呼出）
 * 每个来电使用各自 callId 作为 fullPath 之一部分，从而保证同名页面可开多个，
 * 且相互独立（关闭其中一个不影响其它）。
 */
const callId = computed<string>(() => (route.query.callId as string) || '')
const number = computed<string>(() => (route.query.number as string) || '')
const direction = computed<string>(() => (route.query.direction as string) || 'incoming')

/** 呼叫方向文案 */
const directionText = computed<string>(() => (direction.value === 'outgoing' ? '呼出' : '呼入'))

/** 当前时间，按秒刷新，示意通话进行中 */
const currentTime = ref<string>(formatNow())
let timer: ReturnType<typeof setInterval> | null = null

function formatNow(): string {
  const d = new Date()
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

/** 场景联动配置：来电后可在工单 / 客户 / 销售等系统间跳转 */
const sceneActions = [
  {
    key: 'ticket',
    label: '工单',
    desc: '根据来电快速创建/关联工单',
    icon: Ticket,
    color: '#409EFF'
  },
  {
    key: 'customer',
    label: '客户',
    desc: '来电弹屏定位客户资料',
    icon: User,
    color: '#67C23A'
  },
  {
    key: 'sales',
    label: '销售系统',
    desc: '衔接商机与销售流程',
    icon: Sell,
    color: '#E6A23C'
  }
]

/**
 * 场景联动占位处理
 * <p>
 * 业务背景：本页面为「业务示例」，用于演示来电触发工单 / 客户 / 销售等业务场景的
 * 交互入口，故此处仅做占位提示，不实际调用后端方法。
 * </p>
 */
const handleSceneAction = (key: string) => {
  const action = sceneActions.find((s) => s.key === key)
  ElMessage.info(`【示例】已触发「${action?.label}」场景联动（当前为占位交互，未调用后端接口）`)
}

/**
 * 关闭本页
 * <p>
 * 关闭行为要求：仅关闭「当前」标签页，不能因页面名称相同而关闭其它同名标签页。
 * useTagsView().closeCurrent() 基于当前路由 fullPath（含 callId）精确删除，
 * 满足同一页面可开多个、互不干扰、按需逐个关闭的要求。
 * </p>
 * <p>
 * 说明：closeCurrent() 仅移除标签栏项，并不负责路由跳转；若关闭的恰好是当前激活标签，
 * 还需主动跳转到剩余标签（默认取最后一个）或首页，否则会出现「标签已关、页面仍停留」的问题。
 * </p>
 */
const handleClosePage = () => {
  closeCurrent()
  const views = tagsViewStore.getVisitedViews
  const latest = views[views.length - 1]
  if (latest) {
    router.push(latest)
  } else {
    router.push('/')
  }
}

onMounted(() => {
  timer = setInterval(() => {
    currentTime.value = formatNow()
  }, 1000)
})

onBeforeUnmount(() => {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
})
</script>

<style lang="scss" scoped>
.biz-example {
  &__card {
    margin-bottom: 16px;
  }

  &__scene {
    text-align: center;

    :deep(.el-card__body) {
      padding: 8px 12px;
    }
  }
}
</style>
