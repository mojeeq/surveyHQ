import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { api, tokenStore } from '@/lib/api'
import type { Role, User } from '@/lib/types'

interface AuthState {
  user: User | null
  loading: boolean
  signIn: (email: string, password: string) => Promise<void>
  signOut: () => void
  can: (minimum: Role) => boolean
}

const ROLE_RANK: Record<Role, number> = { viewer: 0, analyst: 1, manager: 2, admin: 3 }

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!tokenStore.get()) {
      setLoading(false)
      return
    }
    api
      .get<User>('/auth/me')
      .then(setUser)
      .catch(() => tokenStore.clear())
      .finally(() => setLoading(false))
  }, [])

  const signIn = useCallback(async (email: string, password: string) => {
    const token = await api.post<{ access_token: string }>('/auth/login', { email, password })
    tokenStore.set(token.access_token)
    setUser(await api.get<User>('/auth/me'))
  }, [])

  const signOut = useCallback(() => {
    tokenStore.clear()
    setUser(null)
    location.href = '/login'
  }, [])

  const can = useCallback(
    (minimum: Role) => (user ? ROLE_RANK[user.role] >= ROLE_RANK[minimum] : false),
    [user],
  )

  const value = useMemo(
    () => ({ user, loading, signIn, signOut, can }),
    [user, loading, signIn, signOut, can],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used inside <AuthProvider>')
  return context
}
