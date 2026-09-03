<template>
  <Dialog :title="dialogTitle" v-model="dialogVisible">
    <el-form
      ref="formRef"
      :model="formData"
      label-width="100px"
      v-loading="formLoading"
    >
      <el-form-item label="呼叫唯一ID" prop="callId">
        <el-input v-model="formData.callId" disabled />
      </el-form-item>
      <el-form-item label="主叫号码" prop="callerNumber">
        <el-input v-model="formData.callerNumber" disabled />
      </el-form-item>
      <el-form-item label="主叫显号" prop="callerDisplayNumber">
        <el-input v-model="formData.callerDisplayNumber" disabled />
      </el-form-item>
      <el-form-item label="被叫号码" prop="calleeNumber">
        <el-input v-model="formData.calleeNumber" disabled />
      </el-form-item>
      <el-form-item label="被叫显号" prop="calleeDisplayNumber">
        <el-input v-model="formData.calleeDisplayNumber" disabled />
      </el-form-item>
      <el-form-item label="号码归属地" prop="numberLocation">
        <el-input v-model="formData.numberLocation" disabled />
      </el-form-item>
      <el-form-item label="坐席ID" prop="agentId">
        <el-input v-model="formData.agentId" disabled />
      </el-form-item>
      <el-form-item label="坐席号码" prop="agentNumber">
        <el-input v-model="formData.agentNumber" disabled />
      </el-form-item>
      <el-form-item label="坐席名称" prop="agentName">
        <el-input v-model="formData.agentName" disabled />
      </el-form-item>
      <el-form-item label="呼叫状态" prop="callState">
        <dict-tag :type="DICT_TYPE.CC_CALL_STATE" :value="formData.callState" />
      </el-form-item>
      <el-form-item label="呼叫方式" prop="direction">
        <dict-tag :type="DICT_TYPE.CC_CALL_DIRECTION" :value="formData.direction" />
      </el-form-item>
      <el-form-item label="呼叫开始时间" prop="callStartTime">
        <el-date-picker
          v-model="formData.callStartTime"
          type="datetime"
          value-format="YYYY-MM-DD HH:mm:ss"
          placeholder="呼叫开始时间"
          disabled
        />
      </el-form-item>
      <el-form-item label="呼叫结束时间" prop="callEndTime">
        <el-date-picker
          v-model="formData.callEndTime"
          type="datetime"
          value-format="YYYY-MM-DD HH:mm:ss"
          placeholder="呼叫结束时间"
          disabled
        />
      </el-form-item>
      <el-form-item label="应答标识" prop="answerFlag">
        <dict-tag :type="DICT_TYPE.CC_CALL_ANSWER_FLAG" :value="formData.answerFlag" />
      </el-form-item>
      <el-form-item label="呼叫接通时间" prop="answerTime">
        <el-date-picker
          v-model="formData.answerTime"
          type="datetime"
          value-format="YYYY-MM-DD HH:mm:ss"
          placeholder="呼叫接通时间"
          disabled
        />
      </el-form-item>
      <el-form-item label="振铃时间" prop="ringingTime">
        <el-date-picker
          v-model="formData.ringingTime"
          type="datetime"
          value-format="YYYY-MM-DD HH:mm:ss"
          placeholder="振铃时间"
          disabled
        />
      </el-form-item>
      <el-form-item label="挂机方向" prop="hangupDir">
        <dict-tag :type="DICT_TYPE.CC_CALL_HANGUP_DIR" :value="formData.hangupDir" />
      </el-form-item>
      <el-form-item label="挂机原因" prop="hangupCauseCode">
        <el-input v-model="formData.hangupCauseCode" disabled />
      </el-form-item>
      <el-form-item label="录音文件地址" prop="filePath">
        <el-input v-model="formData.filePath" disabled />
      </el-form-item>
      <el-form-item label="振铃文件地址" prop="ringingPath">
        <el-input v-model="formData.ringingPath" disabled />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="dialogVisible = false">关 闭</el-button>
    </template>
  </Dialog>
</template>
<script setup lang="ts">
import { CallRecordApi } from '@/api/cc/callrecord'
import { DICT_TYPE } from '@/utils/dict'

/** cc 呼叫记录 详情表单（只读查看） */
defineOptions({ name: 'CallRecordForm' })

const { t } = useI18n() // 国际化

const dialogVisible = ref(false) // 弹窗的是否展示
const dialogTitle = ref('') // 弹窗的标题
const formLoading = ref(false) // 表单的加载中：详情数据加载
const formData = ref({
  id: undefined,
  callId: undefined,
  callerNumber: undefined,
  callerDisplayNumber: undefined,
  calleeNumber: undefined,
  calleeDisplayNumber: undefined,
  numberLocation: undefined,
  agentId: undefined,
  agentNumber: undefined,
  agentName: undefined,
  callState: undefined,
  direction: undefined,
  callStartTime: undefined,
  callEndTime: undefined,
  answerFlag: undefined,
  answerTime: undefined,
  ringingTime: undefined,
  hangupDir: undefined,
  hangupCauseCode: undefined,
  filePath: undefined,
  ringingPath: undefined
})
const formRef = ref() // 表单 Ref

/** 打开弹窗：仅支持 detail 类型，展示只读详情 */
const open = async (type: string, id?: number) => {
  dialogVisible.value = true
  dialogTitle.value = t('action.' + type)
  resetForm()
  // 详情查看时，根据 id 加载数据
  if (id) {
    formLoading.value = true
    try {
      formData.value = await CallRecordApi.getCallRecord(id)
    } finally {
      formLoading.value = false
    }
  }
}
defineExpose({ open }) // 提供 open 方法，用于打开弹窗

/** 重置表单 */
const resetForm = () => {
  formData.value = {
    id: undefined,
    callId: undefined,
    callerNumber: undefined,
    callerDisplayNumber: undefined,
    calleeNumber: undefined,
    calleeDisplayNumber: undefined,
    numberLocation: undefined,
    agentId: undefined,
    agentNumber: undefined,
    agentName: undefined,
    callState: undefined,
    direction: undefined,
    callStartTime: undefined,
    callEndTime: undefined,
    answerFlag: undefined,
    answerTime: undefined,
    ringingTime: undefined,
    hangupDir: undefined,
    hangupCauseCode: undefined,
    filePath: undefined,
    ringingPath: undefined
  }
  formRef.value?.resetFields()
}
</script>
