# 楚烽数码 - AI智能待办与经验沉淀模块集成指南 (V2 存档分析版)

在原有的按需诊断基础上，本模块引入了**本地 SQLite 持久化数据库**，让记事本具备了“永久存档”与“历史检索”能力。同时，新增了**“全局经验分析 (Holistic Analysis)”**功能：AI 可以定期通读所有的历史故障与排障记录，提炼出系统的脆弱点，自动为你生成【楚烽数码专属运维经验与避坑指南】。

## 一、 核心架构升级

1. **持久化存档 (SQLite)：** 抛弃内存字典，所有的任务记录、状态变更、AI 诊断建议全部写入本地 `chufeng_tasks.db` 数据库。
2. **全文检索：** 支持随时通过关键字（如 "VPS", "NAS", "Docker", "软路由"）秒级检索过往的排障记录与 AI 建议。
3. **经验池提炼 (Experience Pool)：** 一键将历史完成的系统级任务打包发给大模型。AI 将基于你处理过的局域网冲突、路由配置或 n8n 自动化报错，总结出规律性的排障 SOP（标准作业程序）。

---

## 二、 后端接口实现 (FastAPI + SQLite)

更新 `main.py`，加入数据库初始化、历史检索接口以及全局经验分析接口。

```python
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional
import uuid
import requests
import os
import sqlite3
from datetime import datetime

app = FastAPI()

AI_API_KEY = os.getenv("DEEPSEEK_API_KEY", "your_api_key")
AI_URL = "https://api.deepseek.com/v1/chat/completions"

# 1. 初始化 SQLite 数据库
def init_db():
    with sqlite3.connect("chufeng_tasks.db") as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                content TEXT,
                is_sys_scope INTEGER,
                status TEXT,
                suggestion TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
init_db()

def get_db_connection():
    conn = sqlite3.connect("chufeng_tasks.db")
    conn.row_factory = sqlite3.Row
    return conn

class TaskItem(BaseModel):
    id: str
    content: str
    is_sys_scope: bool
    status: str
    suggestion: Optional[str] = None
    created_at: Optional[str] = None

# 2. 提交新任务并进行轻量级范畴判定
@app.post("/api/tasks", response_model=TaskItem)
def create_task(content: str):
    task_id = str(uuid.uuid4())
    prompt = f"请分析以下任务是否属于Windows运维、局域网、NAS、软路由、VPS或Docker自动化范畴。只需回答'是'或'否'。任务内容：{content}"
    
    payload = {"model": "deepseek-chat", "messages": [{"role": "user", "content": prompt}], "max_tokens": 10}
    headers = {"Authorization": f"Bearer {AI_API_KEY}", "Content-Type": "application/json"}
    
    is_scope = False
    try:
        res = requests.post(AI_URL, json=payload, headers=headers).json()
        is_scope = "是" in res['choices'][0]['message']['content']
    except:
        pass 

    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO tasks (id, content, is_sys_scope, status) VALUES (?, ?, ?, ?)",
            (task_id, content, int(is_scope), "未完成")
        )
    
    return TaskItem(id=task_id, content=content, is_sys_scope=is_scope, status="未完成")

# 3. 获取/检索任务列表 (支持按关键字搜索)
@app.get("/api/tasks", response_model=List[TaskItem])
def get_tasks(query: str = ""):
    with get_db_connection() as conn:
        if query:
            cursor = conn.execute("SELECT * FROM tasks WHERE content LIKE ? OR suggestion LIKE ? ORDER BY created_at DESC", (f"%{query}%", f"%{query}%"))
        else:
            cursor = conn.execute("SELECT * FROM tasks ORDER BY created_at DESC")
        
        tasks = []
        for row in cursor:
            tasks.append(TaskItem(
                id=row['id'], content=row['content'], is_sys_scope=bool(row['is_sys_scope']),
                status=row['status'], suggestion=row['suggestion'], created_at=row['created_at']
            ))
        return tasks

# 4. 更新任务状态
@app.put("/api/tasks/{task_id}/status")
def update_task_status(task_id: str, status: str):
    with get_db_connection() as conn:
        conn.execute("UPDATE tasks SET status = ? WHERE id = ?", (status, task_id))
    return {"status": "success"}

# 5. 按需获取 AI 见议 (并存档)
@app.post("/api/tasks/{task_id}/suggest")
def generate_suggestion(task_id: str):
    with get_db_connection() as conn:
        task = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not task: raise HTTPException(status_code=404)
        
        prompt = f"针对系统运维任务：【{task['content']}】，当前状态【{task['status']}】。请给出排障思路或具体操作见议。"
        payload = {"model": "deepseek-chat", "messages": [{"role": "user", "content": prompt}]}
        headers = {"Authorization": f"Bearer {AI_API_KEY}", "Content-Type": "application/json"}
        
        try:
            res = requests.post(AI_URL, json=payload, headers=headers).json()
            suggestion = res['choices'][0]['message']['content']
            conn.execute("UPDATE tasks SET suggestion = ? WHERE id = ?", (suggestion, task_id))
            return {"suggestion": suggestion}
        except Exception as e:
            return {"error": str(e)}

# 6. 【新增】全局历史经验提炼分析
@app.post("/api/experience/analyze")
def analyze_experience():
    with get_db_connection() as conn:
        # 获取所有系统范畴内已完成或有建议的历史任务
        cursor = conn.execute("SELECT content, suggestion FROM tasks WHERE is_sys_scope = 1 AND (status = '已完成' OR suggestion IS NOT NULL) LIMIT 50")
        history = [f"问题/任务：{row['content']} 
处理建议：{row['suggestion']}" for row in cursor]
    
    if not history:
        return {"report": "系统记录不足，暂无法生成经验总结。请积累更多排障记录。"}

    history_text = "

".join(history)
    prompt = (
        "你是一个资深IT系统架构师。以下是本中心历史的系统运维、网络管理与自动化部署记录。
"
        "请进行整体分析，提炼出【专属运维经验与避坑指南】。要求：
"
        "1. 归纳出系统最常出现的脆弱点或高频故障模块。
"
        "2. 总结出一套针对性的SOP（标准作业程序）或优化建议，防止问题复发。
"
        f"【历史记录存档】：
{history_text}"
    )
    
    payload = {"model": "deepseek-chat", "messages": [{"role": "user", "content": prompt}]}
    headers = {"Authorization": f"Bearer {AI_API_KEY}", "Content-Type": "application/json"}
    
    try:
        res = requests.post(AI_URL, json=payload, headers=headers).json()
        report = res['choices'][0]['message']['content']
        return {"report": report}
    except Exception as e:
        return {"error": str(e)}
```

---

## 三、 前端组件实现 (Vue 3 检索与经验池)

升级 `AiTodoList.vue`，增加顶部检索栏和“全局经验分析”功能区。

```vue
<template>
  <div class="ai-todo-panel">
    <div class="panel-header">
      <h3>🤖 楚烽智能待办与经验沉淀库</h3>
      <div class="header-actions">
        <!-- 全局检索 -->
        <input 
          v-model="searchQuery" 
          @input="fetchTasks" 
          placeholder="🔍 检索历史任务或报错记录..." 
          class="search-bar"
        />
        <!-- 经验提炼按钮 -->
        <button class="experience-btn" @click="generateExperience" :disabled="analyzing">
          {{ analyzing ? '大脑运转中...' : '📚 提炼全局运维经验' }}
        </button>
      </div>
    </div>

    <!-- 经验总结报告展示区 -->
    <div v-if="experienceReport" class="experience-report">
      <h4>📑 阶段性系统运维经验与避坑总结</h4>
      <div class="markdown-body">{{ experienceReport }}</div>
      <button class="close-btn" @click="experienceReport = null">收起报告</button>
    </div>
    
    <!-- 输入区 -->
    <div class="input-group">
      <input 
        v-model="newTaskText" 
        @keyup.enter="addTask" 
        placeholder="记录新问题，如：重新配置 aaPanel 的防火墙端口..."
      />
      <button :disabled="loading" @click="addTask">
        {{ loading ? '入库中...' : '记录并分析' }}
      </button>
    </div>

    <!-- 历史任务列表 -->
    <ul class="task-list">
      <li v-for="task in tasks" :key="task.id" class="task-item">
        <div class="task-header">
          <span class="task-content">
            <span v-if="task.is_sys_scope" class="badge scope-sys">🖥️ 核心系统</span>
            <span v-else class="badge scope-normal">📝 日常杂项</span>
            <span class="timestamp">[{{ task.created_at.substring(5, 16) }}]</span>
            {{ task.content }}
          </span>
          
          <div class="task-actions">
            <span :class="['status-badge', statusClass(task.status)]">{{ task.status }}</span>
            <select v-model="task.status" @change="updateStatus(task.id, task.status)" v-if="task.is_sys_scope">
              <option value="未完成">未完成</option>
              <option value="部分完成">部分完成</option>
              <option value="已完成">已完成</option>
            </select>
            <button v-if="task.is_sys_scope && task.status !== '已完成'" class="suggest-btn" @click="fetchSuggestion(task)">
              深度诊断 💡
            </button>
          </div>
        </div>
        <div v-if="task.suggestion" class="suggestion-box">
          <strong>历史诊断记录：</strong>
          <p>{{ task.suggestion }}</p>
        </div>
      </li>
    </ul>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue';
import axios from 'axios';

const api = axios.create({ baseURL: 'http://localhost:8000' });
const tasks = ref([]);
const newTaskText = ref('');
const searchQuery = ref('');
const loading = ref(false);
const analyzing = ref(false);
const experienceReport = ref(null);

const statusClass = (status) => {
  if(status === '已完成') return 'status-green';
  if(status === '部分完成') return 'status-yellow';
  return 'status-red';
};

// 检索/获取任务
const fetchTasks = async () => {
  const res = await api.get(`/api/tasks?query=${encodeURIComponent(searchQuery.value)}`);
  tasks.value = res.data;
};

// 提交任务
const addTask = async () => {
  if(!newTaskText.value.trim()) return;
  loading.value = true;
  try {
    await api.post(`/api/tasks?content=${encodeURIComponent(newTaskText.value)}`);
    newTaskText.value = '';
    fetchTasks();
  } finally {
    loading.value = false;
  }
};

const updateStatus = async (id, newStatus) => {
  await api.put(`/api/tasks/${id}/status?status=${newStatus}`);
};

const fetchSuggestion = async (task) => {
  task.suggestion = "提取底层状态，深度分析中...";
  try {
    const res = await api.post(`/api/tasks/${task.id}/suggest`);
    task.suggestion = res.data.suggestion;
  } catch (error) {
    task.suggestion = "提取失败，请检查诊断中枢。";
  }
};

// 提炼全局经验
const generateExperience = async () => {
  analyzing.value = true;
  experienceReport.value = "正在拉取历史存档... 正在将近期报错信息交由 DeepSeek 分析系统隐患...";
  try {
    const res = await api.post('/api/experience/analyze');
    experienceReport.value = res.data.report;
  } catch (error) {
    experienceReport.value = "经验沉淀生成失败。";
  } finally {
    analyzing.value = false;
  }
};

onMounted(fetchTasks);
</script>

<style scoped>
.ai-todo-panel { background: #1e293b; color: #f8fafc; padding: 20px; border-radius: 8px; }
.panel-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
.header-actions { display: flex; gap: 15px; }
.search-bar { padding: 8px 12px; border-radius: 6px; background: #0f172a; border: 1px solid #475569; color: white; width: 250px;}
.experience-btn { background: #8b5cf6; color: white; border: none; padding: 8px 15px; border-radius: 6px; cursor: pointer; font-weight: bold;}
.experience-btn:hover { background: #7c3aed; }
.experience-report { background: #312e81; padding: 20px; border-radius: 8px; margin-bottom: 20px; border: 1px solid #4338ca; }
.close-btn { margin-top: 15px; background: #4f46e5; border: none; color: white; padding: 5px 10px; border-radius: 4px; cursor: pointer;}
.input-group { display: flex; gap: 10px; margin-bottom: 20px; }
.input-group input { flex: 1; padding: 10px; border-radius: 4px; background: #334155; color: white; border: 1px solid #475569; }
.task-item { background: #0f172a; padding: 15px; margin-bottom: 10px; border-radius: 6px; list-style: none; border-left: 3px solid #475569;}
.timestamp { font-size: 0.8em; color: #94a3b8; margin-right: 8px; }
.badge { font-size: 0.8em; padding: 3px 6px; border-radius: 4px; margin-right: 8px; }
.scope-sys { background: #3b82f6; color: white; }
.scope-normal { background: #64748b; color: white; }
.status-badge { font-size: 0.85em; padding: 4px 8px; border-radius: 4px; }
.status-green { background: #10b981; }
.status-yellow { background: #f59e0b; color: black; }
.status-red { background: #ef4444; }
.task-actions select { background: #334155; color: white; border: 1px solid #475569; padding: 2px; border-radius: 4px; margin-left: 10px;}
.suggest-btn { margin-left: 10px; background: transparent; border: 1px solid #3b82f6; color: #3b82f6; cursor: pointer; padding: 4px 8px; border-radius: 4px;}
.suggest-btn:hover { background: #3b82f6; color: white; }
.suggestion-box { margin-top: 15px; background: #1e293b; padding: 12px; border-left: 4px solid #3b82f6; border-radius: 4px; font-size: 0.95em; white-space: pre-wrap; line-height: 1.6;}
</style>
