<template>
  <div class="space-y-4">
    <div class="flex items-center justify-between">
      <h2 class="text-lg font-semibold text-accent">📝 笔记 / 知识库</h2>
      <button class="btn" @click="load">🔄 刷新</button>
    </div>

    <!-- 问 AI：从笔记里调取 -->
    <div class="card space-y-2">
      <p class="font-semibold">问 AI（从笔记里调取）</p>
      <div class="flex gap-2">
        <input v-model="askQ" class="input flex-1" placeholder="例如：我存的硅基流动 key 还能用吗？"
               @keyup.enter="ask" />
        <button class="btn btn-primary" :disabled="asking" @click="ask">{{ asking ? '思考中…' : '提问' }}</button>
      </div>
      <div v-if="askRes" class="rounded-lg border border-edge bg-panel2 p-3 space-y-1">
        <p class="text-xs whitespace-pre-wrap">{{ askRes.answer }}</p>
        <p v-if="askRes.sources && askRes.sources.length" class="text-xs text-gray-400">
          来源：{{ askRes.sources.map(s => s.title).join('、') }}
        </p>
      </div>
    </div>

    <!-- 新增 / 编辑 -->
    <div class="card space-y-2">
      <p class="font-semibold">{{ editing ? '编辑笔记 #' + editing.id : '新增笔记' }}</p>
      <div class="grid grid-cols-1 md:grid-cols-2 gap-2">
        <input v-model="form.title" class="input" placeholder="标题（如：硅基流动 API Key）" />
        <select v-model="form.category" class="input">
          <option value="apikey">API Key</option>
          <option value="tech">技术信息</option>
          <option value="other">其他</option>
        </select>
      </div>
      <div v-if="form.category === 'apikey'" class="grid grid-cols-1 md:grid-cols-2 gap-2">
        <select v-model="form.provider" class="input">
          <option value="siliconflow">硅基流动 SiliconFlow</option>
          <option value="deepseek">DeepSeek</option>
          <option value="openai">OpenAI</option>
          <option value="other">其他</option>
        </select>
        <input v-model="form.tags" class="input" placeholder="标签（逗号分隔）" />
      </div>
      <textarea v-model="form.content" class="input" rows="3"
                :placeholder="form.category === 'apikey' ? '粘贴 API Key（保存时自动测试可用性）' : '记录内容…'"></textarea>
      <div class="flex gap-2">
        <button class="btn btn-primary" :disabled="saving" @click="save">
          {{ saving ? '保存中…' : (editing ? '保存修改' : '💾 保存') }}
        </button>
        <button v-if="editing" class="btn" @click="resetForm">取消编辑</button>
      </div>
      <p v-if="form.test_result" class="text-xs" :class="form.tested === 'ok' ? 'text-ok' : 'text-danger'">
        {{ form.test_result }}
      </p>
    </div>

    <!-- 搜索 / 筛选 -->
    <div class="flex gap-2">
      <input v-model="q" class="input flex-1" placeholder="搜索标题/内容/标签…" @keyup.enter="load" />
      <select v-model="catFilter" class="input w-40">
        <option value="">全部分类</option>
        <option value="apikey">API Key</option>
        <option value="tech">技术信息</option>
        <option value="other">其他</option>
      </select>
      <button class="btn" @click="load">搜索</button>
    </div>

    <!-- 列表 -->
    <div class="card space-y-2">
      <p v-if="loading" class="text-sm text-gray-500 mb-2">加载中…</p>
      <div v-for="n in list" :key="n.id" class="border border-edge rounded-lg p-3 space-y-1">
        <div class="flex items-center justify-between gap-2">
          <div class="flex items-center gap-2 min-w-0">
            <span class="font-semibold text-sm truncate">{{ n.title }}</span>
            <span class="tag" :class="catClass(n.category)">{{ catLabel(n.category) }}</span>
            <span v-if="n.provider" class="text-xs text-gray-400">{{ n.provider }}</span>
          </div>
          <div class="flex items-center gap-2 shrink-0">
            <span class="tag" :class="testedClass(n.tested)">{{ testedLabel(n.tested) }}</span>
            <button class="btn text-xs" @click="editNote(n)">编辑</button>
            <button class="btn btn-danger text-xs" @click="del(n)">删除</button>
          </div>
        </div>
        <p class="text-xs break-all whitespace-pre-wrap" :class="isSecret(n) && !revealed.has(n.id) ? 'text-gray-400' : ''">
          {{ isSecret(n) && !revealed.has(n.id) ? mask(n.content) : n.content }}
        </p>
        <div class="flex flex-wrap items-center gap-2 text-xs text-gray-400">
          <button v-if="isSecret(n)" class="text-accent2" @click="toggleReveal(n.id)">
            {{ revealed.has(n.id) ? '隐藏' : '显示' }}
          </button>
          <span v-if="n.tags && n.tags.length" class="flex gap-1">
            <span v-for="t in n.tags" :key="t" class="tag text-gray-400">#{{ t }}</span>
          </span>
          <span v-if="n.test_result" :class="n.tested === 'ok' ? 'text-ok' : 'text-danger'">{{ n.test_result }}</span>
          <span class="ml-auto">{{ fmt(n.created_at) }}</span>
        </div>
      </div>
      <p v-if="!loading && !list.length" class="text-xs text-gray-500 mt-2">暂无笔记，先记一条吧。</p>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import api from '../api.js'

const list = ref([])
const loading = ref(false)
const saving = ref(false)
const asking = ref(false)
const q = ref('')
const catFilter = ref('')
const askQ = ref('')
const askRes = ref(null)
const editing = ref(null)
const revealed = ref(new Set())
const form = reactive({ title: '', category: 'apikey', provider: 'siliconflow', content: '', tags: '', tested: '', test_result: '' })

const CAT = { apikey: 'API Key', tech: '技术', other: '其他' }
const TESTED = { ok: '已验证 ✓', fail: '验证失败', untested: '未测', skipped: '跳过' }

function catLabel(c) { return CAT[c] || c }
function catClass(c) {
  return { apikey: 'text-accent', tech: 'text-ok', other: 'text-gray-400' }[c] || 'text-gray-400'
}
function testedClass(t) {
  return { ok: 'text-ok', fail: 'text-danger', untested: 'text-gray-400', skipped: 'text-gray-400' }[t] || 'text-gray-400'
}
function testedLabel(t) { return TESTED[t] || t }
function isSecret(n) { return n.category === 'apikey' }
function mask(s) {
  if (!s) return ''
  if (s.length <= 12) return '••••••••'
  return s.slice(0, 8) + '••••••' + s.slice(-4)
}
function toggleReveal(id) {
  const set = new Set(revealed.value)
  set.has(id) ? set.delete(id) : set.add(id)
  revealed.value = set
}
function fmt(ts) { return ts ? String(ts).replace('T', ' ').slice(0, 16) : '' }

function err(e) {
  const d = e.response && e.response.data
  alert('操作失败：' + ((d && (d.message || d.detail)) || (e && e.message) || e))
}

async function load() {
  loading.value = true
  try {
    const r = await api.get('/notes', { params: { q: q.value, category: catFilter.value, limit: 100 } })
    list.value = r.data || []
  } catch (e) { err(e) } finally { loading.value = false }
}

async function save() {
  if (!form.title.trim() || !form.content.trim()) { alert('标题与内容不能为空'); return }
  saving.value = true
  form.tested = ''; form.test_result = ''
  try {
    const body = {
      title: form.title.trim(),
      category: form.category,
      provider: form.category === 'apikey' ? form.provider : '',
      content: form.content.trim(),
      tags: (form.tags || '').split(/[,，]/).map(s => s.trim()).filter(Boolean),
    }
    const r = editing.value
      ? await api.put('/notes/' + editing.value.id, body)
      : await api.post('/notes', body)
    if (r.data) { form.tested = r.data.tested; form.test_result = r.data.test_result || '' }
    resetForm()
    await load()
  } catch (e) { err(e) } finally { saving.value = false }
}

function editNote(n) {
  editing.value = n
  form.title = n.title
  form.category = n.category
  form.provider = n.provider || 'siliconflow'
  form.content = n.content
  form.tags = (n.tags || []).join(', ')
  form.tested = ''; form.test_result = ''
}

function resetForm() {
  editing.value = null
  Object.assign(form, { title: '', category: 'apikey', provider: 'siliconflow', content: '', tags: '', tested: '', test_result: '' })
}

async function del(n) {
  if (!confirm('确定删除笔记「' + n.title + '」？')) return
  try { await api.delete('/notes/' + n.id); await load() } catch (e) { err(e) }
}

async function ask() {
  const qs = askQ.value.trim()
  if (!qs) { alert('请输入问题'); return }
  asking.value = true
  askRes.value = null
  try {
    const r = await api.post('/notes/ask', { question: qs })
    askRes.value = r.data
  } catch (e) { err(e) } finally { asking.value = false }
}

onMounted(load)
defineExpose({ refresh: load })
</script>
