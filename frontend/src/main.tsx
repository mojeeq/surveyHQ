import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import App from './App'
import { AuthProvider } from '@/hooks/useAuth'
import PreferenceBridge from '@/components/PreferenceBridge'
import { DialogProvider } from '@/hooks/useDialog'
import { ToastProvider } from '@/hooks/useToast'
import { ThemeProvider } from '@/hooks/useTheme'
import './fonts.css'
import './index.css'
import './redesign.css'
// After the flat stylesheet, because it puts the gloss back where that took
// it off. Does nothing unless the surface preference is aero.
import './aero.css'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
      staleTime: 30_000,
    },
  },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <ToastProvider>
            {/* Inside ToastProvider: answering a dialog often raises a toast,
                and a dialog has nothing to say that a toast should sit under. */}
            <DialogProvider>
              <AuthProvider>
                <PreferenceBridge />
                <App />
              </AuthProvider>
            </DialogProvider>
          </ToastProvider>
        </BrowserRouter>
      </QueryClientProvider>
    </ThemeProvider>
  </StrictMode>,
)
