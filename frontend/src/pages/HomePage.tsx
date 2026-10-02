/** Shell mínima: muestra el estado de GET /api/health. */

import { useEffect, useState } from 'react'
import { getHealth } from '../shared/api/client.ts'

type BackendState = 'cargando' | 'ok' | 'error'

export default function HomePage() {
  const [backend, setBackend] = useState<BackendState>('cargando')

  useEffect(() => {
    const controller = new AbortController()
    getHealth(controller.signal)
      .then(() => setBackend('ok'))
      .catch((err: unknown) => {
        if (err instanceof DOMException && err.name === 'AbortError') {
          return
        }
        setBackend('error')
      })
    return () => controller.abort()
  }, [])

  return (
    <main className="mx-auto max-w-xl p-8">
      <h1 className="text-2xl font-semibold">Turnos Odontología</h1>
      <p className="mt-2">
        Estado del backend:{' '}
        {backend === 'cargando' ? (
          <span>consultando /api/health…</span>
        ) : backend === 'ok' ? (
          <span className="font-medium text-green-700">ok</span>
        ) : (
          <span className="font-medium text-red-700">
            no disponible (levantá la API en :8000)
          </span>
        )}
      </p>
    </main>
  )
}
