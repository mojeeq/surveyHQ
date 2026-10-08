import { useEffect } from 'react'

import { useAuth } from '@/hooks/useAuth'
import { useTheme } from '@/hooks/useTheme'

/**
 * Hands the account's saved preferences to the shell when sign-in resolves.
 *
 * It exists because of where the providers sit. ThemeProvider wraps
 * AuthProvider, so that the login page is themed before anybody is signed in,
 * which means the theme cannot read the user. Rather than reorder them, or
 * teach the auth layer about appearance, this sits inside both and carries
 * the value across. It renders nothing.
 *
 * Keyed on the user's id, not the whole object: /auth/me is refetched after a
 * password change and on a save, and reapplying on every one of those would
 * overwrite a choice made a moment ago with the copy the request set out with.
 */
export default function PreferenceBridge() {
  const { user } = useAuth()
  const { adoptSidebarPinned } = useTheme()
  const id = user?.id

  useEffect(() => {
    if (!id) return
    adoptSidebarPinned(user?.preferences?.sidebar_pinned ?? null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id])

  return null
}
