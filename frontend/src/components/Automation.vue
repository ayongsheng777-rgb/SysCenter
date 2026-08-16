<template>
  <div class="space-y-4">
    <h2 class="text-lg font-semibold text-accent">自动化剧本中枢</h2>

    <!-- 保存预设 -->
    <div class="card space-y-2">
      <p class="text-sm font-semibold">保存剧本预设</p>
      <input v-model="form.name" class="input" placeholder="预设名称，如 每日备份" />
      <input v-model="form.workflow" class="input" placeholder="工作流路径或完整 URL，如 my-workflow" />
      <textarea v-model="payloadText" class="input" rows="3" placeholder='JSON 负载，如 {"foo":"bar"}'></textarea>
      <button class="btn btn-primary text-xs w-fit" :disabled="saving" @click="savePreset">{{ saving ? '保存中…' : '💾 保存预设' }}</button>
    </div>

    <!-- 预设列表 -->
    <div class="card">
      <div class="flex items-center justify-between mb-2">
        <p class="text-sm font-semibold">已保存剧本</p>
        <button class="btn text-xs" @click="loadPresets">🔄 刷新</button>
      </div>
      <p v-if="!presets.length" class="text-xs text-gray-500">暂无预设，先保存一个常用工作流。</p>
      <table v-else class="w-full text-xs">
        <thead><tr class="text-gray-500"><th class="text-left">名称</th><th class="text-left">工作流</th><th class="text-right">操作</th></tr></thead>
        <tbody>
          <tr v-for="p in presets" :key="p.id" class="border-t border-edge">
            <td class="py-1">{{ p.name }}</td>
            <td class="text-gray-400 break-all">{{ p.workflow }}</td>
            <td class="text-right whitespace-nowrap">
              <button class="btn text-xs" :disabled="loading" @click="triggerPreset(p)">触发</button>
              <button class="btn btn-danger text-xs" @click="delPreset(p)">删</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 手动触发 -->
    <div class="card space-y-2">
      <p class="text-sm text-gray-400">或临时触发一个工作流（路径或完整 URL）。</p>
      <input v-model="workflow" class="input" placeholder="工作流路径或完整 URL" />
      <textarea v-model="payloadText2" class="input" rows="3" placeholder='JSON 负载'></textarea>
      <button class="btn btn-primary" :disabled="loading" @click="trigger">{{ loading ? '触发中…' : '触发' }}</button>
      <pre v-if="resp" class="text-xs text-gray-300 mt-2 whitespace-pre-wrap">{{ resp }}</pre>
      <p v-if="err" class="text-danger text-sm">{{ err }}</p>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import api from '../api.js'

const presets = ref([])
const form = ref({ name: '', workflow: '' })
const payloadText = ref('{}')
const saving = ref(false)

const workflow = ref('')
const payloadText2 = ref('{}')
const resp = ref('')
const err = ref('')
const loading = ref(false)

async function loadPresets() {
  try { const r = await api.get('/automation/presets'); presets.value = r.data } catch (e) { alert('加载预设失败：' + ((e.response && e.response.data && e.response.data.detail) || e)) }
}
async function savePreset() {
  let payload = {}
  try { payload = JSON.parse(payloadText.value || '{}') } catch { alert('负载不是合法 JSON'); return }
  if (!form.value.name.trim() || !form.value.workflow.trim()) { alert('名称和路径不能为空'); return }
  saving.value = true
  try {
    await api.post('/automation/presets', { name: form.value.name.trim(), workflow: form.value.workflow.trim(), payload })
    form.value = { name: '', workflow: '' }; payloadText.value = '{}'
    await loadPresets()
  } catch (e) { alert('保存失败：' + ((e.response && e.response.data && e.response.data.detail) || e)) }
  finally { saving.value = false }
}
async function triggerPreset(p) {
  loading.value = true; resp.value = ''; err.value = ''
  try {
    const r = await api.post('/automation/trigger', { preset_id: p.id })
    resp.value = JSON.stringify(r.data, null, 2)
  } catch (e) { err.value = ((e.response && e.response.data && e.response.data.detail) || '触发失败') }
  finally { loading.value = false }
}
async function delPreset(p) {
  if (!confirm('确认删除预设？')) return
  try { await api.delete(`/automation/presets/${p.id}`); await loadPresets() } catch (e) { alert('删除失败：' + ((e.response && e.response.data && e.response.data.detail) || e)) }
}
async function trigger() {
  resp.value = ''; err.value = ''; loading.value = true
  let payload = {}
  try { payload = JSON.parse(payloadText2.value || '{}') } catch { err.value = '负载不是合法 JSON'; loading.value = false; return }
  try {
    const r = await api.post('/automation/trigger', { workflow: workflow.value, payload })
    resp.value = JSON.stringify(r.data, null, 2)
  } catch (e) { err.value = ((e.response && e.response.data && e.response.data.detail) || '触发失败') }
  finally { loading.value = false }
}
onMounted(loadPresets)
defineExpose({ loadPresets })
</script>
