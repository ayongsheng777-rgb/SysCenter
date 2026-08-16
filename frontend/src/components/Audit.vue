<template>
  <div class="space-y-4">
    <div class="flex items-center justify-between">
      <h2 class="text-lg font-semibold text-accent">操作审计日志</h2>
      <div class="flex gap-2 items-center">
        <select v-model="actionFilter" class="input">
          <option value="">全部动作</option>
          <option v-for="a in actions" :key="a" :value="a">{{ a }}</option>
        </select>
        <button class="btn" @click="load">🔄 刷新</button>
      </div>
    </div>
    <div class="card">
      <p v-if="loading" class="text-sm text-gray-500 mb-2">加载中…</p>
      <table class="w-full text-xs">
        <thead><tr class="text-gray-500">
          <th class="text-left">时间</th><th class="text-left">角色</th><th class="text-left">动作</th>
          <th class="text-left">对象</th><th class="text-left">详情</th><th class="text-left">IP</th>
        </tr></thead>
        <tbody>
          <tr v-for="r in filtered" :key="r.id" class="border-t border-edge">
            <td class="py-1">{{ r.ts }}</td>
            <td>{{ r.actor }}</td>
            <td>{{ r.action }}</td>
            <td>{{ r.target }}</td>
            <td class="max-w-xs truncate" :title="r.detail">{{ r.detail }}</td>
            <td>{{ r.ip }}</td>
          </tr>
        </tbody>
      </table>
      <p v-if="!filtered.length" class="text-xs text-gray-500 mt-2">暂无审计记录。</p>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from 'vue'
import api from '../api.js'

const list = ref([])
const loading = ref(false)
const actionFilter = ref('')
const actions = [
  'login', 'logout', 'reset_otp',
  'vps_upsert', 'vps_delete',
  'settings_update',
  'service_action',
  'automation_trigger', 'automation_preset_save', 'automation_preset_delete',
  'alert_ack', 'alert_delete',
  'feishu_restart', 'feishu_config',
  'lan_scan', 'notify_feishu', 'notify_test',
  'ai_diagnose',
]

const filtered = computed(() =>
  actionFilter.value ? list.value.filter(r => r.action === actionFilter.value) : list.value)

async function load() {
  loading.value = true
  try {
    const r = await api.get('/audit')
    list.value = r.data
  } catch (e) {
    const d = e.response && e.response.data
    alert('加载失败：' + ((d && (d.message || d.detail)) || e))
  } finally {
    loading.value = false
  }
}
onMounted(load)
defineExpose({ refresh: load })
</script>
