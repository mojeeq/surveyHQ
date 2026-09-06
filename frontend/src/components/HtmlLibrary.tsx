import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { useToast } from '@/hooks/useToast'

export interface HtmlSnippet {
  id: string
  name: string
  description?: string
  html: string
  project_id: string | null
}

/**
 * Load an embed from the library, or put this one into it.
 *
 * The same embed - a map, a video, an office banner - belongs on several
 * dashboards, often across surveys, and pasting the markup into each widget
 * let the copies drift: a corrected link was fixed in one place and left wrong
 * in four. Loading takes a copy rather than a reference, deliberately. A
 * widget that changed under its dashboard because somebody edited a shared
 * snippet would be a worse surprise than an out-of-date one, so the library is
 * a place to keep markup, not a live include.
 */
export default function HtmlLibrary({
  html,
  projectId,
  onLoad,
}: {
  /** The markup in the editor now, which is what "Save to library" saves. */
  html: string
  /** The dashboard's project, so a saved snippet lands somewhere sensible. */
  projectId: string | null
  onLoad: (html: string) => void
}) {
  const toast = useToast()
  const queryClient = useQueryClient()
  const [saving, setSaving] = useState(false)
  const [name, setName] = useState('')
  const [shared, setShared] = useState(true)

  const snippets = useQuery({
    queryKey: ['html-snippets', projectId],
    queryFn: () =>
      api.get<HtmlSnippet[]>(
        `/dashboards/html-snippets${projectId ? `?project_id=${projectId}` : ''}`,
      ),
  })

  const save = useMutation({
    mutationFn: () =>
      api.post('/dashboards/html-snippets', {
        name,
        html,
        // Shared by default: an embed worth keeping is usually worth reusing,
        // and that is the whole reason for the library.
        project_id: shared ? null : projectId,
      }),
    onSuccess: () => {
      toast.push(`"${name}" saved to the library`, 'success')
      queryClient.invalidateQueries({ queryKey: ['html-snippets'] })
      setSaving(false)
      setName('')
    },
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  return (
    <div className="mb-2 flex flex-wrap items-center gap-2">
      <select
        className="input h-8 w-56 py-0 text-xs"
        aria-label="Load an embed from the library"
        value=""
        onChange={(event) => {
          const chosen = snippets.data?.find((s) => s.id === event.target.value)
          if (chosen) onLoad(chosen.html)
        }}
      >
        <option value="">
          {snippets.data?.length ? 'Load from library…' : 'Library is empty'}
        </option>
        {(snippets.data ?? []).map((snippet) => (
          <option key={snippet.id} value={snippet.id}>
            {snippet.name}
            {snippet.project_id ? '' : ' (shared)'}
          </option>
        ))}
      </select>

      {saving ? (
        <>
          <input
            className="input h-8 w-44 py-0 text-xs"
            placeholder="Name it"
            aria-label="Name for the saved embed"
            autoFocus
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
          {projectId && (
            <label className="flex items-center gap-1.5 text-xs text-ink-600">
              <input
                type="checkbox"
                checked={shared}
                onChange={(event) => setShared(event.target.checked)}
              />
              Available to every project
            </label>
          )}
          <button
            className="btn-primary btn-sm"
            disabled={!name.trim() || !html.trim() || save.isPending}
            onClick={() => save.mutate()}
          >
            Save
          </button>
          <button className="btn-ghost btn-sm" onClick={() => setSaving(false)}>
            Cancel
          </button>
        </>
      ) : (
        <button
          className="btn-secondary btn-sm"
          disabled={!html.trim()}
          title={html.trim() ? undefined : 'Write some HTML first'}
          onClick={() => setSaving(true)}
        >
          Save to library
        </button>
      )}
    </div>
  )
}
