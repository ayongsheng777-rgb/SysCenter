<template>
  <div class="space-y-4">
    <div class="flex items-center justify-between">
      <h2 class="text-lg font-semibold text-accent">VPS / 代理矩阵</h2>
      <div class="flex gap-2">
        <button class="btn" @click="refresh">🔄 探测延迟</button>
        <button class="btn btn-primary" @click="showAdd = !showAdd">+ 添加</button>
      </div>
    </div>

    <div v-if="showAdd" class="card space-y-2">
      <div class="grid grid-cols-2 md:grid-cols-4 gap-2">
        <input v-model="form.name" class="input" placeholder="名称" />
        <input v-model="form.host" class="input" placeholder="主机/IP" />
        <input v-model.number="form.port" class="input" type="number" placeholder="端口" />
        <select v-model="form.kind" class="input"><option value="vps">VPS</option><option value="proxy">代理</option></select>
      </div>
      <input v-model="form.note" class="input" placeholder="备注" />
      <button class="btn btn-primary" @click="save">保存</button>
    </div>

    <div class="card">
      <p v-if="loading" class="text-sm text-gray-500 mb-2">加载中…</p>
      <table class="w-full text-xs">
        <thead><tr class="text-gray-500"><th class="text-left">名称</th><th class="text-left">主机</th><th class="text-left">类型</th><th class="text-right">延迟</th><th class="text-right">状态</th><th></th></tr></thead>
        <tbody>
          <tr v-for="v in list" :key="v.id" class="border-t border-edge">
            <td class="py-1">{{ v.name }}</td><td>{{ v.host }}:{{ v.port }}</td><td>{{ v.kind }}</td>
            <td class="text-right">{{ v.latency_ms != null ? v.latency_ms + 'ms' : '—' }}</td>
            <td class="text-right"><span class="tag" :class="v.alive ? 'text-ok' : 'text-danger'">{{ v.alive ? '在线' : '离线' }}</span></td>
            <td class="text-right"><button class="btn btn-danger text-xs" @click="del(v.id)">删</button></td>
          </tr>
        </tbody>
      </table>
      <p v-if="!list.length" class="text-xs text-gray-500 mt-2">暂无实例，点击「添加」录入 RackNerd / CloudCone 等。</p>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import api from '../api.js'

const list = ref([])
const showAdd = ref(false)
const form = ref({ name: '', host: '', port: 22, kind: 'vps', note: '' })
const loading = ref(false)

async function refresh() { loading.value = true; try { const r = await api.post('/vps/refresh'); list.value = r.data } finally { loading.value = false } }
async function save() {
  try { await api.post('/vps', form.value); showAdd.value = false; form.value = { name: '', host: '', port: 22, kind: 'vps', note: '' }; await refresh() }
  catch (e) { alert('保存失败：' + ((e.response && e.response.data && e.response.data.detail) || e)) }
}
async function del(id) { if (!confirm('确认删除？')) return; await api.delete('/vps/' + id); await refresh() }
onMounted(refresh)
defineExpose({ refresh })
</script>
