/*
 * The project's do-file.
 *
 * It used to be one command box per dataset, which is the wrong shape for what
 * people actually do: a survey export is several tables, and preparing it
 * means reading two of them, joining them and writing out a third. A box that
 * could only ever see one file had nowhere to put that.
 *
 * Saving and running are separate on purpose. A script half-written at the end
 * of the day should survive being closed, and running it then would build half
 * of something.
 */

import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { Card, Loading, Spinner } from '@/components/ui'
import { api } from '@/lib/api'

interface Script {
  text: string
  reads: string[]
  writes: string[]
  last_run_at: string | null
  last_error: string
}

interface RunResult {
  log: { command: string; message: string }[]
  saved: { id: string; name: string; created: boolean; rows: number }[]
}

export function ProjectScript({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient()
  const [text, setText] = useState('')
  // What the editor held when it was last saved, so "unsaved changes" is a
  // comparison rather than a flag somebody has to remember to clear.
  const [saved, setSaved] = useState('')
  const [log, setLog] = useState<{ command: string; message: string; ok: boolean }[]>([])

  const script = useQuery({
    queryKey: ['project-script', projectId],
    queryFn: () => api.get<Script>(`/projects/${projectId}/script`),
  })

  useEffect(() => {
    if (script.data === undefined) return
    setText(script.data.text)
    setSaved(script.data.text)
  }, [script.data])

  const keep = useMutation({
    mutationFn: (next: string) =>
      api.put<Script>(`/projects/${projectId}/script`, { text: next }),
    onSuccess: (result) => {
      setSaved(result.text)
      queryClient.setQueryData(['project-script', projectId], result)
    },
  })

  const run = useMutation({
    mutationFn: (next: string) =>
      api.post<RunResult>(`/projects/${projectId}/script/run`, { text: next }),
    onSuccess: (result) => {
      // Newest first, so a long script's last line is the one in view.
      setLog(
        result.log
          .map((step) => ({ command: step.command, message: step.message, ok: true }))
          .reverse(),
      )
      queryClient.invalidateQueries({ queryKey: ['project-script', projectId] })
      queryClient.invalidateQueries({ queryKey: ['datasets'] })
    },
    onError: (error: Error) =>
      setLog([{ command: '', message: error.message, ok: false }]),
  })

  if (script.isLoading) return <Loading />

  const dirty = text !== saved
  const busy = run.isPending || keep.isPending
  const last = script.data?.last_run_at

  return (
    <div className="mt-4 grid gap-4 lg:grid-cols-[3fr_2fr]">
      <Card
        title="Script"
        subtitle="Read the project's datasets, put them together, write new ones"
      >
        <textarea
          className="input min-h-[280px] font-mono text-sm"
          value={text}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={(event) => {
            // Ctrl/Cmd+Enter runs, because Enter has to be a new line in a
            // script box. Same as the dataset command box always was.
            if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
              event.preventDefault()
              if (text.trim() && !busy) run.mutate(text)
            }
          }}
          placeholder={
            '* Read two files, join them, write a third\n' +
            'use people\n' +
            'merge m:1 hhid using households, keep(match)\n' +
            'gen adult = age >= 18\n' +
            'collapse (sum) adult, by(province)\n' +
            'save as "Adults by province"'
          }
          spellCheck={false}
          rows={14}
        />

        <div className="mt-2 flex flex-wrap items-center gap-3">
          <button
            className="btn-primary"
            onClick={() => run.mutate(text)}
            disabled={busy || !text.trim()}
          >
            {run.isPending && <Spinner className="h-4 w-4 text-white" />}
            Run script
          </button>
          <span className="text-xs text-ink-400">Ctrl/⌘ + Enter</span>
          <button
            className="btn-secondary"
            onClick={() => keep.mutate(text)}
            disabled={busy || !dirty}
          >
            {keep.isPending && <Spinner className="h-4 w-4" />}
            {dirty ? 'Save' : 'Saved'}
          </button>
          {dirty && (
            <span className="text-xs text-amber-700 dark:text-amber-300">
              Unsaved changes. Running uses what is in the box.
            </span>
          )}
        </div>

        <p className="mt-2 text-xs text-ink-500">
          Start with <code>use</code> to load one of the project's datasets, and
          finish with <code>save as</code> to write what you built. Nothing on
          disk changes until a save, so a script that stops halfway leaves the
          project as it was. Lines run top to bottom and stop at the first
          error.
        </p>
      </Card>

      <div className="space-y-4">
        <Card title="Last run">
          {!last ? (
            <p className="text-sm text-ink-500">
              This script has not been run yet. It will not re-run on a new
              export until it has been run once here, so a draft is never
              started off inside somebody else's import.
            </p>
          ) : (
            <div className="space-y-2 text-sm">
              <p className="text-ink-600 dark:text-dark-600">
                {new Date(last).toLocaleString()}
              </p>
              {script.data?.last_error ? (
                <p className="aero-pane aero-pane-warn px-3 py-2 pl-4 text-xs text-amber-900 dark:text-amber-200">
                  {script.data.last_error}
                </p>
              ) : null}
              <Names label="Reads" names={script.data?.reads ?? []} />
              <Names label="Writes" names={script.data?.writes ?? []} />
              {(script.data?.reads.length ?? 0) > 0 && (
                <p className="text-xs text-ink-500">
                  A newer export of anything under Reads runs this script again,
                  so what it writes keeps up with the data.
                </p>
              )}
            </div>
          )}
        </Card>

        {log.length > 0 && (
          <Card title="Log">
            <div className="max-h-96 overflow-auto rounded border border-ink-200 bg-ink-50 p-3 font-mono text-xs dark:border-dark-200 dark:bg-dark-100">
              {log.map((entry, index) => (
                <div key={index} className="mb-2">
                  {entry.command && (
                    <div className="text-ink-700 dark:text-dark-700">. {entry.command}</div>
                  )}
                  <div className={entry.ok ? 'text-green-700' : 'text-red-700'}>
                    {entry.message}
                  </div>
                </div>
              ))}
            </div>
          </Card>
        )}
      </div>
    </div>
  )
}

function Names({ label, names }: { label: string; names: string[] }) {
  if (!names.length) return null
  return (
    <p className="text-xs text-ink-600 dark:text-dark-600">
      <span className="font-semibold">{label}:</span> {names.join(', ')}
    </p>
  )
}
