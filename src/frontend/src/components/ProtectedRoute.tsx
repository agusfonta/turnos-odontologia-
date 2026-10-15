import React from 'react'
import { useSessionStore } from '../shared/store/session'

interface ProtectedRouteProps {
  children: React.ReactNode
  requiredRole?: 'secretaria' | 'odontologo'
}

export const ProtectedRoute: React.FC<ProtectedRouteProps> = ({ children, requiredRole }) => {
  const { token, user } = useSessionStore()

  if (!token || !user) {
    return (
      <div className="p-8 text-center">
        <h2 className="text-xl font-bold mb-2">Acceso No Autorizado</h2>
        <p className="text-gray-600 mb-4">Debe iniciar sesión para acceder a esta sección.</p>
        <a href="/login" className="text-blue-600 underline">Ir al Login</a>
      </div>
    )
  }

  if (requiredRole && user.rol !== requiredRole) {
    return (
      <div className="p-8 text-center">
        <h2 className="text-xl font-bold mb-2 text-red-600">Acceso Denegado (403)</h2>
        <p className="text-gray-600">No cuenta con el rol requerido ({requiredRole}) para ver esta página.</p>
      </div>
    )
  }

  return <>{children}</>
}
