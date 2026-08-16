<template>
  <div class="min-h-screen flex items-center justify-center px-4">
    <div class="card w-full max-w-md">
      <h1 class="text-2xl font-bold text-accent mb-1">SysCenter</h1>
      <p class="text-sm text-gray-400 mb-6">系统综合管理中心 · 二次验证登录</p>

      <div v-if="setup.setup_open" class="mb-6 p-3 rounded-lg border border-edge bg-panel2">
        <p class="text-xs text-gray-400 mb-2">首次使用：用验证器 App（Google Authenticator / 1Password / Authy）扫描下方二维码绑定（仅显示一次）</p>
        <div v-if="setup.qr" class="flex justify-center mb-3">
          <img :src="setup.qr" alt="OTP 绑定二维码" class="w-44 h-44 rounded bg-white" />
        </div>
        <p class="text-xs break-all text-accent2">otpauth: {{ setup.otpauth_uri || '...' }}</p>
        <p class="text-sm mt-2">密钥（扫码失败可手填）：<code class="text-accent">{{ setup.secret }}</code></p>
      </div>

      <label class="text-sm text-gray-300">6 位动态码（OTP）</label>
      <input v-model="otp" class="input mt-2 text-center tracking-[0.5em] text-lg" maxlength="6" placeholder="••••••" />
      <button class="btn btn-primary w-full mt-4" :disabled="loading" @click="login">
        {{ loading ? '验证中…' : '登录' }}
      </button>
      <p v-if="err" class="text-danger text-sm mt-3">{{ err }}</p>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import api, { setToken } from '../api.js'

const otp = ref('')
const err = ref('')
const loading = ref(false)
const setup = ref({ setup_open: false, otpauth_uri: '', secret: '' })

onMounted(async () => {
  try {
    const r = await api.get('/auth/setup')
    setup.value = r.data
  } catch (e) { /* ignore */ }
})

async function login() {
  err.value = ''
  loading.value = true
  try {
    const r = await api.post('/auth/login', { otp: otp.value })
    setToken(r.data.token)
    location.hash = '#/'
  } catch (e) {
    err.value = (e.response && e.response.data && e.response.data.detail) || '登录失败'
  } finally {
    loading.value = false
  }
}
</script>
