import { api, setToken } from './api'

export interface Me {
  id: string
  name: string
  roles: string[]
  scopes: string[]
}

export async function login(username: string, password: string): Promise<Me> {
  const res = await api<{ access_token: string }>('/auth/token', {
    method: 'POST',
    json: { username, password },
  })
  setToken(res.access_token)
  return api<Me>('/auth/me')
}

export function landingFor(roles: string[]): string {
  if (roles.includes('MINISTRY')) return '/national'
  if (roles.includes('STATE_REVENUE') || roles.includes('ADMIN_RR')) return '/national'
  if (roles.includes('COLLECTOR') || roles.includes('LAO')) return '/projects'
  if (roles.includes('AUDITOR')) return '/projects'
  if (roles.includes('RB')) return '/projects'
  return '/projects'
}
