import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'

export type Theme = 'light' | 'dark' | 'system'

/** How the furniture is drawn, which is a separate question from light or dark.
 *
 *  Aero is the glossy treatment the shell was built with: a lit sidebar, a
 *  glass header, navigation tiles with a highlight over the top half. The
 *  redesign flattened it, and both are wanted - so it is a choice rather than
 *  a commit. It works in either theme, which is why it is not a third value
 *  of Theme.
 */
export type Surface = 'flat' | 'aero'

const STORAGE_KEY = 'theme'
const SURFACE_KEY = 'surface'

function getSystemTheme(): 'light' | 'dark' {
  if (typeof window === 'undefined' || !window.matchMedia) return 'light'
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

function getStoredTheme(): Theme {
  if (typeof window === 'undefined') return 'system'
  const stored = window.localStorage.getItem(STORAGE_KEY)
  return stored === 'light' || stored === 'dark' || stored === 'system' ? stored : 'system'
}

function getStoredSurface(): Surface {
  if (typeof window === 'undefined') return 'flat'
  return window.localStorage.getItem(SURFACE_KEY) === 'aero' ? 'aero' : 'flat'
}

function applyTheme(resolved: 'light' | 'dark') {
  document.documentElement.classList.toggle('dark', resolved === 'dark')
}

function applySurface(surface: Surface) {
  // On the root element so stylesheets can reach it, even though today only
  // the shell reads it through the hook.
  document.documentElement.dataset.surface = surface
}

type ThemeContextValue = {
  /** The user's preference: 'light', 'dark', or 'system'. */
  theme: Theme
  /** The theme actually applied to the page, with 'system' resolved. */
  resolvedTheme: 'light' | 'dark'
  setTheme: (theme: Theme) => void
  toggleTheme: () => void
  /** 'flat' or 'aero'. Independent of light and dark. */
  surface: Surface
  setSurface: (surface: Surface) => void
  toggleSurface: () => void
}

const ThemeContext = createContext<ThemeContextValue | null>(null)

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(() => getStoredTheme())
  const [surface, setSurfaceState] = useState<Surface>(() => getStoredSurface())
  const [resolvedTheme, setResolvedTheme] = useState<'light' | 'dark'>(() =>
    theme === 'system' ? getSystemTheme() : theme,
  )

  useEffect(() => {
    const resolved = theme === 'system' ? getSystemTheme() : theme
    setResolvedTheme(resolved)
    applyTheme(resolved)
  }, [theme])

  // Follow the OS preference live, but only while the user hasn't picked an
  // explicit theme of their own.
  useEffect(() => {
    if (theme !== 'system' || typeof window === 'undefined' || !window.matchMedia) return
    const media = window.matchMedia('(prefers-color-scheme: dark)')
    const onChange = () => {
      const resolved = getSystemTheme()
      setResolvedTheme(resolved)
      applyTheme(resolved)
    }
    media.addEventListener('change', onChange)
    return () => media.removeEventListener('change', onChange)
  }, [theme])

  useEffect(() => {
    applySurface(surface)
  }, [surface])

  const setSurface = (next: Surface) => {
    setSurfaceState(next)
    if (typeof window !== 'undefined') {
      window.localStorage.setItem(SURFACE_KEY, next)
    }
  }

  const toggleSurface = () => setSurface(surface === 'aero' ? 'flat' : 'aero')

  const setTheme = (next: Theme) => {
    setThemeState(next)
    if (typeof window !== 'undefined') {
      window.localStorage.setItem(STORAGE_KEY, next)
    }
  }

  const toggleTheme = () => {
    setTheme(resolvedTheme === 'dark' ? 'light' : 'dark')
  }

  const value = useMemo(
    () => ({ theme, resolvedTheme, setTheme, toggleTheme, surface, setSurface, toggleSurface }),
    [theme, resolvedTheme, surface],
  )

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}

export function useTheme() {
  const context = useContext(ThemeContext)
  if (!context) throw new Error('useTheme must be used within a ThemeProvider')
  return context
}
