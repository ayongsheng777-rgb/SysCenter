<template>
  <div class="space-y-4">
    <div class="flex items-center justify-between">
      <h2 class="text-lg font-semibold text-accent">设置中心</h2>
      <button class="btn btn-primary" :disabled="saving" @click="save">{{ saving ? '保存中…' : '💾 保存全部' }}</button>
    </div>

    <!-- AI 模型 -->
    <div class="card space-y-3">
      <div class="flex items-center justify-between">
        <p class="font-semibold">AI 诊断大脑（多模型）</p>
        <label class="text-xs"><input type="checkbox" v-model="f.ai_enabled" /> 启用</label>
      </div>
      <div v-for="(m, i) in f.ai_models" :key="i" class="border border-edge rounded-lg p-2 space-y-1">
        <div class="grid grid-cols-2 md:grid-cols-3 gap-2">
          <input v-model="m.id" class="input" placeholder="id" />
          <input v-model="m.name" class="input" placeholder="名称" />
          <input v-model="m.model" class="input" placeholder="模型名" />
          <input v-model="m.base_url" class="input" placeholder="Base URL" />
          <input v-model="m.api_key" class="input" :placeholder="secretPlaceholder(m.api_key)" />
          <input v-model="m.tags" class="input" placeholder="标签(逗号)" @input="m.tags = $event.target.value" />
        </div>
        <button class="btn btn-danger text-xs" @click="f.ai_models.splice(i, 1)">移除该模型</button>
      </div>
      <button class="btn text-xs" @click="addModel">+ 新增模型</button>
      <div class="grid grid-cols-2 gap-2">
        <div><label class="text-xs text-gray-400">生效模型(ai_active)</label>
          <select v-model="f.ai_active" class="input"><option v-for="m in f.ai_models" :key="m.id" :value="m.id">{{ m.id }}</option></select></div>
        <div><label class="text-xs text-gray-400">场景模型映射(scenario_models JSON)</label>
          <input v-model="scenarioJson" class="input" placeholder='{"diagnose":"deepseek"}' /></div>
      </div>
    </div>

    <!-- 飞书 -->
    <div class="card space-y-2">
      <div class="flex items-center justify-between">
        <p class="font-semibold">飞书集成（告警推送 + 双向 bot）</p>
        <label class="text-xs"><input type="checkbox" v-model="f.feishu_enabled" /> 启用</label>
      </div>
      <input v-model="f.feishu_webhook" class="input" placeholder="Webhook 地址（告警推送）" />
      <input v-model="f.feishu_secret" class="input" :placeholder="secretPlaceholder(f.feishu_secret)" />
      <button class="btn text-xs w-fit" @click="testFeishu">发送测试消息</button>
      <hr class="border-edge my-1" />
      <p class="text-xs text-gray-400">双向 bot（智能体，WebSocket 长连接）</p>
      <div class="flex items-center gap-2">
        <button class="btn text-xs w-fit" :disabled="feishuQr.loading" @click="startFeishuQr">📷 扫码绑定（推荐）</button>
        <span class="text-xs text-gray-500">或手填下方自建应用凭据</span>
      </div>
      <input v-model="f.feishu_app_id" class="input" placeholder="App ID（飞书开放平台自建应用）" />
      <input v-model="f.feishu_app_secret" class="input" :placeholder="secretPlaceholder(f.feishu_app_secret)" />
      <input v-model="f.feishu_admin_users" class="input" placeholder="管理员 open_id（逗号分隔；留空则首次私聊自动配对）" />
      <!-- 飞书扫码弹层 -->
      <div v-if="feishuQr.show" class="mt-2 p-3 rounded-lg border border-edge bg-panel2 space-y-2">
        <p class="text-xs text-gray-400">用飞书 App 扫码，在飞书官方页点授权（二维码指向飞书官方，不经本站）</p>
        <div class="flex justify-center">
          <img v-if="feishuQr.qr" :src="feishuQr.qr" alt="飞书绑定二维码" class="w-48 h-48 rounded bg-white" />
        </div>
        <p v-if="feishuQr.status === 'waiting'" class="text-xs text-center text-gray-400">等待扫码授权…（{{ feishuQr.remain }}s）</p>
        <p v-else-if="feishuQr.status === 'success'" class="text-xs text-center text-ok">✅ 绑定成功，凭据已自动填入并启用</p>
        <p v-else-if="feishuQr.status === 'expired'" class="text-xs text-center text-danger">⚠️ 二维码已过期，请重新生成</p>
        <p v-else-if="feishuQr.status === 'fail'" class="text-xs text-center text-danger">⚠️ {{ feishuQr.message || '授权失败' }}</p>
        <button class="btn text-xs w-fit" @click="closeFeishuQr">关闭</button>
      </div>
    </div>

    <!-- OTP 二次验证（换绑） -->
    <div class="card space-y-2">
      <p class="font-semibold">OTP 二次验证（换绑验证器）</p>
      <p class="text-xs text-gray-400">更换手机/验证器时：输入当前 6 位动态码验证身份 → 生成新二维码重新扫码绑定（旧令牌立即失效）。</p>
      <div class="flex items-center gap-2">
        <input v-model="otpRebind.code" maxlength="6" class="input w-32 text-center tracking-[0.4em] text-lg" placeholder="••••••" />
        <button class="btn btn-primary text-xs" :disabled="otpRebind.loading" @click="rebindOtp">换绑 / 重新扫码</button>
      </div>
      <p v-if="otpRebind.err" class="text-xs text-danger">{{ otpRebind.err }}</p>
      <p v-if="otpRebind.msg" class="text-xs text-ok">{{ otpRebind.msg }}</p>
      <div v-if="otpRebind.qr" class="space-y-1">
        <p class="text-xs text-gray-400">用新验证器扫描此二维码绑定：</p>
        <div class="flex justify-center">
          <img :src="otpRebind.qr" alt="新 OTP 二维码" class="w-44 h-44 rounded bg-white" />
        </div>
        <p class="text-xs break-all text-accent2">otpauth: {{ otpRebind.uri || '' }}</p>
      </div>
    </div>

    <!-- 监控目标 -->
    <div class="card grid grid-cols-2 gap-2">
      <p class="col-span-2 font-semibold">监控目标</p>
      <input v-model="f.lan_subnet" class="input" placeholder="局域网网段(如 192.168.1)" />
      <input v-model="f.nas_host" class="input" placeholder="NAS 主机" />
      <input v-model.number="f.nas_port" class="input" type="number" placeholder="NAS 端口" />
      <input v-model="f.tv_host" class="input" placeholder="TV 盒子 IP" />
    </div>

    <!-- 自动化 -->
    <div class="card space-y-2">
      <div class="flex items-center justify-between">
        <p class="font-semibold">自动化剧本中枢（n8n）</p>
        <label class="text-xs"><input type="checkbox" v-model="f.automation_enabled" /> 启用</label>
      </div>
      <input v-model="f.n8n_webhook_base" class="input" placeholder="n8n Webhook Base，如 http://host.docker.internal:5678/webhook" />
    </div>

    <!-- 健康检查 -->
    <div class="card grid grid-cols-2 gap-2">
      <p class="col-span-2 font-semibold">定时健康检查 / 告警</p>
      <label class="text-xs col-span-2"><input type="checkbox" v-model="f.health_check_enabled" /> 启用定时检查</label>
      <input v-model.number="f.health_check_interval" class="input" type="number" placeholder="检查间隔(秒)" />
      <div></div>
      <input v-model.number="f.alert_cpu_threshold" class="input" type="number" placeholder="CPU 告警阈值%" />
      <input v-model.number="f.alert_ram_threshold" class="input" type="number" placeholder="内存告警阈值%" />
      <input v-model.number="f.alert_disk_threshold" class="input" type="number" placeholder="磁盘告警阈值%" />
    </div>

    <p v-if="msg" class="text-sm" :class="ok ? 'text-ok' : 'text-danger'">{{ msg }}</p>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import api, { setToken } from '../api.js'

const f = reactive({
  ai_enabled: false, ai_models: [], ai_active: 'default', scenario_models: {},
  feishu_enabled: false, feishu_webhook: '', feishu_secret: '', feishu_default_chat: '',
  feishu_app_id: '', feishu_app_secret: '', feishu_admin_users: '',
  automation_enabled: false, n8n_webhook_base: '',
  lan_subnet: '', nas_host: '', nas_port: 5000, tv_host: '',
  health_check_enabled: true, health_check_interval: 300,
  alert_cpu_threshold: 90, alert_ram_threshold: 90, alert_disk_threshold: 90,
})
const scenarioJson = ref('{}')
const saving = ref(false)
const msg = ref('')
const ok = ref(true)

// OTP 换绑
const otpRebind = reactive({ code: '', loading: false, err: '', msg: '', qr: '', uri: '' })
// 飞书扫码绑定
const feishuQr = reactive({ show: false, loading: false, qr: '', pollToken: '', status: '', message: '', remain: 0, _timer: null })

function secretPlaceholder(v) { return v && v.startsWith('****') ? '（已配置，留空不修改）' : '密钥' }

function addModel() { f.ai_models.push({ id: 'm' + Date.now(), name: '', base_url: '', model: '', api_key: '', tags: '' }) }

async function load() {
  const r = await api.get('/settings')
  const rt = r.data.runtime
  for (const k of Object.keys(f)) {
    if (k in rt) {
      let v = rt[k]
      if (k === 'ai_models' && typeof v === 'string') { try { v = JSON.parse(v) } catch { v = [] } }
      if (k === 'scenario_models' && typeof v === 'string') { try { v = JSON.parse(v) } catch { v = {} } }
      if (k === 'feishu_admin_users' && Array.isArray(v)) v = v.join(', ')
      f[k] = v
    }
  }
  scenarioJson.value = JSON.stringify(f.scenario_models || {})
}

async function save() {
  saving.value = true; msg.value = ''
  const items = {}
  for (const k of Object.keys(f)) {
    let v = f[k]
    if (k === 'scenario_models') { try { v = JSON.parse(scenarioJson.value || '{}') } catch { v = {} } }
    if (k === 'ai_models') v = v.map(m => ({ ...m, tags: Array.isArray(m.tags) ? m.tags : (m.tags || '').split(',').map(s => s.trim()).filter(Boolean) }))
    if (k === 'feishu_admin_users') v = String(v || '').split(',').map(s => s.trim()).filter(Boolean)
    // 密钥占位符不覆盖
    if ((k === 'feishu_secret' || k === 'feishu_app_secret') && typeof v === 'string' && v.startsWith('****')) continue
    items[k] = v
  }
  try {
    await api.put('/settings', { items })
    ok.value = true; msg.value = '已保存并热生效'
    await load()
  } catch (e) { ok.value = false; msg.value = '保存失败：' + ((e.response && e.response.data && e.response.data.detail) || e) }
  finally { saving.value = false }
}

async function testFeishu() {
  try { await api.post('/notify/feishu/test'); alert('测试消息已发送，请查看飞书') }
  catch (e) { alert('失败：' + ((e.response && e.response.data && e.response.data.detail) || e)) }
}

// OTP 换绑：验证旧动态码 → 换新二维码 → 旧令牌立即失效，强制重新登录
async function rebindOtp() {
  otpRebind.err = ''; otpRebind.msg = ''; otpRebind.qr = ''; otpRebind.uri = ''
  const code = (otpRebind.code || '').trim()
  if (!/^\d{6}$/.test(code)) { otpRebind.err = '请输入当前 6 位动态码'; return }
  otpRebind.loading = true
  try {
    const r = await api.post('/auth/reset', { otp: code })
    otpRebind.qr = r.data.qr || ''
    otpRebind.uri = r.data.otpauth_uri || ''
    otpRebind.code = ''
    otpRebind.err = ''
    // 后端已清空全部会话令牌；此处清除本地令牌（记忆）并跳回登录页
    setToken('')
    otpRebind.msg = '✅ 换绑成功：旧动态码已失效，请用新验证器扫码后重新登录…'
    setTimeout(() => { location.hash = '#/login' }, 1500)
  } catch (e) {
    otpRebind.err = (e.response && e.response.data && e.response.data.detail) || '换绑失败'
  } finally { otpRebind.loading = false }
}

// 飞书扫码绑定：取官方二维码 → 轮询授权结果
async function startFeishuQr() {
  closeFeishuQr()
  feishuQr.show = true; feishuQr.loading = true; feishuQr.status = 'waiting'; feishuQr.message = ''
  try {
    const r = await api.post('/feishu/bot/qrcode')
    feishuQr.qr = r.data.qr || ''
    feishuQr.pollToken = r.data.poll_token || ''
    feishuQr.remain = r.data.expires_in || 300
    feishuQr.loading = false
    pollFeishuQr()
  } catch (e) {
    feishuQr.loading = false
    feishuQr.status = 'fail'
    feishuQr.message = (e.response && e.response.data && e.response.data.detail) || '获取二维码失败'
  }
}

function pollFeishuQr() {
  if (feishuQr._timer) clearInterval(feishuQr._timer)
  feishuQr._timer = setInterval(async () => {
    if (feishuQr.remain > 0) feishuQr.remain -= 1
    if (!feishuQr.pollToken) return
    try {
      const r = await api.get('/feishu/bot/qrcode/status?token=' + encodeURIComponent(feishuQr.pollToken))
      const st = r.data.status
      if (st === 'success') {
        feishuQr.status = 'success'
        clearInterval(feishuQr._timer); feishuQr._timer = null
        if (r.data.app_id) f.feishu_app_id = r.data.app_id
        f.feishu_enabled = true
        await load()
      } else if (st === 'expired' || st === 'fail') {
        feishuQr.status = st
        feishuQr.message = r.data.message || ''
        clearInterval(feishuQr._timer); feishuQr._timer = null
      }
    } catch (e) { /* 轮询中忽略偶发错误，继续等 */ }
  }, 2000)
}

function closeFeishuQr() {
  if (feishuQr._timer) { clearInterval(feishuQr._timer); feishuQr._timer = null }
  feishuQr.show = false; feishuQr.qr = ''; feishuQr.pollToken = ''; feishuQr.status = ''; feishuQr.message = ''
}

onMounted(load)
defineExpose({ load })
</script>
