/** Store de autenticación y sesión con Zustand. */

import { create } from 'zustand'

export interface User {
  id: string
  email: string
  rol: 'secretaria' | 'odontologo'
}

interface SessionState {
  token: string | null
  user: User | null
  setSession: (token: string, user: User) => void
  clear: () => void
}

export const useSessionStore = create<SessionState>()((set) => ({
  token: localStorage.getItem('auth_token'),
  user: localStorage.getItem('auth_user') ? JSON.parse(localStorage.getItem('auth_user')!) : null,
  setSession: (token: string, user: User) => {
    localStorage.setItem('auth_token', token)
    localStorage.setItem('auth_user', JSON.stringify(user))
    set({ token, user })
  },
  clear: () => {
    localStorage.removeItem('auth_token')
    localStorage.removeItem('auth_user')
    set({ token: null, user: null })
  },
}))
