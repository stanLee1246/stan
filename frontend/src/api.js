import { reactive } from 'vue'

export const auth = reactive({ user: null, ready: false })
export const preferences = reactive({ demo: sessionStorage.getItem('career-demo') === 'true' })

export function setDemo(value) {
  preferences.demo = value
  sessionStorage.setItem('career-demo', String(value))
}

export async function api(path, options = {}) {
  const token = sessionStorage.getItem('career-token')
  const headers = { 'Content-Type': 'application/json', ...options.headers }
  if (token) headers.Authorization = `Bearer ${token}`
  let response
  try {
    response = await fetch(`/api${path}`, { ...options, headers, body: options.body === undefined ? undefined : JSON.stringify(options.body) })
  } catch {
    throw new Error('无法连接后端，请确认本地后端已启动。')
  }
  const result = await response.json().catch(() => ({}))
  if (!response.ok) {
    if (response.status === 401) { auth.user = null; sessionStorage.removeItem('career-token') }
    const message = Array.isArray(result.detail) ? result.detail.map(x => `${x.loc.slice(1).join('.')}: ${x.msg}`).join('；') : result.detail
    throw new Error(message || `请求失败（${response.status}）`)
  }
  return result
}

export async function restoreAuth() {
  if (sessionStorage.getItem('career-token')) {
    try { auth.user = await api('/auth/me') } catch { auth.user = null }
  }
  auth.ready = true
}

export async function login(body) {
  const result = await api('/auth/login', { method: 'POST', body })
  sessionStorage.setItem('career-token', result.token)
  auth.user = result.user
}

export async function logout() {
  try { await api('/auth/logout', { method: 'POST' }) }
  finally { sessionStorage.removeItem('career-token'); auth.user = null }
}

export const paths = { employment: '企业就业', postgraduate: '升学', civil_service: '公务员', public_institution: '事业单位', internship: '实习', unresolved: '待落实', other: '其他' }
export const displayDate = value => value ? value.slice(0, 10) : '待核对'
