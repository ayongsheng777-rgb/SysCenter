<template>
  <div class="space-y-4">
    <div class="flex items-center justify-between">
      <h2 class="text-lg font-semibold text-accent">🧩 技能中心</h2>
      <button class="btn" @click="load">🔄 刷新</button>
    </div>

    <p class="text-xs text-gray-500">
      每个技能可配「调用代号（key）」和「第三方密钥」，飞书里发 <code class="text-accent2">/key 内容</code> 精准调用。
      内置/目录技能直接执行；SkillHub 技能（SKILL.md）由 AI 代跑，需先在「设置」页配好 AI Key。
    </p>

    <!-- 编辑区 -->
    <div v-if="editing" class="card space-y-2">
      <p class="font-semibold">编辑技能「{{ editing.name }}」</p>
      <div class="grid grid-cols-1 md:grid-cols-2 gap-2">
        <div>
          <label class="text-xs text-gray-500">调用代号 key（飞书 /xxx 用）</label>
          <input v-model="form.key" class="input w-full" placeholder="如 weather" />
        </div>
        <div>
          <label class="text-xs text-gray-500">技能名</label>
          <input v-model="form.name" class="input w-full" placeholder="技能名称" />
        </div>
      </div>
      <div>
        <label class="text-xs text-gray-500">触发词（逗号分隔，飞书消息里命中即触发）</label>
        <input v-model="form.trigger_keywords" class="input w-full" placeholder="天气, 气温, weather" />
      </div>
      <div>
        <label class="text-xs text-gray-500">
          第三方密钥 {{ editing.has_api_key ? '（已配置，留空=不修改）' : '（可选）' }}
        </label>
        <div class="flex gap-2">
          <input v-model="form.api_key" class="input flex-1" placeholder="技能调外部接口用的 API Key" />
          <button v-if="editing.has_api_key" class="btn btn-danger text-xs" @click="clearKey">清除密钥</button>
        </div>
      </div>
      <div class="flex gap-2">
        <button class="btn btn-primary" :disabled="saving" @click="save">
          {{ saving ? '保存中…' : '💾 保存' }}
        </button>
        <button class="btn" @click="cancelEdit">取消</button>
      </div>
    </div>

    <!-- 列表 -->
    <div class="card space-y-2">
      <p v-if="loading" class="text-sm text-gray-500 mb-2">加载中…</p>
      <div v-for="s in list" :key="s.skill_id" class="border border-edge rounded-lg p-3 space-y-1">
        <div class="flex items-center justify-between gap-2">
          <div class="flex items-center gap-2 min-w-0">
            <span class="font-semibold text-sm truncate">{{ s.name }}</span>
            <span class="tag text-accent2">/{{ s.key }}</span>
            <span class="tag text-gray-400">{{ srcLabel(s.source) }}</span>
            <span v-if="s.has_api_key" class="tag text-ok">已配密钥</span>
          </div>
          <div class="flex items-center gap-2 shrink-0">
            <label class="flex items-center gap-1 text-xs text-gray-500 cursor-pointer">
              <input type="checkbox" :checked="s.enabled" @change="toggle(s)" />
              启用
            </label>
            <button class="btn text-xs" @click="edit(s)">编辑</button>
          </div>
        </div>
        <p v-if="s.desc" class="text-xs text-gray-500 break-all">{{ s.desc }}</p>
        <div v-if="s.trigger_keywords && s.trigger_keywords.length" class="flex flex-wrap gap-1">
          <span v-for="t in s.trigger_keywords" :key="t" class="tag text-gray-400">#{{ t }}</span>
        </div>
      </div>
      <p v-if="!loading && !list.length" class="text-xs text-gray-500 mt-2">
        暂无技能。内置「天气查询」会自动出现在这里；SkillHub 装的技能也会被扫描进来。
      </p>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import api from '../api.js'

const list = ref([])
const loading = ref(false)
const saving = ref(false)
const editing = ref(null)
const form = reactive({ key: '', name: '', trigger_keywords: '', api_key: '' })

function srcLabel(s) {
  return { builtin: '内置', dir: '目录', skillhub: 'SkillHub' }[s] || s
}

function err(e) {
  const d = e.response && e.response.data
  alert('操作失败：' + ((d && (d.message || d.detail)) || (e && e.message) || e))
}

async function load() {
  loading.value = true
  try {
    const r = await api.get('/skills')
    list.value = r.data || []
  } catch (e) { err(e) } finally { loading.value = false }
}

function edit(s) {
  editing.value = s
  form.key = s.key || ''
  form.name = s.name || ''
  form.trigger_keywords = (s.trigger_keywords || []).join(', ')
  form.api_key = ''
}

function cancelEdit() {
  editing.value = null
  form.key = form.name = form.trigger_keywords = form.api_key = ''
}

function clearKey() {
  form.api_key = '__CLEAR__'
}

async function toggle(s) {
  try {
    await api.put('/skills/' + encodeURIComponent(s.skill_id), { enabled: !s.enabled })
    await load()
  } catch (e) { err(e) }
}

async function save() {
  if (!form.key.trim()) { alert('调用代号 key 不能为空'); return }
  saving.value = true
  const body = {
    key: form.key.trim(),
    name: form.name.trim(),
    trigger_keywords: (form.trigger_keywords || '').split(/[,，]/).map(x => x.trim()).filter(Boolean),
  }
  if (form.api_key === '__CLEAR__') {
    body.api_key = ''
  } else if (form.api_key && form.api_key.trim()) {
    body.api_key = form.api_key.trim()
  }
  try {
    await api.put('/skills/' + encodeURIComponent(editing.value.skill_id), body)
    cancelEdit()
    await load()
  } catch (e) { err(e) } finally { saving.value = false }
}

onMounted(load)
defineExpose({ refresh: load })
</script>
