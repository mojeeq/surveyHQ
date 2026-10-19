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

import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { Card, Loading, Spinner } from '@/components/ui'
import { ScriptHelp } from '@/components/ProjectScriptHelp'
import { api } from '@/lib/api'
import { useDialog } from '@/hooks/useDialog'
import { useToast } from '@/hooks/useToast'
import { insertLine } from '@/lib/script-insert'

interface Script {
  text: string
  /** What the last run ran, when that is not what is saved. Running and
   *  saving are separate on purpose, so a script can be tried without being
   *  kept - and the editor used to open blank afterwards. */
  unsaved_run: string
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
  const ask = useDialog()
  const toast = useToast()
  const [text, setText] = useState('')
  // What the editor held when it was last saved, so "unsaved changes" is a
  // comparison rather than a flag somebody has to remember to clear.
  const [saved, setSaved] = useState('')
  const [log, setLog] = useState<{ command: string; message: string; ok: boolean }[]>([])

  const box = useRef<HTMLTextAreaElement>(null)

  /** Put an example where the cursor is, then carry on from the end of it. */
  const insert = (line: string) => {
    const area = box.current
    const { text: next, caret } = insertLine(text, area ? area.selectionStart : text.length, line)
    setText(next)
    requestAnimationFrame(() => {
      area?.focus()
      area?.setSelectionRange(caret, caret)
    })
  }

  const script = useQuery({
    queryKey: ['project-script', projectId],
    queryFn: () => api.get<Script>(`/projects/${projectId}/script`),
  })

  useEffect(() => {
    if (script.data === undefined) return
    // The saved script when there is one. Nothing saved but something ran:
    // open on what ran, since the alternative is a blank box on a project
    // whose data was plainly built by something.
    //
    // Where both exist they are different things - one somebody kept, one
    // somebody tried - and the box opens on the kept one. The other is a
    // click away rather than lost, which is the whole point of recording it:
    // opening on it would let an experiment quietly replace the script.
    const opening = script.data.text.trim() ? script.data.text : script.data.unsaved_run
    setText(opening)
    // Still measured against what is saved, so an unsaved run opens dirty and
    // the Save button is live: it is a draft recovered, not a saved script.
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
    onError: (error: Error) => {
      setLog([{ command: '', message: error.message, ok: false }])
      // A run that failed still changed something here: the complaint, and
      // the text that was tried. Left alone, the cached answer from before
      // the run stays fresh for half a minute, so leaving this tab and
      // coming back inside that window resets the box to what was saved and
      // loses the draft the server had just kept.
      queryClient.invalidateQueries({ queryKey: ['project-script', projectId] })
      // A script that stopped partway saved what it got to, which is the
      // whole reason the run is not unwound.
      queryClient.invalidateQueries({ queryKey: ['datasets'] })
    },
  })

  const drop = useMutation({
    mutationFn: () => api.delete<{ detail: string }>(`/projects/${projectId}/script`),
    onSuccess: (result) => {
      setText('')
      setSaved('')
      setLog([])
      queryClient.invalidateQueries({ queryKey: ['project-script', projectId] })
      // The overview lists this project because it has a script; it does not
      // any more.
      queryClient.invalidateQueries({ queryKey: ['scripts'] })
      toast.push(result.detail, 'success')
    },
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  if (script.isLoading) return <Loading />

  const dirty = text !== saved
  const busy = run.isPending || keep.isPending
  const last = script.data?.last_run_at
  // Nothing saved, and the box holds what ran. Checked against the box rather
  // than against the answer alone, so the note goes the moment it is typed
  // over or saved rather than lingering over somebody else's work.
  const recovered =
    !script.data?.text.trim() &&
    !!script.data?.unsaved_run &&
    text === script.data.unsaved_run
  // A saved script and a different run behind it. Not shown while the box
  // already holds that run - then it has been restored and the notice above
  // is the one that applies.
  const alsoRan =
    !!script.data?.text.trim() &&
    !!script.data?.unsaved_run &&
    text !== script.data.unsaved_run

  return (
    <div className="mt-4 grid gap-4 lg:grid-cols-[3fr_2fr]">
      <Card
        title="Script"
        subtitle="Read the project's datasets, put them together, write new ones"
      >
        {alsoRan && (
          // The run is kept but is not the script, so it is offered rather
          // than opened on. Without this it was recorded and unreachable,
          // which is a worse answer than not recording it.
          <div className="mb-2 flex flex-wrap items-center gap-2 rounded-control bg-ink-50 px-2.5 py-1.5 text-xs text-ink-700 dark:bg-dark-100 dark:text-dark-700">
            <span>
              The last run here was not this script. It is kept, unsaved.
            </span>
            <button
              className="btn-ghost btn-sm"
              onClick={() => setText(script.data?.unsaved_run ?? '')}
            >
              Put it in the box
            </button>
          </div>
        )}
        {recovered && (
          // Said before the box rather than after it. Somebody who ran a
          // script without saving it comes back to what looks like their
          // script, and the one thing they need to know is that nothing has
          // kept it yet.
          <p className="mb-2 rounded-control bg-amber-50 px-2.5 py-1.5 text-xs text-amber-800 dark:bg-amber-500/10 dark:text-amber-200">
            This is the script that last ran here. It was never saved, so it is
            in the box rather than kept - Save keeps it.
          </p>
        )}
        <textarea
          ref={box}
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
          {/* Pushed to the far end, away from Run and Save. It is the one
              control here that cannot be undone by typing again. */}
          {(script.data?.text || script.data?.unsaved_run) && (
            <button
              className="btn-ghost btn-sm ml-auto text-red-700 dark:text-red-300"
              disabled={busy || drop.isPending}
              onClick={async () => {
                const sure = await ask.confirm({
                  title: 'Delete this script?',
                  message:
                    'The script goes, along with what its last run read and wrote. ' +
                    'The datasets it built stay exactly as they are - deleting the ' +
                    'recipe does not unmake what it cooked. This project then drops ' +
                    'off the Scripts page until something is written here again.',
                  confirmLabel: 'Delete script',
                  tone: 'danger',
                })
                if (sure) drop.mutate()
              }}
            >
              {drop.isPending && <Spinner className="h-4 w-4" />}
              Delete script
            </button>
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
        <ScriptHelp onInsert={insert} />
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
