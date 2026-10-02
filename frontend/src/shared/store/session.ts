/** Store base de sesión (placeholder, sin auth real hasta C-03). */

import { create } from 'zustand'

interface SessionState {
  token: string | null
  setToken: (token: string | null) => void
  clear: () => void
}

export const useSessionStore = create<SessionState>()((set) => ({
  token: null,
  setToken: (token: string | null) => set({ token }),
  clear: () => set({ token: null }),
}))
