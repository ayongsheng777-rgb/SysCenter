<template>
  <div class="min-h-screen">
    <Login v-if="!loggedIn || route === 'login'" />

    <div v-else class="max-w-6xl mx-auto px-4 py-4">
      <header class="flex items-center justify-between mb-4">
        <div class="flex items-center gap-2">
          <span class="text-accent text-xl font-bold">⚡ SysCenter</span>
          <span class="text-xs text-gray-500">系统综合管理中心</span>
        </div>
        <button class="btn text-xs" @click="logout">退出登录</button>
      </header>

      <nav class="flex flex-wrap gap-2 mb-4">
        <div v-for="t in tabs" :key="t.key" class="nav-item" :class="{ active: route === t.key }" @click="go(t.key)">{{ t.label }}</div>
      </nav>

      <component :is="current" ref="currentRef" />
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import api, { getToken, setToken } from './api.js'
import Login from './components/Login.vue'
import Health from './components/Health.vue'
import Network from './components/Network.vue'
import Vps from './components/Vps.vue'
import Services from './components/Services.vue'
import Diagnose from './components/Diagnose.vue'
import Settings from './components/Settings.vue'
import Automation from './components/Automation.vue'
import Alerts from './components/Alerts.vue'
import TodoExperience from './components/TodoExperience.vue'
import Notes from './components/Notes.vue'
import Audit from './components/Audit.vue'

const tabs = [
  { key: '', label: '概览' }, { key: 'network', label: '网络/资产' },
  { key: 'vps', label: 'VPS矩阵' }, { key: 'services', label: '服务' },
  { key: 'diagnose', label: 'AI诊断' }, { key: 'automation', label: '自动化' },
  { key: 'alerts', label: '告警' }, { key: 'todos', label: '待办/经验' },
  { key: 'notes', label: '笔记/知识库' },
  { key: 'audit', label: '审计' }, { key: 'settings', label: '设置' },
]
const map = { '': Health, network: Network, vps: Vps, services: Services, diagnose: Diagnose, automation: Automation, alerts: Alerts, todos: TodoExperience, notes: Notes, audit: Audit, settings: Settings }

const route = ref(location.hash.replace('#/', '') || '')
const loggedIn = ref(!!getToken())
const currentRef = ref(null)

const current = computed(() => map[route.value] || Health)

function go(k) { location.hash = k ? '#/' + k : '#/' }
async function logout() {
  // 先通知后端吊销服务端令牌，再清本地（即便接口失败也强制退出）
  try { await api.post('/auth/logout') } catch (e) { /* 忽略 */ }
  setToken(''); loggedIn.value = false; location.hash = '#/login'
}

// 用浏览器原生 hashchange 事件监听地址栏变化。
// Vue 的 watch(() => location.hash) 盯不住非响应式变量，导致点导航/登录后页面不切换，只能 F5。
function onHashChange() {
  route.value = location.hash.replace('#/', '') || ''
  loggedIn.value = !!getToken()
}
window.addEventListener('hashchange', onHashChange)

onMounted(() => {
  onHashChange() // 首次进入先按地址栏同步一次状态
  // 令牌存在但可能已失效：访问一个需鉴权的接口探活。
  // 仅当明确 401（令牌失效）才弹回登录；其它错误（500/网络抖动）不踢人。
  if (loggedIn.value) {
    api.get('/system/health').catch((e) => {
      if (e.response && e.response.status === 401) { loggedIn.value = false; location.hash = '#/login' }
    })
  }
})
</script>
