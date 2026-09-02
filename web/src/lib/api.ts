/** API client. Auth token + demo date live in localStorage; every request carries both. */

export const API_BASE: string =
  (import.meta as any).env?.VITE_API_BASE || '/api/v1'

export function getToken(): string | null {
  return localStorage.getItem('bhuarjan.token')
}

export function setToken(t: string | null) {
  if (t) localStorage.setItem('bhuarjan.token', t)
  else localStorage.removeItem('bhuarjan.token')
}

export function getDemoDate(): string | null {
  return localStorage.getItem('bhuarjan.demoDate')
}

export function setDemoDate(d: string | null) {
  if (d) localStorage.setItem('bhuarjan.demoDate', d)
  else localStorage.removeItem('bhuarjan.demoDate')
}

export class ApiError extends Error {
  status: number
  problem: any
  constructor(status: number, problem: any) {
    super(problem?.detail || problem?.title || `HTTP ${status}`)
    this.status = status
    this.problem = problem
  }
}

export async function api<T = any>(
  path: string,
  init: RequestInit & { json?: any } = {},
): Promise<T> {
  const headers: Record<string, string> = {
    ...(init.headers as Record<string, string> | undefined),
  }
  const token = getToken()
  if (token) headers['Authorization'] = `Bearer ${token}`
  const demoDate = getDemoDate()
  if (demoDate) headers['X-Demo-Date'] = demoDate
  let body = init.body
  if (init.json !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(init.json)
  }
  const res = await fetch(`${API_BASE}${path}`, { ...init, headers, body })
  if (res.status === 401) {
    setToken(null)
    if (!location.pathname.startsWith('/login') && !location.pathname.startsWith('/public')) {
      location.href = '/login'
    }
  }
  if (!res.ok) {
    let problem: any = null
    try {
      problem = await res.json()
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, problem)
  }
  if (res.status === 204) return undefined as T
  return res.json()
}

/** Text-bodied GET (YAML, unified diffs) with the same auth/demo-date headers and 401 handling as api(). */
export async function apiText(path: string, init: RequestInit = {}): Promise<string> {
  const headers: Record<string, string> = { ...(init.headers as Record<string, string> | undefined) }
  const token = getToken()
  if (token) headers['Authorization'] = `Bearer ${token}`
  const demoDate = getDemoDate()
  if (demoDate) headers['X-Demo-Date'] = demoDate
  const res = await fetch(`${API_BASE}${path}`, { ...init, headers })
  if (res.status === 401) {
    setToken(null)
    if (!location.pathname.startsWith('/login') && !location.pathname.startsWith('/public')) {
      location.href = '/login'
    }
  }
  if (!res.ok) {
    let problem: any = null
    try {
      problem = await res.json()
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, problem)
  }
  return res.text()
}

export function uploadForm<T = any>(path: string, form: FormData): Promise<T> {
  return api<T>(path, { method: 'POST', body: form })
}

/** ₹ from integer paise, Indian grouping, lakh/crore. */
export function formatINR(paise: number | string | null | undefined): string {
  const p = Number(paise || 0)
  const rupees = p / 100
  if (Math.abs(rupees) >= 1e7) return `₹${(rupees / 1e7).toFixed(2)} Cr`
  if (Math.abs(rupees) >= 1e5) return `₹${(rupees / 1e5).toFixed(2)} L`
  return `₹${rupees.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`
}

export function formatDate(d: string | null | undefined): string {
  if (!d) return '—'
  const [y, m, day] = d.split('-')
  return `${day}-${m}-${y}`
}
