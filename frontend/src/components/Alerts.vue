<template>
  <div class="space-y-4">
    <div class="flex items-center justify-between">
      <h2 class="text-lg font-semibold text-accent">告警日志</h2>
      <button class="btn" @click="load">🔄 刷新</button>
    </div>
    <div class="card">
      <p v-if="loading" class="text-sm text-gray-500 mb-2">加载中…</p>
      <table class="w-full text-xs">
        <thead><tr class="text-gray-500"><th class="text-left">时间</th><th class="text-left">级别</th><th class="text-left">来源</th><th class="text-left">内容</th></tr></thead>
        <tbody>
          <tr v-for="a in list" :key="a.id" class="border-t border-edge" :class="a.acknowledged ? 'opacity-50' : ''">
            <td class="py-1 text-gray-400">{{ a.ts }}</td>
            <td><span class="tag" :class="lvl(a.level)">{{ a.level }}</span></td>
            <td class="text-gray-400">{{ a.source }}</td>
            <td>{{ a.message }}</td>
            <td class="text-right whitespace-nowrap">
              <button v-if="!a.acknowledged" class="btn text-xs" @click="ack(a)">确认</button>
              <button class="btn btn-danger text-xs" @click="del(a)">删</button>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-if="!list.length" class="text-xs text-gray-500 mt-2">暂无告警</p>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import api from '../api.js'

const list = ref([])
const loading = ref(false)
function lvl(l) { return l === 'critical' ? 'text-danger' : l === 'warning' ? 'text-warn' : 'text-ok' }
async function load() { loading.value = true; try { const r = await api.get('/alerts?limit=100'); list.value = r.data } finally { loading.value = false } }
async function ack(a) {
  try { await api.post(`/alerts/${a.id}/ack`); a.acknowledged = true } catch (e) { alert('确认失败：' + ((e.response && e.response.data && e.response.data.detail) || e)) }
}
async function del(a) {
  if (!confirm('确认删除该告警记录？')) return
  try { await api.delete(`/alerts/${a.id}`); list.value = list.value.filter(x => x.id !== a.id) } catch (e) { alert('删除失败：' + ((e.response && e.response.data && e.response.data.detail) || e)) }
}
onMounted(load)
defineExpose({ load })
</script>
