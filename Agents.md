# SysCenter — Agents 维护手册

> 面向智能体/维护者的速查手册：架构、AI 模型模块、SOP、踩坑。改动前先读，改完附验证。

## 0. 一句话定位

SysCenter 是 **Windows 服务器 / NAS / 局域网** 运维监控面板：FastAPI 后端 + Vue3 前端 + PostgreSQL + Redis。
AI 模块是「运维大脑」——把系统日志 / 报错丢给大模型，产出分步排障建议（诊断接口 `/api/ai/diagnose`）。

---

## 1. 部署与进程（2026-08-20 起：EXE 唯一运行方案）

| 组件 | 说明 |
|---|---|
| 应用（前端+后端） | **`D:\software\SysCenter\SysCenter.exe`**（onedir：exe + `_internal/` + 资源），直接对外 **8352**，自带 Web UI（不再需要 nginx） |
| 开机自启 | HKCU Run 键 `SysCenter`（`install` 写 / `uninstall` 删），登录自动托盘运行 |
| 托盘退出 | 托盘菜单「退出」需输 **OTP 动态码**（复用 `data/otp_secret`；tkinter 弹窗 + PowerShell InputBox 兜底） |
| Postgres | Docker 容器 `syscenter-postgres`，`127.0.0.1:5442`，库 `syscenter`（密码见 `.env`）—— **EXE 的地基，勿删** |
| Redis | Docker 容器 `syscenter-redis`，`127.0.0.1:6387` ——同上 |

⚠️ **运行形态 = SysCenter.exe + 两个地基容器**（docker-compose 已只剩 postgres/redis，nginx 已移除）。EXE 内嵌全部应用代码，**改源码后须重新构建 EXE 才生效**（见 §3.2）；旧 dev 版（`backend/.venv` 直跑 uvicorn）仅作开发调试。

---

## 2. AI 模型模块（核心）

复用本机 dragons-breath 的「OpenAI 兼容多模型层」思路：配置与代码分离，模型可热插拔。

### 2.1 架构三件套

- **`app/config.py`** — `Settings` 数据类 + `app_settings` 表（DB 覆盖 env 默认值，免重启热更新）。
- **`app/ai_client.py`** — 统一客户端：`chat()` / `chat_with_fallback()` / `chat_json_with_fallback()`。
- **`app/routers/ai.py` + `app/routers/settings.py`** — 诊断接口 + 设置读写接口。
- **前端 `frontend/src/components/Settings.vue`** — AI 模型增删改、生效模型下拉选择。

### 2.2 配置字段（`app_settings` 表）

| 键 | 含义 |
|---|---|
| `ai_enabled` | 总开关 |
| `ai_models` | 模型库 `[{id, name, base_url, model, api_key, tags, user_agent, proxy}]` |
| `ai_active` | 生效模型 id；`active_ai_profile()` 找不到就退回 env 默认 |
| `scenario_models` | 场景→模型 id（逗号分隔 = 轮循链，单值 = 固定） |

- `ai_ready`（是否可用）只看 `active` 那个模型的 key 是否有效（占位符 `your/xxx/sk-xxx/...` 视为未配置）。
- 诊断调用走 `get_scenario_fallback_chain(scenario)`：先按 `scenario_models` 取链，末尾追加 active 作为兜底。

### 2.3 `chat()` 行为（务必守住的铁律）

1. 禁用 / 无 key / 占位符 → 返回 `None`，**绝不向上抛异常**（主流程不受 AI 故障影响）。
2. 缓存：`hash(model+system+user)`，默认 TTL 900s（按场景可调）。
3. 限流：`asyncio.Semaphore(4)`。
4. **推理模型**（`_REASONING_SUBSTRINGS`：`deepseek-reasoner` / `deepseek-r1` / `deepseek-v4-pro` / `kimi-k3` / `o1` / `o3` / `qwq`，大小写不敏感子串匹配）：`max_tokens≥2000`、`timeout≥150s`；json_mode 时加 `response_format=json_object`。
5. **慢模型**（`_SLOW_SUBSTRINGS`）：`timeout≥150s`。
6. 错误码人话提示：401 Key 失效 / 403 无权限 / 404 模型名不存在 / 429 限频或欠费。
7. 用量异步落库 `ai_usage_log`（失败静默，不阻塞主链路）；面板接口 `GET /api/settings/ai-usage`。

### 2.4 已接入服务商

**DeepSeek**（默认）
- 端点 `https://api.deepseek.com/v1`，模型 `deepseek-chat`。key 留空待填。

**硅基流动 SiliconFlow**（2026-08-19 新增）
- 端点 `https://api.siliconflow.cn/v1`（OpenAI 兼容）。
- **国内节点，`proxy` 必须留空**（配 `127.0.0.1:1080` 反而连不上）。
- 已加 4 个免费档模型：
  | id | 模型 | 角色 |
  |---|---|---|
  | `siliconflow-deepseek-v3` | `deepseek-ai/DeepSeek-V3` | 主力，**已设为默认生效** |
  | `siliconflow-deepseek-r1` | `deepseek-ai/DeepSeek-R1` | 推理（走加长预算） |
  | `siliconflow-qwen3-32b` | `Qwen/Qwen3-32B` | 强力通用 |
  | `siliconflow-qwen3-8b` | `Qwen/Qwen3-8B` | 轻量快 |
- 真实 API key 存于 `app_settings.ai_models` 的 `api_key` 字段（**只落库，不进 git**）。
- 源码 `default_ai_models()` 里硅基流动条目的 `api_key` 留空：仅提供结构，真实 key 靠运行时写库或前端填。

### 2.5 AI 笔记 / 知识库（2026-08-19 新增）

第二块 AI 能力：个人笔记沉淀 + 自然语言调取。存 API Key、技术排障信息等，日后直接「问 AI」捞出来。

- **后端**：`app/routers/notes.py`（路由，前缀 `/api/notes`，需鉴权）+ `db.py` 的 `ai_notes` 表与助手函数。
- **前端**：`frontend/src/components/Notes.vue` + `App.vue` 导航「笔记/知识库」（`#/notes`）。
- **表**：`ai_notes(id, title, category[apikey|tech|other], provider, content, tags, tested[ok|fail|untested|skipped], test_result, created_at, updated_at)`；`init_pool()` 里另有幂等 `CREATE TABLE IF NOT EXISTS` 兜底（Alembic 之外也保证建表）。

**接口一览**：
| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/api/notes?q=&category=&limit=` | 关键词检索（标题/内容/标签，中文连续字、英文词分词） |
| POST | `/api/notes` | 新建；`category=apikey` 时**保存前自动探活** |
| GET/PUT/DELETE | `/api/notes/{id}` | 查/改/删；改 apikey 的 content/provider 会重新探活 |
| POST | `/api/notes/ask` | 自然语言提问 → 关键词命中笔记 → 喂大模型提炼 |

**API Key 自动探活**：`_PROVIDER_BASE = {deepseek, siliconflow, openai}` → `GET {base}/models` 带 Bearer，200=ok / 401/403=fail / 异常=网络不通。只对 `apikey` 分类触发，结果写入 `tested`/`test_result`。

**「问 AI」流程**：`ask()` 先 `db.list_notes(q=问题)` 关键词召回（无新增向量依赖，轻量）→ 命中内容拼成 corpus → `chat_with_fallback(system, user, chain=get_scenario_fallback_chain("notes"))` 提炼，system 提示「只据笔记回答、禁止编造」。命中 0 条则返回 `found=False` 提示。

> ⚠️ **坑（已修）**：corpus 里**必须**拼入 `test_result`（不只 `content`），否则问「key 还能用吗」时模型只看到一串裸 key，会答「笔记里没有相关信息」。见 `notes.py` 的 `corpus` 拼接。

**飞书入口（2026-08-19 新增）**：`feishu.py` 也接了笔记能力，双通道：
- **明确指令**（`_route_message` 路由）：`存key <服务商> <key>`（服务商可省，自动识别）、`记笔记 <内容>`、`查笔记 <关键词>`、`笔记列表`。
- **AI 自然语言**（`_cmd_ai` 改造）：system prompt 让 AI 在用户想「保存信息」时回 `{"action":"save_note",...}` JSON，后端 `ai_client._extract_json` 解析后落库（apikey 自动测）；普通问答仍纯文本不误触发。
- 复用 `notes.save_api_key_note(key, provider, title)`：显式 provider 探活通过才采用，否则回退 `detect_provider()` 自动探测。
- 回复时 key 一律脱敏（`_mask_key`：前 8 后 4）。

> ⚠️ **坑（已修）**：AI 会按 `sk-` 前缀把硅基流动 key 误判成 openai → `save_api_key_note` 里「显式 provider 测不过就自动探测」已兜住；tags 里加中文别名（`_PROVIDER_CN`），否则中文搜「硅基流动」命中不了英文 `siliconflow`。

---

## 3. SOP

### 3.1 加新服务商 / 模型

1. 确认是 OpenAI 兼容（`base_url` + `/chat/completions`）。
2. （可选）`config.py` 的 `default_ai_models()` 补默认条目，**`api_key` 留空**（防密钥进 git）。
3. 写库 `app_settings.ai_models`：合并追加
   `{id, name, base_url, model, api_key, tags, user_agent:"", proxy:""}`
   （**国内节点 proxy 留空**，境外才填宿主代理）。
4. 重启后端，或调 `PUT /api/settings` 热更新（需 admin 鉴权）。
5. 实测：直连 `ai_client.chat`，或前端「AI 诊断」跑一条真实日志。

### 3.2 改代码后的生效路径（无看门狗）

**正式运行是 EXE**：改 `backend/` 源码 → **重新构建 EXE** → 重启 EXE（托盘退出需 OTP；或 `taskkill //IM SysCenter.exe //F` 后重新启动）。

快速构建（构建 Python 必须自带 tkinter，本机用 `C:\Program Files\Python312`）：

```powershell
cd D:\WorkBuddy\SysCenter
.\packaging\windows\build.ps1 -SkipFrontend   # 产出 dist_exe\SysCenter\
# 停 EXE → 把新构建复制到 D:\software\SysCenter\（覆盖）→ 重启 EXE
```

**开发调试（只验代码，不打扰线上 EXE）**：用 dev venv 起临时实例，避开 8352：

```powershell
Start-Process -FilePath "D:\WorkBuddy\SysCenter\backend\.venv\Scripts\python.exe" `
  -ArgumentList "-m","uvicorn","app.main:app","--host","0.0.0.0","--port","8399" `
  -WorkingDirectory "D:\WorkBuddy\SysCenter\backend" -WindowStyle Hidden
```

- `main.py` 启动即 `load_runtime_settings()` 读库 → 新配置生效。
- EXE 端口 8352 监听即代表起来；若没起来查 `D:\software\SysCenter\logs\syscenter.log`（uvicorn 日志已并入该文件）。

### 3.3 验证

- **最稳**：独立脚本 `import app.ai_client` 后直接调 `ai_client.chat(model_profile=...)`，走真实代码路径（绕开鉴权与服务进程）。
- 或前端设置页看 `ai_ready` / 调一次「AI 诊断」。
- ⚠️ 本环境 PowerShell 的 stdout 常被吞；验证信息写文件后 `Read`，或用 python 打印。

---

## 4. 踩坑与注意事项

- **真实 key 永不写进源码**（防 git 泄露）；只落库 `app_settings`，或前端填写。
- **国内模型 proxy 留空**（DeepSeek / 通义 / 智谱 / 硅基流动）；境外（OpenAI/Gemini）容器内才用 `host.docker.internal:1080`。
- `load_runtime_settings()` **只在启动读库**：只改 DB 不重启、也不调 `PUT /api/settings` → 运行中的进程仍是旧配置。
- `available()` 当前返回 `settings.ai_ready`（只看 active 模型的 key）。若把唯一带 key 的模型指派给某场景而 active 无 key，该场景调用会失效——配多模型时确保 active 也有可用 key，或场景链自带兜底。
- 推理模型务必让其命中 `_REASONING_SUBSTRINGS`，否则 `max_tokens` 太小会返回空 JSON / 推理链被截断。
- 新增 OpenAI 兼容服务商时，`_provider_of()` 的 host 关键字列表（含 `siliconflow`）决定用量统计的 provider 归类，新域名记得补。
- 笔记「问 AI」(`/api/notes/ask`) 依赖 `ai_enabled && ai_ready`，否则 400；自动探活仅 `apikey` 分类触发，tech/other 一律 `untested`。

---

## 5. EXE 原生化速查（2026-08-20 落地）

- **交付位置**：`D:\software\SysCenter\`（整体挪移，勿只拷 exe）。结构：`SysCenter.exe` + `_internal/`（Python+依赖）+ `alembic.ini`/`migrations/`/`config/`/`frontend/dist/`/`.env`/`data/`（OTP 密钥等）。
- **命令**：无参数 / `start` = 托盘模式（EXE 默认）；`{version|doctor|status|install|uninstall|migrate|config|backup|restore|tray}`。`version`/`doctor` 均 RC=0。
- **自启**：`install` 写 HKCU Run `SysCenter`；`uninstall` 删；登录自动托盘运行。
- **打包（build.ps1 已固化为可复现）**：`onedir + windowed`；`--collect-all app/asyncpg/psycopg2/cryptography/pydantic/pydantic_settings/segno/pystray/PIL + lark_oapi/uvicorn/alembic`；构建 Python 必须自带 tkinter（Python 3.12）。
- **打包铁律**：① onefile 在本机挂死（火绒锁 1.1 万+ 解压文件、_MEI 目录堆积）→ 必须 onedir；② 缺 tkinter → 托盘 OTP 弹窗失效；③ 缺 `--collect-all app` → uvicorn 以字符串 `"app.main:app"` 加载，静态分析看不到，app.main/db/路由不打 → 后端起不来；④ `app/db.py` 启动迁移冻结态须用 `sys.executable` 目录找 alembic.ini/migrations，否则回退内联建表；⑤ uvicorn `log_config=None` 让日志进 `logs/syscenter.log`。
- **验证**：`version`/`doctor` RC=0；`/health` 200 且 postgres/redis up；`http://127.0.0.1:8352/` 前端页面正常。
