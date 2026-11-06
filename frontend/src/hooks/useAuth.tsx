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

export interface SignupInput {
  username: string
  email: string
  full_name: string
  password: string
}

interface AuthState {
  user: User | null
  loading: boolean
  signIn: (identifier: string, password: string) => Promise<void>
  signUp: (input: SignupInput) => Promise<void>
  signOut: () => void
  can: (minimum: Role) => boolean
  /** Called after a forced password change, so the gate lifts without a reload. */
  refresh: () => Promise<void>
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

  const establishSession = useCallback(async (accessToken: string) => {
    tokenStore.set(accessToken)
    try {
      setUser(await api.get<User>('/auth/me'))
    } catch (error) {
      tokenStore.clear()
      throw error
    }
  }, [])

  const signIn = useCallback(
    async (identifier: string, password: string) => {
      const token = await api.post<{ access_token: string }>('/auth/login', {
        identifier,
        password,
      })
      await establishSession(token.access_token)
    },
    [establishSession],
  )

  const signUp = useCallback(
    async (input: SignupInput) => {
      const token = await api.post<{ access_token: string }>('/auth/signup', input)
      await establishSession(token.access_token)
    },
    [establishSession],
  )

  const signOut = useCallback(() => {
    tokenStore.clear()
    setUser(null)
    location.href = '/login'
  }, [])

  const refresh = useCallback(async () => {
    setUser(await api.get<User>('/auth/me'))
  }, [])

  const can = useCallback(
    (minimum: Role) => (user ? ROLE_RANK[user.role] >= ROLE_RANK[minimum] : false),
    [user],
  )

  const value = useMemo(
    () => ({ user, loading, signIn, signUp, signOut, can, refresh }),
    [user, loading, signIn, signUp, signOut, can, refresh],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used inside <AuthProvider>')
  return context
}
