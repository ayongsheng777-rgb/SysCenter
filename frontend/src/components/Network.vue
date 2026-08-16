<template>
  <div class="space-y-4">
    <div class="flex items-center justify-between">
      <h2 class="text-lg font-semibold text-accent">网络与资产</h2>
      <button class="btn" @click="refreshAssets">🔄 刷新 NAS / TV</button>
    </div>

    <div class="card">
      <p class="text-sm font-semibold mb-2">局域网设备扫描</p>
      <div class="flex gap-2 mb-3">
        <input v-model="subnet" class="input" placeholder="网段，如 192.168.1" />
        <button class="btn btn-primary" :disabled="scanning" @click="scan">{{ scanning ? '扫描中…' : '开始扫描' }}</button>
      </div>
      <p class="text-xs text-gray-500 mb-2">在线设备 {{ hosts.length }} 台（线程并发 ping，约数秒~数十秒）</p>
      <div class="mb-2">
        <button class="btn text-xs" :disabled="!hosts.length" @click="exportCsv">⬇ 导出 CSV</button>
      </div>
      <table class="w-full text-xs">
        <thead><tr class="text-gray-500"><th class="text-left">IP</th><th class="text-left">MAC</th><th class="text-left">主机名</th><th class="text-left">类型</th><th class="text-right">延迟</th></tr></thead>
        <tbody>
          <tr v-for="h in hosts" :key="h.ip" class="border-t border-edge">
            <td class="py-1">{{ h.ip }}</td><td class="text-gray-400">{{ h.mac || '—' }}</td>
            <td>{{ h.hostname || '—' }}</td>
            <td><span class="tag text-gray-400">{{ devType(h) }}</span></td>
            <td class="text-right">{{ h.latency_ms ?? '—' }} ms</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
      <div class="card">
        <p class="text-sm font-semibold mb-2">Synology NAS</p>
        <div v-if="!nas.configured" class="text-xs text-gray-500">未在设置中配置 NAS_HOST</div>
        <div v-else class="text-sm">
          <p>{{ nas.host }}:{{ nas.port }}</p>
          <span class="tag" :class="nas.alive ? 'text-ok' : 'text-danger'">{{ nas.alive ? '在线' : '离线' }}</span>
          <span v-if="nas.latency_ms != null" class="text-xs text-gray-400 ml-2">{{ nas.latency_ms }} ms</span>
        </div>
      </div>
      <div class="card">
        <p class="text-sm font-semibold mb-2">TV 盒子</p>
        <div v-if="!tv.configured" class="text-xs text-gray-500">未在设置中配置 TV_HOST</div>
        <div v-else class="text-sm">
          <p>{{ tv.host }}</p>
          <span class="tag" :class="tv.alive ? 'text-ok' : 'text-danger'">{{ tv.alive ? '在线' : '离线' }}</span>
          <span v-if="tv.latency_ms != null" class="text-xs text-gray-400 ml-2">{{ tv.latency_ms }} ms</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import api from '../api.js'

const subnet = ref('')
const scanning = ref(false)
const hosts = ref([])
const nas = ref({ configured: false })
const tv = ref({ configured: false })

async function loadSubnet() {
  try {
    const r = await api.get('/settings')
    subnet.value = (r.data.runtime.lan_subnet || '').replace(/\.\d+$/, '') || ''
  } catch (e) {}
}
async function scan() {
  scanning.value = true
  try {
    const r = await api.post('/network/lan-scan', { subnet: subnet.value })
    hosts.value = r.data.hosts
  } catch (e) { alert('扫描失败：' + ((e.response && e.response.data && e.response.data.detail) || e)) }
  finally { scanning.value = false }
}
async function refreshAssets() {
  const [n, t] = await Promise.all([api.get('/network/nas'), api.get('/network/tv')])
  nas.value = n.data; tv.value = t.data
}
function devType(h) {
  const s = ((h.hostname || '') + ' ' + (h.mac || '')).toLowerCase()
  if (s.includes('nas') || s.includes('synology') || s.includes('qnap')) return 'NAS'
  if (s.includes('tv') || s.includes('androidtv') || s.includes('mi tv')) return 'TV/盒子'
  if (s.includes('phone') || s.includes('iphone') || s.includes('android') || s.includes('redmi') || s.includes('mi ')) return '手机'
  if (s.includes('router') || s.includes('padavan') || s.includes('openwrt') || s.includes('ikuai') || s.includes('gateway')) return '路由器'
  if (s.includes('pc') || s.includes('desktop') || s.includes('win') || s.includes('laptop')) return '电脑'
  return '未知'
}
function exportCsv() {
  const header = ['IP', 'MAC', '主机名', '类型', '延迟(ms)']
  const rows = hosts.value.map(h => [h.ip, h.mac || '', h.hostname || '', devType(h), h.latency_ms ?? ''])
  const csv = [header, ...rows].map(r => r.map(c => `"${String(c).replace(/"/g, '""')}"`).join(',')).join('\r\n')
  const blob = new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `lan-scan-${subnet.value.replace(/\./g, '_')}.csv`
  a.click()
  URL.revokeObjectURL(url)
}
onMounted(() => { loadSubnet(); refreshAssets() })
defineExpose({ refreshAssets })
</script>
