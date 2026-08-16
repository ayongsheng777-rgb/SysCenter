<template>
  <div class="space-y-4">
    <div class="flex items-center justify-between">
      <h2 class="text-lg font-semibold text-accent">系统健康</h2>
      <button class="btn" @click="load">🔄 刷新</button>
    </div>

    <div v-if="!data" class="text-gray-400 text-sm">加载中…</div>
    <template v-else>
      <!-- 聚合仪表盘 -->
      <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div class="card cursor-pointer" @click="goTodos">
          <p class="text-sm text-gray-400">未完成待办</p>
          <p class="text-2xl font-bold" :class="summary.todoOpen ? 'text-warn' : 'text-ok'">{{ summary.todoOpen }}</p>
          <p class="text-xs text-gray-500 mt-1">核心系统 {{ summary.todoSys }} 条</p>
        </div>
        <div class="card cursor-pointer" @click="goAlerts">
          <p class="text-sm text-gray-400">近期未确认告警</p>
          <p class="text-2xl font-bold" :class="summary.alertsActive ? 'text-danger' : 'text-ok'">{{ summary.alertsActive }}</p>
          <p class="text-xs text-gray-500 mt-1">严重/警告（未确认）</p>
        </div>
        <div class="card cursor-pointer" @click="goServices">
          <p class="text-sm text-gray-400">异常服务</p>
          <p class="text-2xl font-bold" :class="summary.svcAbnormal ? 'text-danger' : 'text-ok'">{{ summary.svcAbnormal }}</p>
          <p class="text-xs text-gray-500 mt-1">未运行的服务数</p>
        </div>
      </div>

      <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div class="card">
          <p class="text-sm text-gray-400">CPU 占用</p>
          <p class="text-2xl font-bold">{{ data.cpu_percent }}%</p>
          <div class="bar mt-2"><span :style="bar(data.cpu_percent)" :class="color(data.cpu_percent)"></span></div>
          <p class="text-xs text-gray-500 mt-1">逻辑核 {{ data.cpu_count }} / 物理核 {{ data.cpu_count_physical }}</p>
        </div>
        <div class="card">
          <p class="text-sm text-gray-400">内存占用</p>
          <p class="text-2xl font-bold">{{ data.ram_percent }}%</p>
          <div class="bar mt-2"><span :style="bar(data.ram_percent)" :class="color(data.ram_percent)"></span></div>
          <p class="text-xs text-gray-500 mt-1">{{ data.ram_used_gb }} / {{ data.ram_total_gb }} GB</p>
        </div>
        <div class="card">
          <p class="text-sm text-gray-400">进程数</p>
          <p class="text-2xl font-bold">{{ data.process_count }}</p>
          <p class="text-xs text-gray-500 mt-2">主机 {{ data.hostname }}</p>
          <p class="text-xs text-gray-500">已运行 {{ fmtUptime(data.uptime_seconds) }}</p>
        </div>
      </div>

      <div class="card">
        <p class="text-sm font-semibold mb-2">磁盘</p>
        <div v-for="d in data.disks" :key="d.mount" class="mb-2">
          <div class="flex justify-between text-xs text-gray-300">
            <span>{{ d.mount }} ({{ d.fstype }})</span>
            <span>{{ d.used_gb }} / {{ d.total_gb }} GB · {{ d.percent }}%</span>
          </div>
          <div class="bar mt-1"><span :style="bar(d.percent)" :class="color(d.percent)"></span></div>
        </div>
      </div>

      <div class="card">
        <p class="text-sm font-semibold mb-2">Top CPU 进程</p>
        <table class="w-full text-xs">
          <thead><tr class="text-gray-500"><th class="text-left">PID</th><th class="text-left">名称</th><th class="text-right">CPU%</th><th class="text-right">MEM%</th></tr></thead>
          <tbody>
            <tr v-for="p in data.top_cpu" :key="p.pid" class="border-t border-edge">
              <td class="py-1">{{ p.pid }}</td><td>{{ p.name }}</td>
              <td class="text-right">{{ p.cpu }}</td><td class="text-right">{{ p.mem }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="card">
        <p class="text-sm font-semibold mb-2">网卡</p>
        <div v-for="n in interfaces" :key="n.name" class="text-xs mb-1 flex gap-2">
          <span class="tag" :class="n.is_up ? 'text-ok' : 'text-danger'">{{ n.is_up ? 'UP' : 'DOWN' }}</span>
          <span class="text-gray-300 w-40 truncate">{{ n.name }}</span>
          <span class="text-gray-500">{{ n.ipv4.join(', ') || '—' }}</span>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import api from '../api.js'

const data = ref(null)
const interfaces = ref([])
const summary = reactive({ todoOpen: 0, todoSys: 0, alertsActive: 0, svcAbnormal: 0 })

function bar(v) { return { width: Math.min(100, v) + '%' } }
function color(v) { return v >= 90 ? 'bg-danger' : v >= 70 ? 'bg-warn' : 'bg-ok' }
function fmtUptime(s) {
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60)
  return `${h}h ${m}m`
}
function goTodos() { location.hash = '#/todos' }
function goAlerts() { location.hash = '#/alerts' }
function goServices() { location.hash = '#/services' }

async function load() {
  const [h, i] = await Promise.all([api.get('/system/health'), api.get('/system/interfaces')])
  data.value = h.data
  interfaces.value = i.data
  // 聚合仪表盘（容错：任一失败不影响主面板）
  try {
    const [t, a, s] = await Promise.all([
      api.get('/todos', { params: { all: 1 } }),
      api.get('/alerts', { params: { limit: 100 } }),
      api.get('/system/services'),
    ])
    const todos = t.data || []
    summary.todoOpen = todos.filter(x => x.status !== '已完成').length
    summary.todoSys = todos.filter(x => x.is_sys_scope && x.status !== '已完成').length
    const alerts = a.data || []
    summary.alertsActive = alerts.filter(x => !x.acknowledged && (x.level === 'critical' || x.level === 'warning')).length
    const svcs = s.data || []
    summary.svcAbnormal = svcs.filter(x => x.state !== 'RUNNING').length
  } catch (e) { /* 聚合失败静默 */ }
}
onMounted(load)
defineExpose({ load })
</script>
