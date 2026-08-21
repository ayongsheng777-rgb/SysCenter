<template>
  <div class="space-y-4">
    <div class="flex items-center justify-between">
      <h2 class="text-lg font-semibold text-accent">灾变备份</h2>
      <div class="flex gap-2">
        <button class="btn" :disabled="busy" @click="run('incr')">🔄 立即增量备份</button>
        <button class="btn" :disabled="busy" @click="run('full')">📦 立即全量备份</button>
      </div>
    </div>

    <div class="card">
      <p v-if="loading" class="text-sm text-gray-500 mb-2">加载中…</p>
      <div class="flex flex-wrap gap-6 text-sm">
        <div>
          <div class="text-xs text-gray-500">备份目录</div>
          <div class="font-mono text-xs mt-1">{{ status.root || '-' }}</div>
        </div>
        <div>
          <div class="text-xs text-gray-500">上次全量</div>
          <div class="mt-1">{{ fmtTime(status.last_full) }}</div>
        </div>
        <div>
          <div class="text-xs text-gray-500">上次增量</div>
          <div class="mt-1">{{ fmtTime(status.last_incr) }}</div>
        </div>
        <div>
          <div class="text-xs text-gray-500">备份周期</div>
          <div class="mt-1">全量 {{ status.full_interval_days }} 天 / 增量 {{ status.incr_interval_days }} 天</div>
        </div>
        <div>
          <div class="text-xs text-gray-500">保留策略</div>
          <div class="mt-1">全量 {{ status.full_retention_days }} 天 / 增量 {{ status.incr_retention_days }} 天</div>
        </div>
      </div>
    </div>

    <div class="card">
      <p class="text-sm text-gray-500 mb-2">最近备份记录</p>
      <table class="w-full text-xs">
        <thead><tr class="text-gray-500"><th class="text-left">时间</th><th class="text-left">类型</th><th class="text-left">大小</th><th class="text-left">状态</th><th class="text-left">说明</th></tr></thead>
        <tbody>
          <tr v-for="(b, i) in status.recent" :key="i" class="border-t border-edge">
            <td class="py-1 text-gray-400 whitespace-nowrap">{{ fmtTime(b.created_at) }}</td>
            <td><span class="tag" :class="b.backup_type === 'full' ? 'text-ok' : 'text-warn'">{{ b.backup_type === 'full' ? '全量' : '增量' }}</span></td>
            <td class="text-gray-400">{{ fmtSize(b.file_size) }}</td>
            <td><span class="tag" :class="b.status === 'success' ? 'text-ok' : 'text-danger'">{{ b.status === 'success' ? '成功' : '失败' }}</span></td>
            <td class="text-gray-400">{{ b.message }}</td>
          </tr>
        </tbody>
      </table>
      <p v-if="!status.recent || !status.recent.length" class="text-xs text-gray-500 mt-2">暂无备份记录</p>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import api from '../api.js'

const status = ref({ root: '', recent: [] })
const loading = ref(false)
const busy = ref(false)

function fmtTime(s) {
  if (!s) return '从未'
  const d = new Date(s)
  if (isNaN(d.getTime())) return s
  return d.toLocaleString('zh-CN', { hour12: false })
}

function fmtSize(n) {
  if (n == null) return '-'
  if (n < 1024) return n + ' B'
  if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB'
  return (n / 1024 / 1024).toFixed(1) + ' MB'
}

async function load() {
  loading.value = true
  try {
    const r = await api.get('/backup/status')
    status.value = r.data
  } catch (e) {
    alert('加载备份状态失败：' + ((e.response && e.response.data && e.response.data.detail) || e))
  } finally {
    loading.value = false
  }
}

async function run(type) {
  const label = type === 'full' ? '全量' : '增量'
  if (!confirm(`确认立即执行${label}备份？`)) return
  busy.value = true
  try {
    await api.post('/backup/run', { type })
    await load()
  } catch (e) {
    alert(`${label}备份失败：` + ((e.response && e.response.data && e.response.data.detail) || e))
  } finally {
    busy.value = false
  }
}

onMounted(load)
defineExpose({ load })
</script>
