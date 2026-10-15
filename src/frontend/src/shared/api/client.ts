/** Cliente HTTP centralizado. Sin URLs hardcodeadas: base por env. */

import type { User } from '../store/session'

const API_BASE_URL: string =
  import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api'

export interface HealthStatus {
  status: 'ok'
}

function isHealthStatus(data: unknown): data is HealthStatus {
  if (typeof data !== 'object' || data === null) {
    return false
  }
  return (data as { status?: unknown }).status === 'ok'
}

export async function getHealth(signal?: AbortSignal): Promise<HealthStatus> {
  const res = await fetch(`${API_BASE_URL}/health`, { signal })
  if (!res.ok) {
    throw new Error(`GET /health falló con status ${res.status}`)
  }
  const data: unknown = await res.json()
  if (!isHealthStatus(data)) {
    throw new Error('Respuesta de /health inválida')
  }
  return data
}

export interface LoginResponse {
  access_token: string
  token_type: string
  user: User
}

export async function apiLogin(email: string, password: string): Promise<LoginResponse> {
  const res = await fetch(`${API_BASE_URL}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  })
  if (!res.ok) {
    const errData = await res.json().catch(() => ({}))
    throw new Error((errData as { detail?: string }).detail || `Login falló con status ${res.status}`)
  }
  return res.json()
}

export async function apiLogout(token: string): Promise<void> {
  await fetch(`${API_BASE_URL}/auth/logout`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
  })
}

export async function apiGetMe(token: string): Promise<User> {
  const res = await fetch(`${API_BASE_URL}/auth/me`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) {
    throw new Error('No se pudo obtener el perfil de usuario')
  }
  return res.json()
}

export async function apiRefresh(): Promise<{ access_token: string; token_type: string }> {
  const res = await fetch(`${API_BASE_URL}/auth/refresh`, {
    method: 'POST',
  })
  if (!res.ok) {
    throw new Error('Refresh token inválido o expirado')
  }
  return res.json()
}

export { API_BASE_URL }
