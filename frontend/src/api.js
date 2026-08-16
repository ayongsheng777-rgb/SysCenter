import axios from 'axios'

const TOKEN_KEY = 'syscenter_token'

export function getToken() {
  return localStorage.getItem(TOKEN_KEY) || ''
}
export function setToken(t) {
  if (t) localStorage.setItem(TOKEN_KEY, t)
  else localStorage.removeItem(TOKEN_KEY)
}

const api = axios.create({ baseURL: '/api' })

api.interceptors.request.use((config) => {
  const t = getToken()
  if (t) config.headers['Authorization'] = 'Bearer ' + t
  return config
})

api.interceptors.response.use(
  (r) => r,
  (err) => {
    // 后端统一错误格式为 {success,code,message,request_id}；为兼容旧组件读取
    // `.detail` 的习惯，补一个 detail 别名，避免大范围改动前端组件。
    if (err.response && err.response.data && err.response.data.message && !err.response.data.detail) {
      err.response.data.detail = err.response.data.message
    }
    // 401 = 未认证/令牌失效。仅当本次请求【带令牌】时才清令牌回登录页
    // （说明会话确实过期）；若请求本就无令牌，只代表"未登录"，不清令牌、不踢人，
    // 避免登录瞬间令牌尚未写入的竞态把刚登录的用户弹回登录页（闪退）。
    if (err.response && err.response.status === 401) {
      if (getToken()) {
        setToken('')
        if (location.hash !== '#/login') location.hash = '#/login'
      }
    }
    return Promise.reject(err)
  }
)

export default api
