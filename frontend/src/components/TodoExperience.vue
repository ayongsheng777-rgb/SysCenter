<template>
  <div class="space-y-4">
    <div class="flex items-center justify-between">
      <h2 class="text-lg font-semibold text-accent">🤖 AI 智能待办与经验沉淀</h2>
      <button class="btn" @click="fetchTasks">🔄 刷新</button>
    </div>

    <!-- 检索 + 经验提炼 -->
    <div class="card flex flex-wrap gap-2 items-center">
      <input v-model="searchQuery" @input="onSearch" class="input flex-1 min-w-[220px]"
             placeholder="🔍 检索历史任务或 AI 诊断记录…" />
      <button class="btn btn-primary" :disabled="analyzing" @click="generateExperience">
        {{ analyzing ? '大脑运转中…' : '📚 提炼全局运维经验' }}
      </button>
    </div>

    <!-- 经验总结报告 -->
    <div v-if="experienceReport" class="card border-accent2">
      <div class="flex items-center justify-between mb-2">
        <h4 class="font-semibold text-accent2">📑 阶段性系统运维经验与避坑总结</h4>
        <button class="btn text-xs" @click="experienceReport = null">收起</button>
      </div>
      <div class="whitespace-pre-wrap text-sm leading-relaxed">{{ experienceReport }}</div>
    </div>

    <!-- 录入 -->
    <div class="card flex gap-2">
      <input v-model="newTaskText" @keyup.enter="addTask" class="input flex-1"
             placeholder="记录新问题，如：重新配置 NAS 的防火墙端口…" />
      <button class="btn btn-primary" :disabled="loading" @click="addTask">
        {{ loading ? '入库中…' : '记录并分析' }}
      </button>
    </div>

    <p v-if="!tasks.length && !loading" class="text-xs text-gray-500">暂无记录，先在上方记一条吧。</p>

    <!-- 任务列表 -->
    <ul class="space-y-2">
      <li v-for="task in tasks" :key="task.id" class="card border-l-4"
          :class="task.is_sys_scope ? 'border-l-accent' : 'border-l-edge'">
        <div class="flex items-start justify-between gap-2">
          <div class="min-w-0 flex-1">
            <div class="flex items-center gap-2 mb-1 flex-wrap">
              <span class="tag" :class="task.is_sys_scope ? 'text-accent' : 'text-gray-400'">
                {{ task.is_sys_scope ? '🖥️ 核心系统' : '📝 日常杂项' }}
              </span>
              <span class="text-xs text-gray-500">{{ (task.created_at || '').replace('T', ' ').slice(0, 16) }}</span>
            </div>
            <p class="text-sm break-words">{{ task.content }}</p>
          </div>
          <div class="flex items-center gap-1 whitespace-nowrap">
            <select v-model="task.status" @change="updateStatus(task)" class="input w-auto py-1 px-2 text-xs">
              <option value="未完成">未完成</option>
              <option value="部分完成">部分完成</option>
              <option value="已完成">已完成</option>
            </select>
            <button class="btn text-xs" :disabled="busyId === task.id" @click="fetchSuggestion(task)">💡 诊断</button>
            <button class="btn btn-danger text-xs" @click="del(task)">删</button>
          </div>
        </div>
        <div v-if="task.suggestion" class="mt-2 p-2 rounded-lg bg-panel2 border border-edge text-sm whitespace-pre-wrap leading-relaxed">
          <strong class="text-accent2">历史诊断记录：</strong>{{ task.suggestion }}
        </div>
      </li>
    </ul>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import api from '../api.js'

const tasks = ref([])
const newTaskText = ref('')
const searchQuery = ref('')
const loading = ref(false)
const analyzing = ref(false)
const busyId = ref(null)
const experienceReport = ref(null)

let _searchTimer = null
function onSearch() {
  if (_searchTimer) clearTimeout(_searchTimer)
  _searchTimer = setTimeout(fetchTasks, 300)
}

async function fetchTasks() {
  try {
    const r = await api.get('/todos', { params: { query: searchQuery.value, all: 1 } })
    tasks.value = r.data
  } catch (e) {
    if (!(e.response && e.response.status === 401)) alert('加载失败：' + ((e.response && e.response.data && e.response.data.detail) || e))
  }
}

async function addTask() {
  const content = newTaskText.value.trim()
  if (!content) return
  loading.value = true
  try {
    const r = await api.post('/todos', { content })
    newTaskText.value = ''
    tasks.value.unshift(r.data)
  } catch (e) {
    alert('记录失败：' + ((e.response && e.response.data && e.response.data.detail) || e))
  } finally {
    loading.value = false
  }
}

async function updateStatus(task) {
  busyId.value = task.id
  try {
    await api.put(`/todos/${task.id}/status`, { status: task.status })
  } catch (e) {
    alert('状态更新失败：' + ((e.response && e.response.data && e.response.data.detail) || e))
  } finally {
    busyId.value = null
  }
}

async function fetchSuggestion(task) {
  busyId.value = task.id
  const old = task.suggestion
  task.suggestion = '提取底层状态，深度分析中…'
  try {
    const r = await api.post(`/todos/${task.id}/suggest`)
    task.suggestion = r.data.suggestion
  } catch (e) {
    task.suggestion = old
    alert('诊断失败：' + ((e.response && e.response.data && e.response.data.detail) || 'AI 未启用或调用失败'))
  } finally {
    busyId.value = null
  }
}

async function del(task) {
  if (!confirm('确认删除该待办？')) return
  try {
    await api.delete(`/todos/${task.id}`)
    tasks.value = tasks.value.filter(t => t.id !== task.id)
  } catch (e) {
    alert('删除失败：' + ((e.response && e.response.data && e.response.data.detail) || e))
  }
}

async function generateExperience() {
  analyzing.value = true
  experienceReport.value = '正在拉取历史存档并交由 AI 分析系统隐患…'
  try {
    const r = await api.post('/todos/experience/analyze')
    experienceReport.value = r.data.report
  } catch (e) {
    experienceReport.value = '经验沉淀生成失败：' + ((e.response && e.response.data && e.response.data.detail) || 'AI 未启用或调用失败')
  } finally {
    analyzing.value = false
  }
}

onMounted(fetchTasks)
defineExpose({ fetchTasks })
</script>
