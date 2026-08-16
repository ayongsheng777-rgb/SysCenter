<template>
  <div class="space-y-4">
    <div class="flex items-center justify-between">
      <h2 class="text-lg font-semibold text-accent">Windows 服务与启动项</h2>
      <button class="btn" @click="load">🔄 刷新</button>
    </div>

    <div class="card">
      <p class="text-sm font-semibold mb-2">系统服务（核心服务禁止停止）</p>
      <p v-if="loading" class="text-sm text-gray-500 mb-2">加载中…</p>
      <input v-model="kw" class="input mb-2" placeholder="过滤服务名…" />
      <div class="max-h-80 overflow-auto">
        <table class="w-full text-xs">
          <thead><tr class="text-gray-500"><th class="text-left">名称</th><th class="text-left">显示名</th><th class="text-left">状态</th><th class="text-left">启动类型</th><th></th></tr></thead>
          <tbody>
            <tr v-for="s in filtered" :key="s.name" class="border-t border-edge">
              <td class="py-1">{{ s.name }}</td><td class="text-gray-400">{{ s.display }}</td>
              <td><span class="tag" :class="s.state === 'RUNNING' ? 'text-ok' : 'text-gray-400'">{{ s.state }}</span></td>
              <td class="text-gray-400">{{ s.start_type }}</td>
              <td class="text-right whitespace-nowrap">
                <button v-if="s.state !== 'RUNNING'" class="btn text-xs" @click="act(s.name, 'start')">启动</button>
                <button v-else class="btn btn-danger text-xs" @click="act(s.name, 'stop')">停止</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div class="card">
      <p class="text-sm font-semibold mb-2">开机自启项（注册表 / 启动文件夹）</p>
      <div class="max-h-60 overflow-auto text-xs">
        <table class="w-full">
          <thead><tr class="text-gray-500"><th class="text-left">作用域</th><th class="text-left">名称</th><th class="text-left">命令</th></tr></thead>
          <tbody>
            <tr v-for="(a, i) in startup" :key="i" class="border-t border-edge">
              <td class="py-1 text-gray-400">{{ a.scope }}</td><td>{{ a.name }}</td><td class="text-gray-500 break-all">{{ a.command }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import api from '../api.js'

const services = ref([])
const startup = ref([])
const kw = ref('')
const loading = ref(false)

const filtered = computed(() =>
  services.value.filter(s => !kw.value || (s.name + s.display).toLowerCase().includes(kw.value.toLowerCase())))

async function load() {
  loading.value = true
  try {
    const [s, a] = await Promise.all([api.get('/system/services'), api.get('/system/startup')])
    services.value = s.data; startup.value = a.data
  } finally { loading.value = false }
}
async function act(name, action) {
  if (action === 'stop' && !confirm(`确认停止服务 ${name}？`)) return
  try { await api.post(`/system/services/${name}/action`, { action }); await load() }
  catch (e) { alert(((e.response && e.response.data && e.response.data.detail) || e)) }
}
onMounted(load)
defineExpose({ load })
</script>
