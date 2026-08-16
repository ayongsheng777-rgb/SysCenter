# 楚烽数码 - 飞书 Bot 双向通讯与 AI 中转改造指南

在此前的方案中，飞书仅仅被作为一个单向的“消息接收器”（Webhook 推送告警和提醒）。
为了让它成为你真正的**“随身超级管家”**，我们将通过飞书开放平台的 **Event Subscription (事件订阅)** 功能，赋予飞书 Bot 接收指令、执行系统/生活任务，以及**双向中转 AI 对话**的能力。

这意味着：你不仅能收到通知，还能直接在飞书对话框里让它“查系统状态”、“记下明天的待办”，甚至像和 DeepSeek 聊天一样向它提问。

---

## 一、 架构与通讯流程设计

1. **URL 验证与事件回调 (Webhook)：** 
   你的 FastAPI 后端需要暴露一个专门的 `/api/feishu/webhook` 接口，通过 Cloudflare Tunnel 映射到公网。飞书会将你在聊天框发送的所有消息推送到这个接口。
2. **Access Token 获取：** 
   为了让 Bot 能“回话”，后端需要使用 `APP_ID` 和 `APP_SECRET` 向飞书服务器换取 `tenant_access_token`。
3. **指令与 AI 中转路由 (Router)：**
   * **正则/指令匹配：** 如果发送的是特定指令（如 `/sys`、`/todo`），直接调用本地代码查询系统（CPU/内存）或写入生活/系统数据库，并回复结果。
   * **AI 自然语言接管：** 如果不是预设指令，系统将用户输入的内容提取出来，透传给 DeepSeek API（系统设定其身份为“楚烽数码全能AI管家”），并将 DeepSeek 的推理结果通过飞书回复给用户。

---

## 二、 核心后端代码改造 (`feishu_bot.py`)

建议将飞书处理逻辑独立为一个模块，然后在 `main.py` 中引入。以下为完整的飞书双向通讯、鉴权验证与 AI 对话集成的代码。

```python
import os
import json
import requests
from fastapi import APIRouter, Request, BackgroundTasks
import sqlite3
import psutil

feishu_router = APIRouter()

# 飞书应用凭证 (在飞书开发者后台获取)
FEISHU_APP_ID = os.getenv("FEISHU_APP_ID", "cli_your_app_id")
FEISHU_APP_SECRET = os.getenv("FEISHU_APP_SECRET", "your_app_secret")

# AI 凭证
AI_API_KEY = os.getenv("DEEPSEEK_API_KEY", "your_deepseek_key")
AI_URL = "https://api.deepseek.com/v1/chat/completions"

# --- 1. 飞书 Token 与发送消息工具 ---
def get_tenant_access_token():
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    payload = {"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET}
    res = requests.post(url, json=payload).json()
    return res.get("tenant_access_token")

def reply_feishu_msg(message_id: str, text: str):
    token = get_tenant_access_token()
    url = f"https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/reply"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {
        "msg_type": "text",
        "content": json.dumps({"text": text})
    }
    requests.post(url, headers=headers, json=payload)

# --- 2. 消息路由与 AI 中转处理核心逻辑 ---
def process_feishu_message(text: str, message_id: str):
    text = text.strip()
    
    # 场景 A: IT 系统管理快捷指令
    if text.startswith("/sys"):
        cpu = psutil.cpu_percent(interval=1)
        mem = psutil.virtual_memory().percent
        reply_feishu_msg(message_id, f"🖥️ [楚烽系统状态]
CPU占用: {cpu}%
内存占用: {mem}%")
        return

    # 场景 B: 生活记事快捷写入 (例如: /记事 星期天去宜昌玩)
    elif text.startswith("/记事"):
        content = text.replace("/记事", "").strip()
        if content:
            # 此处调用前面生活版的写入逻辑 (简化示意)
            with sqlite3.connect("chufeng_life.db") as conn:
                conn.execute(
                    "INSERT INTO life_tasks (id, content, is_todo_scope, status) VALUES (?, ?, ?, ?)",
                    (str(os.urandom(8).hex()), content, 1, "未完成")
                )
            reply_feishu_msg(message_id, f"✅ 已成功记入生活记事本并开始后台监控：\n{content}")
        return

    # 场景 C: 未命中指令，自动转接 DeepSeek AI 进行日常对话与排障支持
    else:
        prompt = (
            "你是楚烽数码(Chufeng Digital)的专属AI智能管家，懂IT运维（VPS、NAS、Docker）、也负责生活行程规划与建议。
"
            f"主人发送了以下消息，请直接且自然地回复他：\n{text}"
        )
        payload = {"model": "deepseek-chat", "messages": [{"role": "user", "content": prompt}]}
        headers = {"Authorization": f"Bearer {AI_API_KEY}", "Content-Type": "application/json"}
        
        try:
            res = requests.post(AI_URL, json=payload, headers=headers).json()
            ai_reply = res['choices'][0]['message']['content']
            reply_feishu_msg(message_id, f"🤖 {ai_reply}")
        except Exception as e:
            reply_feishu_msg(message_id, "⚠️ AI大脑连接超时，请稍后再试。")

# --- 3. 飞书 Webhook 接收端点 ---
@feishu_router.post("/api/feishu/webhook")
async def feishu_webhook(request: Request, background_tasks: BackgroundTasks):
    data = await request.json()

    # (1) 飞书后台配置 URL 时的握手验证 (非常重要，否则飞书后台会提示验证失败)
    if "challenge" in data:
        return {"challenge": data["challenge"]}

    # (2) 过滤事件类型，拦截用户发送的文本消息
    header = data.get("header", {})
    if header.get("event_type") == "im.message.receive_v1":
        event = data.get("event", {})
        message = event.get("message", {})
        
        if message.get("message_type") == "text":
            try:
                # 解析消息体 json 字符串
                content_dict = json.loads(message.get("content", "{}"))
                text = content_dict.get("text", "")
                message_id = message.get("message_id")
                
                # 放入后台任务异步处理，避免阻塞飞书的回调，导致飞书重试发信
                background_tasks.add_task(process_feishu_message, text, message_id)
            except Exception as e:
                print(f"Error parsing message: {e}")

    return {"msg": "success"}
```

然后，在你的主入口 `main.py` 中挂载这个路由器：
```python
from fastapi import FastAPI
from feishu_bot import feishu_router

app = FastAPI()
app.include_router(feishu_router)
```

---

## 三、 飞书开放平台配置详细指南 (重点踩坑防范)

飞书的双向通讯配置比较严格，请务必按以下步骤在 [飞书开发者后台](https://open.feishu.cn/app/) 操作：

1. **获取 App 凭证：**
   进入应用详情 $ightarrow$ 左侧导航栏【凭证与基础信息】 $ightarrow$ 获取 `App ID` 和 `App Secret`，填入你的环境变量中。
2. **开通机器人能力：**
   左侧导航栏 $ightarrow$ 【添加应用能力】 $ightarrow$ 添加【机器人】能力。
3. **权限管理配置 (极其重要)：**
   左侧导航栏 $ightarrow$ 【权限管理】 $ightarrow$ 搜索并开通以下权限（需要发布版本后生效）：
   * `im:message.p2p_msg` (获取单聊消息)
   * `im:message` (获取与发送单聊、群组消息)
   * `im:message.group_at_msg` (获取群组中@机器人的消息)
4. **配置事件订阅与 URL：**
   左侧导航栏 $ightarrow$ 【事件订阅】。
   * **请求地址配置：** 填入你的 Cloudflare Tunnel 外网地址加上接口路径。例如：`https://your-tunnel.com/api/feishu/webhook`。
   * **保存验证：** 点击保存时，飞书会向该地址发送带有 `challenge` 的 JSON。上面的代码已经包含了验证逻辑，只要你服务端运行正常，这里就会验证通过。
   * **添加具体事件：** 在事件订阅列表里，添加 `接收消息 v2.0 (im.message.receive_v1)` 事件。
5. **版本发布：**
   最后在左侧导航栏点击【版本管理与发布】，创建一个新版本并申请发布。审核通过后，你就可以在飞书上搜索到该应用，并进行聊天了。

## 四、 项目协调与扩展说明

通过此次改造：
* **单聊当客服：** 飞书对话框变成了 Chufeng 系统和生活中心的统一入口。
* **随时记入：** 突然有个灵感，或者发现一台机器网络不对，直接在手机打开飞书发一句：“/记事 检查192.168.1.10的Docker容器”，后台数据库就能自动存档、后续AI生成操作建议。
* **双模态响应：** 加了 `/` 前缀的就是硬核脚本控制，不加前缀的就是调用的 DeepSeek 分析。实现了无缝的自然语言交互。

你可以先将此段代码加入现有框架，配置飞书开发者后台打通内网。测试确认可以在飞书上收到机器人的闲聊回复和 `/sys` 系统状态回复后，我们再进一步细化指令逻辑！
