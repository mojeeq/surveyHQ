import { createContext, useCallback, useContext, useState, type ReactNode } from 'react'

type ToastLevel = 'success' | 'error' | 'info'
interface Toast {
  id: number
  message: string
  level: ToastLevel
}

const ToastContext = createContext<{ push: (message: string, level?: ToastLevel) => void } | null>(
  null,
)

const TONES: Record<ToastLevel, string> = {
  success: 'border-emerald-200 bg-emerald-50 text-emerald-900',
  error: 'border-red-200 bg-red-50 text-red-900',
  info: 'border-brand-200 bg-brand-50 text-brand-900',
}
const ICONS: Record<ToastLevel, string> = { success: '✓', error: '⚠', info: 'ℹ' }

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])

  const push = useCallback((message: string, level: ToastLevel = 'info') => {
    const id = Date.now() + Math.random()
    setToasts((current) => [...current, { id, message, level }])
    setTimeout(() => setToasts((current) => current.filter((t) => t.id !== id)), 5000)
  }, [])

  return (
    <ToastContext.Provider value={{ push }}>
      {children}
      <div className="fixed bottom-4 right-4 z-[60] flex w-80 flex-col gap-2">
        {toasts.map((toast) => (
          <div
            key={toast.id}
            role="status"
            className={`flex items-start gap-2 rounded-lg border px-4 py-3 text-sm shadow-pop ${TONES[toast.level]}`}
          >
            <span aria-hidden>{ICONS[toast.level]}</span>
            <span className="flex-1">{toast.message}</span>
            <button
              onClick={() => setToasts((c) => c.filter((t) => t.id !== toast.id))}
              aria-label="Dismiss"
              className="opacity-60 hover:opacity-100"
            >
              ✕
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}

export function useToast() {
  const context = useContext(ToastContext)
  if (!context) throw new Error('useToast must be used inside <ToastProvider>')
  return context
}
