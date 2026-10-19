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

/** What the editor opens on for a project.
 *
 *  The saved script when there is one. Nothing saved but something ran: what
 *  ran, since the alternative is a blank box on a project whose data was
 *  plainly built by something.
 *
 *  Where both exist they are different things - one somebody kept, one
 *  somebody tried - and the box opens on the kept one, with the other a click
 *  away. Opening on the run instead would let an experiment quietly take the
 *  place of the script, and Run would then run the experiment.
 *
 *  Out here, and tested, because this choice has been wrong twice: once
 *  preferring the saved text so hard that a recorded run was unreachable, and
 *  once treating a box of spaces as a script.
 */
export function openingText(script: { text: string; unsaved_run: string }): string {
  return script.text.trim() ? script.text : script.unsaved_run
}

/** What the box should hold when an answer arrives, or null to leave it be.
 *
 *  Two things have to hold at once, and holding only one of them is a bug
 *  each way round. A box that tracks the query throws away the draft
 *  somebody is in the middle of correcting - which a failed run does, since
 *  it refetches to show the newer complaint. A box filled once and then
 *  never again hides a script a colleague saved while the tab was shut, and
 *  Save afterwards writes over their work without either of them seeing it.
 *
 *  So the box belongs to the person from the moment they change it, and until
 *  then it is only a view of what is saved and follows a newer one.
 *
 *  "From the moment they change it" has to be measured against what was last
 *  put in the box, not against what is saved. A project with nothing saved
 *  and a run on record opens on the run, so the box differs from the saved
 *  text immediately, with nobody having touched anything - and reading that
 *  as an edit left the box ignoring every later answer, which is the bug this
 *  is the second attempt at.
 */
export function fillWith(
  answer: { text: string; unsaved_run: string },
  where: {
    filled: string | null
    project: string
    inBox: string
    /** What the editor last put in the box itself. */
    shown: string
    /** The saved text as the editor last knew it. */
    saved: string
  },
): string | null {
  // Opening on a project. Falling back to the last run matters here: a blank
  // box on a project whose data was plainly built by something is the
  // complaint this started from.
  //
  // Judged by the project rather than by the box, because an untouched box
  // would otherwise be measured against the previous project's saved text,
  // and a draft left in one project would turn up in the next one's editor.
  if (where.filled !== where.project) return openingText(answer)
  // Theirs: what is in the box is not what the editor put there.
  if (where.inBox !== where.shown) return null
  // Untouched, and nothing has been saved since the box was filled. Leave it
  // be rather than writing the saved text over it: on a project with nothing
  // saved and a run on record that would empty the box every refetch, and
  // after somebody cleared the box and saved it, falling back to the run
  // would hand them back the thing they had just finished replacing.
  if (answer.text === where.saved) return null
  // Untouched, and somebody has saved since. Follow it - plainly, so that
  // Save afterwards cannot quietly overwrite their work.
  return answer.text
}

/** A project with no script, as the server describes one: `script_for`
 *  makes an empty one rather than answering 404. */
const EMPTY_SCRIPT: Script = Object.freeze({
  text: '',
  unsaved_run: '',
  reads: [],
  writes: [],
  last_run_at: null,
  last_error: '',
})

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

  /** The project the box was last filled for. See `fillWith`.
   *
   *  Anything that refetches while somebody is typing - a failed run asking
   *  for the newer error, a window regaining focus - used to refill the box
   *  from the answer, throwing away the draft they were correcting. Reads,
   *  writes and the last error come from the query and are redrawn freely;
   *  the text is only replaced while nobody has changed it.
   */
  const filledFor = useRef<string | null>(null)
  /** What is in the box, readable from a callback that runs long after the
   *  render it was started from. Assigned here rather than in an effect so it
   *  cannot lag behind by a tick, and never read while rendering. */
  const live = useRef('')
  /** What the editor last put in the box, which is how a change made by the
   *  person is told apart from a box the editor filled. Not state: nothing is
   *  drawn from it, and it must be read inside the effect that sets it. */
  const shown = useRef('')

  useEffect(() => {
    if (script.data === undefined) return
    const fill = fillWith(script.data, {
      filled: filledFor.current,
      project: projectId,
      inBox: text,
      shown: shown.current,
      saved,
    })
    if (fill === null) return
    filledFor.current = projectId
    shown.current = fill
    setText(fill)
    // Always measured against what is saved, so a recovered run opens dirty
    // and the Save button is live: it is a draft got back, not a saved
    // script.
    setSaved(script.data.text)
    // `text` and `saved` are read above, so they belong here. The effect runs
    // again when they change and stops at `fillWith`, which is the point:
    // the first keystroke is what hands the box over.
  }, [script.data, projectId, text, saved])

  const keep = useMutation({
    mutationFn: (next: string) =>
      api.put<Script>(`/projects/${projectId}/script`, { text: next }),
    onSuccess: (result, sent) => {
      // Saving does not write the box. The box stays editable while the PUT
      // is in flight, so anything written back here lands on top of whatever
      // was typed in the meantime and those keystrokes are gone.
      //
      // What moves is the marker, to the text that was sent. If the box still
      // holds it, nobody typed during the save and it may follow a newer
      // answer; if they did, the box differs from the marker and is theirs,
      // which is exactly right. `sent` rather than `result.text` for the same
      // reason: the marker records what was in the box, and a server that
      // tidies what it stores has not changed that.
      shown.current = sent
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
    // What the answer said before the delete, so a delete that fails can put
    // it back.
    mutationFn: (_before: Script | undefined) =>
      api.delete<{ detail: string }>(`/projects/${projectId}/script`),
    onSuccess: (result) => {
      // The box was emptied when they asked, and so was the cached answer.
      // Nothing here touches either: by the time this arrives they may have
      // started typing the script that replaces the one they got rid of,
      // which is the obvious next thing to do, and erasing that is the loss
      // this whole arrangement is against.
      setLog([])
      queryClient.invalidateQueries({ queryKey: ['project-script', projectId] })
      // The overview lists this project because it has a script; it does not
      // any more.
      queryClient.invalidateQueries({ queryKey: ['scripts'] })
      toast.push(result.detail, 'success')
    },
    onError: (error: Error, before) => {
      if (before) {
        // Put the answer back, and let the ordinary rule do the rest: the box
        // is empty and nobody has touched it, so it follows the script back.
        // If they did start typing, the box is theirs and keeps what they
        // wrote. Either way nothing here writes the box.
        queryClient.setQueryData(['project-script', projectId], before)
        // And the saved text with it. `saved` means what the server holds,
        // and the server still holds this one. Left empty it is a lie that
        // reads two ways: `dirty` measures a draft against nothing, and
        // `fillWith` sees a script that has been there all along as newly
        // saved. Setting it here does not disturb a draft, because the box
        // is not read.
        setSaved(before.text)
        // Nothing happened, so the editor should show what this project
        // opens on - which is not always the saved text. With nothing saved
        // and a run on record it is the run, and following cannot reach
        // that: `fillWith` compares the saved text and would leave the box
        // empty with no notice and no offer, the run invisible until a
        // reload. Marking the project unfilled sends the next pass down the
        // opening branch, which is exactly "what this project opens on".
        //
        // Only when nobody has typed. The opening branch does not ask, so on
        // a box somebody has started a replacement in it would overwrite
        // them, and that is the loss all of this is against.
        if (live.current === shown.current) filledFor.current = null
        // And then go and find out. Cancelling the read that was on its way
        // back rolls the query to where it was before that read, so what was
        // snapshotted above is the answer from before it - and putting that
        // back is putting back something known to be behind. A script a
        // colleague saved, a newer run, a newer complaint: all of it would
        // stay hidden until something else happened to ask.
        //
        // Restoring first and asking second is the point of a rollback: the
        // editor shows what it had rather than nothing, and the truth
        // arrives a moment later through the ordinary rule.
        queryClient.invalidateQueries({ queryKey: ['project-script', projectId] })
      }
      toast.push(error.message, 'error')
    },
  })

  // Above the early return, so a render that bails out early cannot leave
  // this behind holding something the box no longer contains.
  live.current = text

  if (script.isLoading) return <Loading />

  const dirty = text !== saved
  // Every request that changes the script, so nothing that would make another
  // one can be pressed while one is out.
  //
  // The delete was missing here, and only the Delete button made up for it at
  // its own call site - which is the shape of the bug: one caller patched
  // instead of the definition. Save stayed live through a delete, so typing a
  // replacement and saving it sent a PUT that raced the DELETE. Where the PUT
  // landed first, the DELETE then removed the script that had just been
  // saved, and the refetch emptied the box - after Save had said it worked.
  //
  // This is about the buttons, not the box. Typing stays free the whole time;
  // what waits is firing a second request on top of the first.
  const busy = run.isPending || keep.isPending || drop.isPending
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
              disabled={busy}
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
                if (!sure) return
                // Emptying the box is part of what they asked for, so it
                // happens with the request rather than when the answer gets
                // back.
                //
                // The cached answer has to be emptied in the same breath. Left
                // holding the script it no longer matches the saved text, so
                // the box - empty and untouched - follows it straight back,
                // and the clear is undone before the request has even
                // returned. On a slow delete the box then shows the script
                // that is being deleted, and anything typed into it is typed
                // onto the end of that.
                //
                // Keeping what the answer said is what lets a delete that
                // fails put it back. See `fillWith` and the mutation's
                // `onError`.
                // A read already on its way back has to be stopped first. One
                // started by a window regaining focus, or by the last run,
                // lands after the line below and puts the pre-delete script
                // back into the answer - and then the empty, untouched box
                // follows it, which is the same bug through a second door.
                await queryClient.cancelQueries({
                  queryKey: ['project-script', projectId],
                })
                const before = queryClient.getQueryData<Script>(['project-script', projectId])
                setText('')
                shown.current = ''
                setSaved('')
                queryClient.setQueryData(['project-script', projectId], EMPTY_SCRIPT)
                drop.mutate(before)
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
