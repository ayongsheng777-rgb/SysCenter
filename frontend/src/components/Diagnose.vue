<template>
  <div class="space-y-4">
    <h2 class="text-lg font-semibold text-accent">AI 智能诊断</h2>
    <div class="card space-y-2">
      <p class="text-sm text-gray-400">粘贴系统异常日志 / 报错，交给 AI 诊断大脑（DeepSeek 等，带模型兜底）。</p>
      <textarea v-model="log" class="input" rows="8" placeholder="在此粘贴日志…"></textarea>
      <button class="btn btn-primary" :disabled="loading || !log" @click="run">
        {{ loading ? '诊断中…' : '开始诊断' }}
      </button>
      <div v-if="result" class="mt-3 p-3 rounded-lg bg-panel2 border border-edge whitespace-pre-wrap text-sm">{{ result }}</div>
      <p v-if="err" class="text-danger text-sm">{{ err }}</p>
      <p v-if="model" class="text-xs text-gray-500">使用模型：{{ model }}</p>
    </div>

    <!-- 历史回看 -->
    <div class="card space-y-2">
      <div class="flex items-center justify-between">
        <p class="font-semibold text-accent">诊断历史</p>
        <button class="btn text-xs" @click="loadHistory">🔄 刷新</button>
      </div>
      <p v-if="!history.length" class="text-xs text-gray-500">暂无历史记录（每次诊断会自动存档）。</p>
      <div v-for="h in history" :key="h.id" class="border border-edge rounded-lg p-2">
        <div class="flex items-start justify-between gap-2">
          <p class="text-xs text-gray-400 break-all flex-1">{{ (h.log_content || '').slice(0, 120) }}{{ (h.log_content || '').length > 120 ? '…' : '' }}</p>
          <button class="btn text-xs whitespace-nowrap" :disabled="busyId === h.id" @click="saveAsTodo(h)">存为待办</button>
        </div>
        <div class="mt-1 text-sm whitespace-pre-wrap leading-relaxed">{{ h.result }}</div>
        <p class="text-xs text-gray-500 mt-1">{{ (h.created_at || '').replace('T', ' ').slice(0, 16) }} · {{ h.model }}</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import api from '../api.js'

const log = ref('')
const result = ref('')
const model = ref('')
const err = ref('')
const loading = ref(false)
const history = ref([])
const busyId = ref(null)

async function run() {
  result.value = ''; err.value = ''; model.value = ''; loading.value = true
  try {
    const r = await api.post('/ai/diagnose', { log_content: log.value })
    result.value = r.data.result; model.value = r.data.model
    loadHistory()
  } catch (e) {
    err.value = ((e.response && e.response.data && e.response.data.detail) || '诊断失败')
  } finally { loading.value = false }
}

async function loadHistory() {
  try {
    const r = await api.get('/ai/history', { params: { limit: 30 } })
    history.value = r.data
  } catch (e) { /* 静默 */ }
}

async function saveAsTodo(h) {
  busyId.value = h.id
  try {
    await api.post('/todos', { content: (h.log_content || '').slice(0, 500) })
  } catch (e) {
    alert('存为待办失败：' + ((e.response && e.response.data && e.response.data.detail) || e))
  } finally {
    busyId.value = null
  }
}

onMounted(loadHistory)
</script>
