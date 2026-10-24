/*
 * The project's do-file, as the Scripts page's editor.
 *
 * It used to be one command box per dataset, which is the wrong shape for what
 * people actually do: a survey export is several tables, and preparing it
 * means reading two of them, joining them and writing out a third. A box that
 * could only ever see one file had nowhere to put that.
 *
 * Save keeps a script without running it: one half-written at the end of the
 * day should survive being closed, and running it then would build half of
 * something. Run keeps it too, when it goes through. They used to be wholly
 * separate, and that was how scripts went missing from the nightly re-run -
 * run, seen to work, never saved. The script a clean run replaced is offered
 * back, so trying something over a good one costs nothing.
 *
 * It used to be a tab on the project's own page, and every script's place in
 * the running order was on another page entirely, so writing one, reordering
 * it and deleting it were three trips. It is drawn now as an editor's pane -
 * the box with its line numbers, a toolbar over it, a status bar under it and
 * the output and the reference beside it - for the Scripts page to set beside
 * the list of every script.
 */

import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { Loading, Spinner } from '@/components/ui'
import { ScriptHelp } from '@/components/ProjectScriptHelp'
import { api } from '@/lib/api'
import { relativeTime } from '@/lib/format'
import { useDialog } from '@/hooks/useDialog'
import { useToast } from '@/hooks/useToast'
import { insertLine } from '@/lib/script-insert'
import { caretAt, commandStarts, failedLine } from '@/lib/script-lines'

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
  /** The saved script the last clean run replaced, so it can be put back. */
  previous_text: string
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

/** Whether this project has a script to throw away.
 *
 *  A run counts, not only text. The Scripts page lists every project whose
 *  script has run, and a run from before the text of a run was recorded left
 *  its time, reads and writes and no text at all - so asking only about text
 *  hid Delete on exactly the scripts the page sent people here to deal with.
 */
export function hasScript(script: {
  text: string
  unsaved_run: string
  last_run_at: string | null
}): boolean {
  return !!script.text || !!script.unsaved_run || script.last_run_at !== null
}

/** A run is on record and nothing of its text is: neither saved nor kept
 *  from the run. The box is empty because there is nothing to put in it,
 *  which the editor has to say - an empty box on its own reads as a script
 *  that failed to load. */
export function textNotKept(script: {
  text: string
  unsaved_run: string
  last_run_at: string | null
}): boolean {
  return !script.text.trim() && !script.unsaved_run.trim() && script.last_run_at !== null
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
    /** The recorded run as the editor last knew it. */
    knownRun: string
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
  // Untouched, and the answer is the one the editor last settled on. Nothing
  // has happened, so there is nothing to show.
  //
  // Both halves of the answer, which took three goes to see. Comparing only
  // the saved text was standing in for this, and it is a poor stand-in,
  // because the saved text is empty in two quite different situations - a
  // project nobody has saved anything in, and a box somebody cleared and
  // saved on purpose - and in both of them the thing that moves is the run.
  // So a run by anybody was read as "nothing has happened": the box stayed as
  // it was and neither notice offered the new run, the amber one wanting the
  // run already in the box and the offer wanting a saved script.
  //
  // The deliberate clear, which is what that stand-in was protecting, is
  // covered by this as it stands: the answer still carries the run that was
  // on record when they saved, so it has not changed and the run is not
  // handed back. A new one is a new thing to say.
  if (answer.text === where.saved && answer.unsaved_run === where.knownRun) return null
  // Untouched, and the answer has moved. Follow what the project opens on
  // rather than the saved text alone: with nothing saved that is the recorded
  // run, and following only the saved text would blank a box that is showing
  // one.
  const fresh = openingText(answer)
  return fresh === where.shown ? null : fresh
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
  previous_text: '',
})

interface RunResult {
  /** Whether what ran is now the saved script. */
  kept: boolean
  log: { command: string; message: string }[]
  saved: { id: string; name: string; created: boolean; rows: number }[]
}

/** Line height of the box and of its line numbers, which have to agree to
 *  the pixel or the numbers drift away from their lines down a long script. */
const LINE_PX = 20

export function ProjectScript({
  projectId,
  projectName,
  canEdit,
  onDirtyChange,
}: {
  projectId: string
  /** Named in the editor's title bar. */
  projectName: string
  /** Whether this reader may change the script. Running it writes the
   *  project's datasets, so that takes the manager role over the project,
   *  while anybody who can see the project can read it. The server refuses
   *  the rest either way; this is so that nothing invites them to try. */
  canEdit: boolean
  /** Told whenever leaving would start or stop losing something, so the
   *  page can ask before moving to another script. */
  onDirtyChange?: (dirty: boolean) => void
}) {
  const queryClient = useQueryClient()
  const ask = useDialog()
  const toast = useToast()
  const [text, setText] = useState('')
  // What the editor held when it was last saved, so "unsaved changes" is a
  // comparison rather than a flag somebody has to remember to clear.
  const [saved, setSaved] = useState('')
  const [log, setLog] = useState<{ command: string; message: string; ok: boolean }[]>([])
  /** The side panel. Null until somebody picks: it then opens on the output
   *  of a script that has run and on the reference for one that has not. */
  const [panel, setPanel] = useState<'output' | 'reference' | null>(null)
  const [caret, setCaret] = useState({ line: 1, column: 1 })

  const box = useRef<HTMLTextAreaElement>(null)
  const gutter = useRef<HTMLDivElement>(null)

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
  /** The recorded run in the answer the editor last settled on, which is the
   *  other half of "has anything happened". It moves wherever `shown` moves,
   *  and `fillWith` reads both. */
  const knownRun = useRef('')

  useEffect(() => {
    if (script.data === undefined) return
    const fill = fillWith(script.data, {
      filled: filledFor.current,
      project: projectId,
      inBox: text,
      shown: shown.current,
      saved,
      knownRun: knownRun.current,
    })
    // The baselines describe the answer, not the box, so they settle on every
    // answer the editor is shown - including one that calls for no write.
    //
    // Returning null from `fillWith` means "leave the box", and this used to
    // be read as "nothing happened". Those are different. Open on a recovered
    // run, have somebody save exactly that run, and the answer moves from a
    // run with nothing saved to a saved script with no run - while the text
    // to show is the same either way, so there is nothing to write. The
    // saved text stayed empty against a server holding a script: Save read
    // "unsaved changes" for a box that matched it, and clearing the box
    // turned Save off entirely, on a project with a script still in it.
    setSaved(script.data.text)
    knownRun.current = script.data.unsaved_run
    if (fill === null) return
    filledFor.current = projectId
    shown.current = fill
    setText(fill)
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
      knownRun.current = result.unsaved_run
      setSaved(result.text)
      queryClient.setQueryData(['project-script', projectId], result)
      // The list beside the editor counts commands and says whether each
      // script is saved; a first save is what puts a new one in it.
      queryClient.invalidateQueries({ queryKey: ['scripts'] })
      queryClient.invalidateQueries({ queryKey: ['project-overview', projectId] })
    },
  })

  const run = useMutation({
    mutationFn: (next: string) =>
      api.post<RunResult>(`/projects/${projectId}/script/run`, { text: next }),
    onSuccess: (result, sent) => {
      // A clean run kept what ran. The marker moves to it exactly as a save
      // moves it - to the text that was sent, never by writing the box, which
      // may have been typed in while the run was out. See `keep`.
      if (result.kept) {
        shown.current = sent
        knownRun.current = ''
        setSaved(sent)
      }
      // Newest first, so a long script's last line is the one in view.
      setLog(
        result.log
          .map((step) => ({ command: step.command, message: step.message, ok: true }))
          .reverse(),
      )
      queryClient.invalidateQueries({ queryKey: ['project-script', projectId] })
      queryClient.invalidateQueries({ queryKey: ['datasets'] })
      // What it read and wrote decides its step in the list, so a run can
      // move it there.
      queryClient.invalidateQueries({ queryKey: ['scripts'] })
      queryClient.invalidateQueries({ queryKey: ['project-overview', projectId] })
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
      // And the list beside the editor marks it as failed.
      queryClient.invalidateQueries({ queryKey: ['scripts'] })
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
      // The list beside the editor holds this project because it has a
      // script; it does not any more.
      queryClient.invalidateQueries({ queryKey: ['scripts'] })
      queryClient.invalidateQueries({ queryKey: ['project-overview', projectId] })
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
        knownRun.current = before.unsaved_run
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

  const dirty = text !== saved
  // Whether leaving would lose anything, which is not the same as `dirty`. A
  // project with nothing saved opens on the run on record, so the box differs
  // from the saved text before anybody touches it - Save is right to offer
  // itself, and asking "leave without saving?" would be a false alarm: coming
  // back opens on that same run. What is lost is a change from what the
  // editor opens on.
  const wouldLose = script.data !== undefined && text !== openingText(script.data)

  // Above the early return too, being hooks. The page asks before moving to
  // another script with changes that would be lost, and is told there are
  // none when the editor goes.
  useEffect(() => {
    onDirtyChange?.(wouldLose)
    return () => onDirtyChange?.(false)
  }, [wouldLose, onDirtyChange])

  // And closing the tab, which the page cannot ask about, is left to the
  // browser's own question. It is the one leaving that throws a script away.
  useEffect(() => {
    if (!wouldLose) return
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault()
      event.returnValue = ''
    }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [wouldLose])

  if (script.isLoading) {
    return (
      <div className="grid flex-1 place-items-center p-8">
        <Loading />
      </div>
    )
  }

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

  // The line the last run stopped on, marked in the margin - only while the
  // box holds what ran. The complaint counts commands in that text, and in
  // any other text the same count lands somewhere it means nothing.
  const ran = script.data ? script.data.unsaved_run || script.data.text : ''
  const stopped =
    script.data?.last_error && text === ran ? failedLine(script.data.last_error, text) : null
  const lineCount = text.split('\n').length
  const commands = commandStarts(text).length
  const side = panel ?? (last || log.length ? 'output' : 'reference')

  const start = () => {
    setPanel('output')
    run.mutate(text)
  }

  /** Put the caret at the start of a line and bring it into view. */
  const goTo = (line: number) => {
    const area = box.current
    if (!area) return
    const offset = text.split('\n').slice(0, line - 1).join('\n').length + (line > 1 ? 1 : 0)
    area.focus()
    area.setSelectionRange(offset, offset)
    area.scrollTop = Math.max(0, (line - 1) * LINE_PX - area.clientHeight / 2)
    setCaret(caretAt(text, offset))
  }

  const notice = 'flex flex-wrap items-center gap-x-2 gap-y-1 border-b px-3 py-1.5 text-xs'
  const plain = `${notice} border-ink-200 bg-ink-50 text-ink-700 dark:border-dark-200 dark:bg-dark-100 dark:text-dark-700`
  const amber = `${notice} border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200`

  return (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col lg:flex-row">
      <section
        className="flex min-h-0 min-w-0 flex-1 flex-col"
        aria-label={`Script for ${projectName}`}
        onKeyDown={(event) => {
          if (!(event.metaKey || event.ctrlKey)) return
          // Ctrl/Cmd+Enter runs, because Enter has to be a new line in a
          // script box; Ctrl/Cmd+S saves, as in any editor, rather than
          // offering to save the page.
          if (event.key === 'Enter') {
            event.preventDefault()
            if (canEdit && text.trim() && !busy) start()
          } else if (event.key === 's' || event.key === 'S') {
            event.preventDefault()
            if (canEdit && dirty && !busy) keep.mutate(text)
          }
        }}
      >
        <div className="flex flex-wrap items-center gap-2 border-b border-ink-200 px-3 py-1.5 dark:border-dark-200">
          <div className="mr-auto flex min-w-0 items-center gap-2">
            <Link
              to={`/projects/${projectId}`}
              className="truncate text-[13px] font-semibold text-ink-800 hover:text-brand-700 dark:text-dark-800 dark:hover:text-brand-400"
              title="Open the project"
            >
              {projectName}
            </Link>
            {!canEdit ? (
              <span className="chip border-ink-200 bg-ink-100 text-ink-700 dark:border-dark-300 dark:bg-dark-200 dark:text-dark-700">
                Read only
              </span>
            ) : dirty ? (
              <span
                className="chip border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200"
                title="Running uses what is in the box, and keeps it if it runs cleanly."
              >
                Unsaved
              </span>
            ) : null}
          </div>
          {canEdit ? (
            <>
              <button
                className="btn-primary btn-sm"
                onClick={start}
                disabled={busy || !text.trim()}
                title="Run the script (Ctrl/⌘ + Enter)"
              >
                {run.isPending ? (
                  <Spinner className="h-3.5 w-3.5 text-white" />
                ) : (
                  <span aria-hidden>▶</span>
                )}
                Run
              </button>
              <button
                className="btn-secondary btn-sm"
                onClick={() => keep.mutate(text)}
                disabled={busy || !dirty}
                title="Keep it without running it (Ctrl/⌘ + S)"
              >
                {keep.isPending && <Spinner className="h-3.5 w-3.5" />}
                {dirty ? 'Save' : 'Saved'}
              </button>
              {/* Set apart from Run and Save, and quieter. It is the one
                  control here that cannot be undone by typing again. */}
              {script.data && hasScript(script.data) && (
                <button
                  className="btn-ghost btn-sm text-red-700 dark:text-red-300"
                  disabled={busy}
                  title="Delete this script"
                  onClick={async () => {
                    const sure = await ask.confirm({
                      title: 'Delete this script?',
                      message:
                        'The script goes, along with what its last run read and wrote. ' +
                        'The datasets it built stay exactly as they are - deleting the ' +
                        'recipe does not unmake what it cooked. It then drops out of ' +
                        'the list of scripts until something is written here again.',
                      confirmLabel: 'Delete script',
                      tone: 'danger',
                    })
                    if (!sure) return
                    // Emptying the box is part of what they asked for, so it
                    // happens with the request rather than when the answer
                    // gets back. The cached answer is emptied in the same
                    // breath: left holding the script, the empty, untouched
                    // box follows it straight back, and the clear is undone
                    // before the request has returned. Keeping what the answer
                    // said is what lets a delete that fails put it back. See
                    // `fillWith` and the mutation's `onError`.
                    //
                    // A read already on its way back is stopped first, or it
                    // lands after the emptying and puts the script back into
                    // the answer - the same bug through a second door.
                    await queryClient.cancelQueries({
                      queryKey: ['project-script', projectId],
                    })
                    const before = queryClient.getQueryData<Script>(['project-script', projectId])
                    setText('')
                    shown.current = ''
                    // The cached answer is about to say there is no run either.
                    knownRun.current = ''
                    setSaved('')
                    queryClient.setQueryData(['project-script', projectId], EMPTY_SCRIPT)
                    drop.mutate(before)
                  }}
                >
                  {drop.isPending && <Spinner className="h-3.5 w-3.5" />}
                  Delete
                </button>
              )}
            </>
          ) : (
            <span className="text-xs text-ink-500 dark:text-dark-500">
              Changing it takes the manager role on this project
            </span>
          )}
        </div>

        {alsoRan && (
          // The run is kept but is not the script, so it is offered rather
          // than opened on. Without this it was recorded and unreachable,
          // which is a worse answer than not recording it.
          <div className={plain}>
            <span>The last run here was not this script. It is kept, unsaved.</span>
            {canEdit && (
              <button
                className="font-medium text-brand-700 hover:underline dark:text-brand-400"
                onClick={() => setText(script.data?.unsaved_run ?? '')}
              >
                Put it in the box
              </button>
            )}
          </div>
        )}
        {script.data && textNotKept(script.data) && !text.trim() && (
          // The run is real - it read and wrote the datasets listed in the
          // output - but it ran before a run's text was recorded, so there is
          // nothing to open on. Said, so the empty box is not taken for a
          // fault, with the two ways out of it.
          <p className={amber}>
            This script has run, but the text of that run was not kept - it ran
            before scripts were recorded. Write it again and Save to keep it, or
            delete it to take it out of the list.
          </p>
        )}
        {!!script.data?.previous_text && text !== script.data.previous_text && (
          // A clean run replaced a saved script. The old one is kept one deep,
          // so trying something over a good script is a click from undone.
          <div className={plain}>
            <span>The last run replaced the script that was saved before it.</span>
            {canEdit && (
              <button
                className="font-medium text-brand-700 hover:underline dark:text-brand-400"
                onClick={() => setText(script.data?.previous_text ?? '')}
              >
                Put the previous one in the box
              </button>
            )}
          </div>
        )}
        {recovered && (
          // Said above the box rather than under it. Somebody who ran a
          // script without saving it comes back to what looks like their
          // script, and the one thing they need to know is that nothing has
          // kept it yet.
          <p className={amber}>
            This is the script that last ran here. It was never saved, so it is
            in the box rather than kept - Save keeps it.
          </p>
        )}

        <div className="flex min-h-[320px] flex-1 overflow-hidden">
          {/* The margin scrolls with the box rather than on its own, and
              carries a little more than the text so it can follow the box to
              the bottom past a horizontal scrollbar. */}
          <div
            ref={gutter}
            aria-hidden
            className="w-11 shrink-0 select-none overflow-hidden border-r border-ink-100 bg-ink-50 py-2 text-right font-mono text-[12px] text-ink-400 dark:border-dark-200 dark:bg-dark-100 dark:text-dark-500"
            style={{ lineHeight: `${LINE_PX}px` }}
          >
            {Array.from({ length: lineCount }, (_, index) => (
              <div
                key={index}
                className={`pr-2 ${
                  index + 1 === stopped
                    ? 'bg-red-100 font-semibold text-red-700 dark:bg-red-500/20 dark:text-red-300'
                    : index + 1 === caret.line
                      ? 'text-ink-800 dark:text-dark-800'
                      : ''
                }`}
              >
                {index + 1}
              </div>
            ))}
            <div className="h-8" />
          </div>
          <textarea
            ref={box}
            aria-label={`Script for ${projectName}`}
            className="min-w-0 flex-1 resize-none overflow-auto whitespace-pre border-0 bg-transparent px-3 py-2 font-mono text-[13px] text-ink-800 placeholder:text-ink-400 focus:outline-none focus:ring-0 dark:text-dark-800 dark:placeholder:text-dark-500"
            style={{ lineHeight: `${LINE_PX}px` }}
            value={text}
            readOnly={!canEdit}
            wrap="off"
            onChange={(event) => setText(event.target.value)}
            onScroll={(event) => {
              if (gutter.current) gutter.current.scrollTop = event.currentTarget.scrollTop
            }}
            onSelect={(event) =>
              setCaret(caretAt(event.currentTarget.value, event.currentTarget.selectionStart))
            }
            placeholder={
              canEdit
                ? '* Read two files, join them, write a third\n' +
                  'use people\n' +
                  'merge m:1 hhid using households, keep(match)\n' +
                  'gen adult = age >= 18\n' +
                  'collapse (sum) adult, by(province)\n' +
                  'save as "Adults by province"'
                : 'No script here yet.'
            }
            spellCheck={false}
          />
        </div>

        <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 border-t border-ink-200 bg-ink-50 px-3 py-1 text-[11px] text-ink-500 dark:border-dark-200 dark:bg-dark-100 dark:text-dark-600">
          <span className="tabular-nums">
            Ln {caret.line}, Col {caret.column}
          </span>
          <span>{commands === 1 ? '1 command' : `${commands} commands`}</span>
          <span>
            {!last
              ? 'Never run'
              : script.data?.last_error
                ? `Last run failed ${relativeTime(last)}`
                : `Last ran ${relativeTime(last)}`}
          </span>
          {stopped !== null && (
            <button
              className="font-medium text-red-700 hover:underline dark:text-red-300"
              onClick={() => goTo(stopped)}
            >
              Stopped at line {stopped}
            </button>
          )}
          {canEdit && (
            <span className="ml-auto hidden xl:inline">Ctrl+Enter runs · Ctrl+S saves</span>
          )}
        </div>
      </section>

      <aside className="flex min-h-[240px] min-w-0 flex-col border-t border-ink-200 dark:border-dark-200 lg:min-h-0 lg:w-[340px] lg:shrink-0 lg:border-l lg:border-t-0">
        <div role="tablist" aria-label="Beside the script" className="flex shrink-0 border-b border-ink-200 px-1 dark:border-dark-200">
          {(['output', 'reference'] as const).map((id) => (
            <button
              key={id}
              role="tab"
              aria-selected={side === id}
              onClick={() => setPanel(id)}
              className={`-mb-px border-b-2 px-3 py-2 text-xs font-medium transition-colors ${
                side === id
                  ? 'border-brand-600 text-brand-700 dark:text-brand-400'
                  : 'border-transparent text-ink-500 hover:text-ink-800 dark:text-dark-500 dark:hover:text-dark-800'
              }`}
            >
              {id === 'output' ? 'Output' : 'Reference'}
              {id === 'output' && !!script.data?.last_error && (
                <span aria-hidden className="ml-1.5 inline-block h-1.5 w-1.5 rounded-full bg-red-500 align-middle" />
              )}
            </button>
          ))}
        </div>
        <div role="tabpanel" className="min-h-0 flex-1 overflow-y-auto p-3">
          {side === 'reference' ? (
            <ScriptHelp onInsert={canEdit ? insert : undefined} />
          ) : (
            <div className="space-y-3 text-xs">
              {log.length > 0 && (
                <div>
                  <h3 className="mb-1 font-semibold text-ink-700 dark:text-dark-700">This run</h3>
                  <div className="rounded-control border border-ink-200 bg-ink-50 p-2 font-mono dark:border-dark-200 dark:bg-dark-100">
                    {log.map((entry, index) => (
                      <div key={index} className="mb-1.5 last:mb-0">
                        {entry.command && (
                          <div className="text-ink-700 dark:text-dark-700">. {entry.command}</div>
                        )}
                        <div
                          className={
                            entry.ok
                              ? 'text-green-700 dark:text-green-400'
                              : 'text-red-700 dark:text-red-300'
                          }
                        >
                          {entry.message}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              <div>
                <h3 className="mb-1 font-semibold text-ink-700 dark:text-dark-700">Last run</h3>
                {!last ? (
                  <p className="leading-relaxed text-ink-500 dark:text-dark-600">
                    Not run yet. Start with <code>use</code> to load one of the
                    project&apos;s datasets and finish with <code>save as</code> to
                    write what you built; nothing on disk changes until a save. A
                    script re-runs on a new export only once it has been run here,
                    so a draft is never started off inside somebody else&apos;s
                    import.
                  </p>
                ) : (
                  <div className="space-y-1.5">
                    <p className="text-ink-600 dark:text-dark-600">
                      {new Date(last).toLocaleString()}
                    </p>
                    {script.data?.last_error ? (
                      <p className="aero-pane aero-pane-warn px-3 py-2 pl-4 text-amber-900 dark:text-amber-200">
                        {script.data.last_error}
                      </p>
                    ) : null}
                    <Names label="Reads" names={script.data?.reads ?? []} />
                    <Names label="Writes" names={script.data?.writes ?? []} />
                    {(script.data?.reads.length ?? 0) > 0 && (
                      <p className="text-ink-500 dark:text-dark-600">
                        A newer export of anything under Reads runs this script
                        again, so what it writes keeps up with the data.
                      </p>
                    )}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </aside>
    </div>
  )
}

function Names({ label, names }: { label: string; names: string[] }) {
  if (!names.length) return null
  return (
    <p className="text-ink-600 dark:text-dark-600">
      <span className="font-semibold">{label}:</span> {names.join(', ')}
    </p>
  )
}
