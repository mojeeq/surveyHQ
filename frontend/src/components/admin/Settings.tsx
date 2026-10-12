import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'

import { Card, ErrorNote, Loading } from '@/components/ui'
import { useToast } from '@/hooks/useToast'
import { api } from '@/lib/api'

/** One setting, as the server describes it. */
export interface PlatformSetting {
  name: string
  group: string
  label: string
  about: string
  warning: string
  kind: 'int' | 'bool' | 'text' | 'secret'
  unit: string
  minimum: number | null
  maximum: number | null
  /** A secret says whether it is set rather than what it is. */
  value: number | string | boolean
  default: number | string | boolean
  /** Whether what is in force came from here rather than from .env. */
  overridden: boolean
}

/** A setting's value as a form holds it, which is to say as text. */
export function asField(setting: PlatformSetting): string {
  if (setting.kind === 'bool') return setting.value ? 'true' : 'false'
  if (setting.kind === 'secret') return ''
  return String(setting.value ?? '')
}

/** What to send back: only what somebody actually changed. */
export function changesIn(
  settings: PlatformSetting[],
  edited: Record<string, string>,
): Record<string, string | boolean | number> {
  const changes: Record<string, string | boolean | number> = {}
  for (const setting of settings) {
    const typed = edited[setting.name]
    if (typed === undefined) continue
    // A secret never comes back from the server, so an empty box means "leave
    // the one that is there" rather than "clear it".
    if (setting.kind === 'secret') {
      if (typed) changes[setting.name] = typed
      continue
    }
    if (typed === asField(setting)) continue
    if (setting.kind === 'bool') changes[setting.name] = typed === 'true'
    else if (setting.kind === 'int') changes[setting.name] = Number(typed)
    else changes[setting.name] = typed
  }
  return changes
}

/** What a setting says underneath itself about where its value came from. */
export function provenance(setting: PlatformSetting): string {
  if (setting.kind === 'secret') return setting.value ? 'Set here' : 'Not set'
  const fallback =
    setting.kind === 'bool'
      ? setting.default
        ? 'on'
        : 'off'
      : `${setting.default}${setting.unit ? ` ${setting.unit}` : ''}`
  return setting.overridden ? `Set here. Without it: ${fallback}` : `From .env: ${fallback}`
}

export default function Settings() {
  const toast = useToast()
  const queryClient = useQueryClient()
  const [edited, setEdited] = useState<Record<string, string>>({})

  const listed = useQuery({
    queryKey: ['platform-settings'],
    queryFn: () => api.get<PlatformSetting[]>('/system/settings'),
  })

  // The form follows the server whenever the server has something new to say.
  useEffect(() => {
    if (listed.data) {
      setEdited(Object.fromEntries(listed.data.map((setting) => [setting.name, asField(setting)])))
    }
  }, [listed.data])

  const save = useMutation({
    mutationFn: (changes: Record<string, string | boolean | number>) =>
      api.put<PlatformSetting[]>('/system/settings', changes),
    onSuccess: (updated) => {
      queryClient.setQueryData(['platform-settings'], updated)
      queryClient.invalidateQueries({ queryKey: ['platform-info'] })
      toast.push('Saved. The rest of the platform picks this up within half a minute.', 'success')
    },
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  const reset = useMutation({
    mutationFn: (name: string) => api.delete<PlatformSetting[]>(`/system/settings/${name}`),
    onSuccess: (updated) => {
      queryClient.setQueryData(['platform-settings'], updated)
      toast.push('Back to what .env says.', 'success')
    },
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  if (listed.isLoading) return <Loading />
  if (listed.error) return <ErrorNote error={listed.error} />
  const settings = listed.data ?? []

  const changes = changesIn(settings, edited)
  const dirty = Object.keys(changes).length
  const groups = [...new Set(settings.map((setting) => setting.group))]

  return (
    <div className="space-y-4">
      <p className="text-sm text-ink-500 dark:text-dark-500">
        What can be changed while the platform is running. Everything else - the secret key,
        the database, the addresses this answers on - stays in <code>.env</code>, where a web
        page cannot reach it. A change here reaches every part of the platform within half a
        minute, and goes into the audit log with your name on it.
      </p>

      {groups.map((group) => (
        <Card key={group} title={group}>
          <div className="divide-y divide-ink-100 dark:divide-dark-200">
            {settings
              .filter((setting) => setting.group === group)
              .map((setting) => (
                <div key={setting.name} className="flex flex-wrap gap-3 py-3 first:pt-0">
                  <div className="min-w-0 flex-1">
                    <label
                      className="text-sm font-medium text-ink-800 dark:text-dark-800"
                      htmlFor={`setting-${setting.name}`}
                    >
                      {setting.label}
                    </label>
                    <p className="mt-0.5 text-xs text-ink-500 dark:text-dark-500">
                      {setting.about}
                    </p>
                    {setting.warning && (
                      <p className="mt-1 text-xs text-amber-700 dark:text-amber-500">
                        {setting.warning}
                      </p>
                    )}
                    <p className="mt-1 text-xs text-ink-400 dark:text-dark-500">
                      {provenance(setting)}
                      {setting.overridden && (
                        <button
                          type="button"
                          className="ml-2 underline hover:text-ink-600 dark:hover:text-dark-700"
                          onClick={() => reset.mutate(setting.name)}
                          disabled={reset.isPending}
                        >
                          put it back
                        </button>
                      )}
                    </p>
                  </div>
                  <div className="flex w-56 shrink-0 items-start gap-2">
                    {setting.kind === 'bool' ? (
                      <select
                        id={`setting-${setting.name}`}
                        className="input py-1 text-sm"
                        value={edited[setting.name] ?? 'false'}
                        onChange={(event) =>
                          setEdited((was) => ({ ...was, [setting.name]: event.target.value }))
                        }
                      >
                        <option value="true">On</option>
                        <option value="false">Off</option>
                      </select>
                    ) : (
                      <input
                        id={`setting-${setting.name}`}
                        className="input py-1 text-sm"
                        type={
                          setting.kind === 'secret'
                            ? 'password'
                            : setting.kind === 'int'
                              ? 'number'
                              : 'text'
                        }
                        inputMode={setting.kind === 'int' ? 'numeric' : undefined}
                        min={setting.minimum ?? undefined}
                        max={setting.maximum ?? undefined}
                        placeholder={
                          setting.kind === 'secret'
                            ? setting.value
                              ? 'Set. Type to replace it'
                              : 'Not set'
                            : undefined
                        }
                        autoComplete={setting.kind === 'secret' ? 'new-password' : 'off'}
                        value={edited[setting.name] ?? ''}
                        onChange={(event) =>
                          setEdited((was) => ({ ...was, [setting.name]: event.target.value }))
                        }
                      />
                    )}
                    {setting.unit && (
                      <span className="pt-1.5 text-xs text-ink-500 dark:text-dark-500">
                        {setting.unit}
                      </span>
                    )}
                  </div>
                </div>
              ))}
          </div>
        </Card>
      ))}

      <div className="sticky bottom-0 flex items-center gap-3 border-t border-ink-200 bg-white/95 py-3 dark:border-dark-300 dark:bg-dark-50/95">
        <button
          className="btn-primary"
          disabled={!dirty || save.isPending}
          onClick={() => save.mutate(changes)}
        >
          {save.isPending
            ? 'Saving'
            : dirty
              ? `Save ${dirty} change${dirty > 1 ? 's' : ''}`
              : 'Saved'}
        </button>
        {Boolean(dirty) && (
          <button
            className="btn-secondary"
            onClick={() =>
              setEdited(
                Object.fromEntries(settings.map((setting) => [setting.name, asField(setting)])),
              )
            }
          >
            Undo
          </button>
        )}
      </div>
    </div>
  )
}
