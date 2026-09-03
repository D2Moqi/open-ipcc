<template>
  <Dialog :title="dialogTitle" v-model="dialogVisible" width="700">
    <el-form ref="formRef" :model="formData" :rules="formRules" label-width="120px" v-loading="formLoading">
      <el-row :gutter="20">
        <el-col :span="12">
          <el-form-item label="网关名称" prop="name">
            <el-input v-model="formData.name" placeholder="请输入网关名称" />
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="网关类型" prop="type">
            <el-select v-model="formData.type" placeholder="请选择网关类型" class="!w-full">
              <el-option label="内部网关" :value="1" />
              <el-option label="外部网关" :value="2" />
            </el-select>
          </el-form-item>
        </el-col>
      </el-row>
      <el-row :gutter="20">
        <el-col :span="12">
          <el-form-item label="注册模式" prop="registerEnabled">
            <el-select
              v-model="formData.registerEnabled"
              placeholder="请选择注册模式"
              class="!w-full"
              @change="handleRegisterModeChange"
            >
              <el-option
                v-for="dict in getIntDictOptions(DICT_TYPE.CC_SIPPROXY_GATEWAY_REGISTER_MODE)"
                :key="dict.value"
                :label="dict.label"
                :value="dict.value"
              />
            </el-select>
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="状态" prop="status">
            <el-select v-model="formData.status" placeholder="请选择状态" class="!w-full">
              <el-option
                v-for="dict in getIntDictOptions(DICT_TYPE.COMMON_STATUS)"
                :key="dict.value"
                :label="dict.label"
                :value="dict.value"
              />
            </el-select>
          </el-form-item>
        </el-col>
      </el-row>
      <!-- 注册模式专属字段：置于状态下边一行，直连模式隐藏 -->
      <el-row v-if="formData.registerEnabled === 1" :gutter="20">
        <el-col :span="12">
          <el-form-item label="注册域" prop="registerRealm">
            <el-input v-model="formData.registerRealm" placeholder="可空，缺省回退From域→sipproxy公网IP" />
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="注册有效期上限(秒)" prop="registerMaxExpires">
            <el-input-number
              v-model="formData.registerMaxExpires"
              :min="60"
              :max="86400"
              controls-position="right"
              class="!w-full"
              placeholder="可空，缺省7200"
            />
          </el-form-item>
        </el-col>
      </el-row>
      <el-row :gutter="20">
        <el-col :span="12">
          <el-form-item label="网关地址" prop="address">
            <el-input
              v-model="formData.address"
              :placeholder="formData.registerEnabled === 1 ? '注册模式可留空，由REGISTER自动学习' : '请输入网关地址(IP或域名)'"
            />
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="网关端口" prop="port">
            <el-input-number
              v-model="formData.port"
              :min="1"
              :max="65535"
              controls-position="right"
              class="!w-full"
              :placeholder="formData.registerEnabled === 1 ? '可空' : ''"
            />
          </el-form-item>
        </el-col>
      </el-row>
      <el-row :gutter="20">
        <el-col :span="12">
          <el-form-item label="代理回程IP" prop="toSipProxyIp">
            <el-input v-model="formData.toSipProxyIp" placeholder="可选，告知网关向该IP回送响应(默认sip.public-ip)" />
          </el-form-item>
        </el-col>
        <el-col :span="12" />
      </el-row>
      <el-row :gutter="20">
        <el-col :span="12">
          <el-form-item label="认证类型" prop="authType">
            <el-select v-model="formData.authType" placeholder="请选择认证类型" class="!w-full" @change="handleAuthTypeChange">
              <el-option label="不认证" :value="0" />
              <el-option label="密码认证" :value="1" />
            </el-select>
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="传输协议" prop="transportProtocol">
            <el-select v-model="formData.transportProtocol" placeholder="请选择传输协议" class="!w-full">
              <el-option label="UDP" :value="1" />
              <el-option label="TCP" :value="2" />
            </el-select>
          </el-form-item>
        </el-col>
      </el-row>
      <el-row v-if="formData.authType === 1" :gutter="20">
        <el-col :span="12">
          <el-form-item label="账户" prop="username">
            <el-input v-model="formData.username" placeholder="请输入认证账户" />
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="密码" prop="password">
            <el-input v-model="formData.password" placeholder="请输入认证密码" show-password />
          </el-form-item>
        </el-col>
      </el-row>
      <el-row :gutter="20">
        <el-col :span="12">
          <el-form-item label="外线号码(DID)" prop="externalLineNumber">
            <el-input v-model="formData.externalLineNumber" placeholder="请输入外线号码" />
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="From域" prop="fromDomain">
            <el-input v-model="formData.fromDomain" placeholder="请输入From域(可选)" />
          </el-form-item>
        </el-col>
      </el-row>
      <el-row :gutter="20">
        <el-col :span="12">
          <el-form-item label="CallerId显示" prop="callerIdInFrom">
            <el-radio-group v-model="formData.callerIdInFrom">
              <el-radio :value="0">显示真实主叫</el-radio>
              <el-radio :value="1">显示DID号码</el-radio>
            </el-radio-group>
          </el-form-item>
        </el-col>
      </el-row>
      <el-divider content-position="left">高级配置（可选）</el-divider>
      <el-row :gutter="20">
        <el-col :span="8">
          <el-form-item label="重试时间(秒)" prop="retrySeconds">
            <el-input-number v-model="formData.retrySeconds" :min="0" controls-position="right" class="!w-full" />
          </el-form-item>
        </el-col>
        <el-col :span="8">
          <el-form-item label="心跳时间(秒)" prop="pingSeconds">
            <el-input-number v-model="formData.pingSeconds" :min="0" controls-position="right" class="!w-full" />
          </el-form-item>
        </el-col>
        <el-col :span="8">
          <el-form-item label="超时时间(秒)" prop="expireSeconds">
            <el-input-number v-model="formData.expireSeconds" :min="0" controls-position="right" class="!w-full" />
          </el-form-item>
        </el-col>
      </el-row>
      <el-form-item label="备注" prop="remark">
        <el-input v-model="formData.remark" type="textarea" :rows="3" placeholder="请输入备注" />
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
import { SipProxyGatewayApi, SipProxyGatewayVO } from '@/api/cc/sipproxygateway'

defineOptions({ name: 'SipProxyGatewayForm' })

const { t } = useI18n()
const message = useMessage()

const dialogVisible = ref(false)
const dialogTitle = ref('')
const formLoading = ref(false)
const formType = ref('')
const formData = ref<SipProxyGatewayVO>({
  id: undefined,
  name: '',
  type: 2,
  address: '',
  port: 5060,
  toSipProxyIp: undefined,
  authType: 0,
  transportProtocol: 1,
  registerEnabled: 0,
  registerRealm: undefined,
  registerMaxExpires: undefined,
  authAddress: undefined,
  authPort: undefined,
  username: undefined,
  password: undefined,
  callerIdInFrom: 0,
  fromDomain: undefined,
  retrySeconds: undefined,
  pingSeconds: undefined,
  expireSeconds: undefined,
  externalLineNumber: undefined,
  status: 0,
  remark: undefined
})
const formRules = reactive({
  name: [{ required: true, message: '网关名称不能为空', trigger: 'blur' }],
  type: [{ required: true, message: '网关类型不能为空', trigger: 'change' }],
  address: [{
    validator: (rule: any, value: any, callback: any) => {
      // 注册模式(自动学习地址)可留空；直连模式必填
      if (formData.value.registerEnabled !== 1 && (!value || value === '')) {
        callback(new Error('直连模式网关地址不能为空'))
      } else {
        callback()
      }
    },
    trigger: 'blur'
  }],
  port: [{
    validator: (rule: any, value: any, callback: any) => {
      if (formData.value.registerEnabled !== 1 && (!value || value <= 0)) {
        callback(new Error('直连模式网关端口不能为空'))
      } else {
        callback()
      }
    },
    trigger: 'blur'
  }],
  authType: [{ required: true, message: '认证类型不能为空', trigger: 'change' }],
  transportProtocol: [{ required: true, message: '传输协议不能为空', trigger: 'change' }],
  registerEnabled: [{ required: true, message: '注册模式不能为空', trigger: 'change' }],
  callerIdInFrom: [{ required: true, message: 'CallerId显示方式不能为空', trigger: 'change' }],
  status: [{ required: true, message: '状态不能为空', trigger: 'change' }],
  username: [{
    validator: (rule: any, value: any, callback: any) => {
      if (formData.value.authType === 1 && (!value || value === '')) {
        callback(new Error('认证型网关账户不能为空'))
      } else {
        callback()
      }
    },
    trigger: 'blur'
  }],
  password: [{
    validator: (rule: any, value: any, callback: any) => {
      if (formData.value.authType === 1 && (!value || value === '')) {
        callback(new Error('认证型网关密码不能为空'))
      } else {
        callback()
      }
    },
    trigger: 'blur'
  }],
  registerRealm: [{
    validator: (rule: any, value: any, callback: any) => {
      // 注册域可空（缺省回退 from_domain → sipproxy 公网 IP），仅做长度校验
      if (value && value.length > 128) {
        callback(new Error('注册域长度不能超过128字符'))
      } else {
        callback()
      }
    },
    trigger: 'blur'
  }]
})
const formRef = ref()

const open = async (type: string, id?: number) => {
  dialogVisible.value = true
  dialogTitle.value = t('action.' + type)
  formType.value = type
  resetForm()
  if (id) {
    formLoading.value = true
    try {
      formData.value = await SipProxyGatewayApi.getSipProxyGateway(id)
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
    const data = formData.value as SipProxyGatewayVO
    // 不认证网关：强制置空账户密码(null 才会被 JSON 序列化传给后端，防止数据库残留旧值)
    if (data.authType !== 1) {
      data.username = null
      data.password = null
    }
    if (formType.value === 'create') {
      await SipProxyGatewayApi.createSipProxyGateway(data)
      message.success(t('common.createSuccess'))
    } else {
      await SipProxyGatewayApi.updateSipProxyGateway(data)
      message.success(t('common.updateSuccess'))
    }
    dialogVisible.value = false
    emit('success')
  } finally {
    formLoading.value = false
  }
}

const handleAuthTypeChange = (value: number) => {
  // 切换到不认证时清空账户/密码，避免残留上一认证配置的数据
  if (value !== 1) {
    formData.value.username = null
    formData.value.password = null
    // 注册模式依赖密码认证（REGISTER Digest 401 挑战），切到不认证时强制回直连并清理注册配置
    if (formData.value.registerEnabled === 1) {
      formData.value.registerEnabled = 0
      formData.value.registerRealm = undefined
      formData.value.registerMaxExpires = undefined
    }
  }
}

/**
 * 注册模式联动：
 * - 切到注册模式(1)：强制密码认证（注册认证依赖账户密码），暂时隐藏并暂存直连地址/端口（REGISTER 自动学习）
 * - 切回直连(0)：清空注册域/注册有效期上限，恢复暂存的地址/端口（误触切换不丢配置），端口兜底 5060
 */
// 直连模式地址/端口暂存（切到注册模式时保存，切回直连时恢复，防误触切换丢失用户输入）
let savedDirectAddress = ''
let savedDirectPort: number | undefined = undefined

const handleRegisterModeChange = (value: number) => {
  if (value === 1) {
    formData.value.authType = 1
    savedDirectAddress = formData.value.address || ''
    savedDirectPort = formData.value.port
    formData.value.address = undefined
    formData.value.port = undefined
  } else {
    formData.value.registerRealm = undefined
    formData.value.registerMaxExpires = undefined
    // 恢复切换前的直连地址/端口（地址原样恢复，端口兜底 5060）
    formData.value.address = savedDirectAddress || undefined
    formData.value.port = savedDirectPort ?? 5060
    savedDirectAddress = ''
    savedDirectPort = undefined
  }
}

const resetForm = () => {
  formData.value = {
    id: undefined,
    name: '',
    type: 2,
    address: '',
    port: 5060,
    toSipProxyIp: undefined,
    authType: 0,
    transportProtocol: 1,
    registerEnabled: 0,
    registerRealm: undefined,
    registerMaxExpires: undefined,
    authAddress: undefined,
    authPort: undefined,
    username: undefined,
    password: undefined,
    callerIdInFrom: 0,
    fromDomain: undefined,
    retrySeconds: undefined,
    pingSeconds: undefined,
    expireSeconds: undefined,
    externalLineNumber: undefined,
    status: 0,
    remark: undefined
  }
  // 重置暂存的直连地址/端口，避免跨表单残留
  savedDirectAddress = ''
  savedDirectPort = undefined
  formRef.value?.resetFields()
}
</script>
