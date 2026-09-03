<template>
  <div class="playback-content">
    <div class="pc-row">
      <span class="pc-label">放音类型</span>
      <el-radio-group v-model="localForm.playbackType" @change="handlePlaybackTypeChange" size="small">
        <el-radio :value="PlaybackType.VOICE_FILE">语音文件</el-radio>
        <el-radio :value="PlaybackType.TEXT">文本内容</el-radio>
      </el-radio-group>
    </div>
    <div class="pc-row" v-if="localForm.playbackType === PlaybackType.VOICE_FILE">
      <span class="pc-label">语音文件</span>
      <el-select
        v-model="localForm.fileId"
        placeholder="请选择语音文件"
        clearable
        :teleported="true"
        size="small"
        class="pc-ctrl"
        :key="selectRenderKey"
      >
        <el-option :value="String(item.id)" :label="item.name" v-for="item in voiceOptions" :key="item.id" />
      </el-select>
    </div>
    <div class="pc-row" v-if="localForm.playbackType === PlaybackType.TEXT">
      <span class="pc-label">文本内容</span>
      <el-input
        type="textarea"
        v-model="localForm.content"
        placeholder="请输入文本内容"
        :rows="2"
        size="small"
        class="pc-ctrl"
      />
    </div>
    <div class="pc-row">
      <span class="pc-label">放音次数</span>
      <el-input-number
        v-model="localForm.num"
        :min="1"
        :max="100"
        size="small"
        controls-position="right"
      />
    </div>
  </div>
</template>

<script lang="ts">
import { defineComponent, PropType } from 'vue'
import { SysVoiceFileApi, SysVoiceFileVO } from '@/api/cc/sysvoicefile'
import { PlaybackType } from '@/views/cc/ivr/consts/ivrEnum'

/** 放音内容数据结构：放音类型 + 语音文件ID + 文本内容 + 放音次数 */
export interface PlaybackContentData {
  playbackType: number
  fileId: string
  content: string
  num: number
}

/**
 * 播放内容子组件
 * 封装放音类型单选、语音文件下拉、文本内容输入、放音次数，供各放音类节点复用
 * 通过 v-model:modelValue 双向绑定，使用本地响应式 localForm + watch 双向同步，
 * 避免"每次 computed getter 返回新对象导致 v-model 修改的是临时对象而丢失"的问题。
 */
export default defineComponent({
  name: 'PlaybackContent',
  props: {
    modelValue: {
      type: Object as PropType<PlaybackContentData>,
      default: () => ({ playbackType: PlaybackType.VOICE_FILE, fileId: '', content: '', num: 1 })
    }
  },
  emits: ['update:modelValue'],
  data() {
    const m = this.modelValue || ({} as PlaybackContentData)
    return {
      /** 放音类型枚举，供模板中使用 */
      PlaybackType,
      /** 本地响应式表单状态，所有 v-model 直接绑定此对象 */
      localForm: {
        playbackType: typeof m.playbackType === 'number' ? m.playbackType : PlaybackType.VOICE_FILE,
        fileId: m.fileId == null ? '' : String(m.fileId),
        content: typeof m.content === 'string' ? m.content : '',
        num: typeof m.num === 'number' && m.num > 0 ? m.num : 1
      } as PlaybackContentData,
      voiceOptions: [] as SysVoiceFileVO[],
      /** 防止两个 watch 相互触发造成的循环更新 */
      isSyncingFromProp: false,
      isSyncingToParent: false,
      /** el-select 动态 key：语音文件列表加载完成后 ++，强制 el-select 重新渲染，
       *  以便根据新加载的 options 正确匹配并显示 fileId 对应的文件名称 label，
       *  避免"先有 fileId 值后加载 options"时 el-select 只能显示 value 数字（ID）。 */
      selectRenderKey: 0
    }
  },
  watch: {
    /**
     * 父组件传值变化时同步到本地表单
     * - 先对新旧内容做规范化+深度比较，避免父组件 computed getter 每次返回新对象引用
     *   （但内容完全相同）造成不必要的同步覆盖 → 循环 emit → setProperties 重渲染节点
     * - 同步时设置 isSyncingFromProp 标志，避免 localForm 的 watch 又把旧值 emit 回去
     */
    modelValue: {
      deep: true,
      handler(val: PlaybackContentData | undefined | null) {
        if (this.isSyncingToParent) return
        const m = val || ({} as PlaybackContentData)

        /** 规范化字段：统一类型，便于与本地值比较 */
        const normalize = (v: any) => ({
          playbackType: typeof v.playbackType === 'number' ? v.playbackType : PlaybackType.VOICE_FILE,
          fileId: v.fileId == null ? '' : String(v.fileId),
          content: typeof v.content === 'string' ? v.content : '',
          num: typeof v.num === 'number' && v.num > 0 ? v.num : 1
        })
        const fromProp = normalize(m)
        const fromLocal = normalize(this.localForm)

        // 内容完全相同时跳过，避免父 computed 返回新对象引用导致的反复同步
        if (
          fromProp.playbackType === fromLocal.playbackType &&
          fromProp.fileId === fromLocal.fileId &&
          fromProp.content === fromLocal.content &&
          fromProp.num === fromLocal.num
        ) {
          return
        }

        this.isSyncingFromProp = true
        try {
          this.localForm.playbackType = fromProp.playbackType
          this.localForm.fileId = fromProp.fileId
          this.localForm.content = fromProp.content
          this.localForm.num = fromProp.num
        } finally {
          this.$nextTick(() => {
            this.isSyncingFromProp = false
          })
        }
      }
    },
    /**
     * 本地表单任何字段变化都同步给父组件
     * 跳过由父组件 prop 同步触发的本次变更，避免循环
     */
    localForm: {
      deep: true,
      handler() {
        if (this.isSyncingFromProp) return
        this.isSyncingToParent = true
        try {
          this.$emit('update:modelValue', { ...this.localForm })
        } finally {
          this.$nextTick(() => {
            this.isSyncingToParent = false
          })
        }
      }
    }
  },
  mounted() {
    this.getVoiceOption()
  },
  methods: {
    /** 加载语音文件列表，供放音类型为"语音文件"时下拉选择；加载完成后强制 el-select 重新渲染匹配 label */
    async getVoiceOption() {
      try {
        const list = await SysVoiceFileApi.getSysVoiceFileList()
        this.voiceOptions = list || []
      } catch (e) {
        console.error('加载语音文件列表失败', e)
        this.voiceOptions = []
      } finally {
        // voiceOptions 加载完成后，selectRenderKey++ 让 el-select 重新挂载，
        // 确保 el-select 能根据 options 匹配到 fileId 对应的 label（文件名），
        // 解决"回显时先有 fileId 值、后加载 options"导致 el-select 直接显示 value（ID 数字）的问题。
        this.$nextTick(() => {
          this.selectRenderKey++
        })
      }
    },
    /**
     * 放音类型切换时清空语音文件与文本内容
     * 直接修改本地响应式对象，由 watch deep 自动同步给父组件
     */
    handlePlaybackTypeChange() {
      this.localForm.fileId = ''
      this.localForm.content = ''
    }
  }
})
</script>
<style scoped>
.playback-content {
  width: 100%;
}
.pc-row {
  display: flex;
  align-items: center;
  margin-bottom: 8px;
  gap: 8px;
  font-size: 12px;
}
.pc-label {
  font-size: 12px;
  color: #4e5969;
  width: 72px;
  flex-shrink: 0;
  text-align: right;
  line-height: 28px;
}
.pc-ctrl {
  flex: 1;
  min-width: 0;
}
</style>
