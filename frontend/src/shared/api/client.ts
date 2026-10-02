/** Cliente HTTP centralizado. Sin URLs hardcodeadas: base por env. */

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

export { API_BASE_URL }
