/*
 * One of a project's do-files, as the Scripts page's editor.
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
 * the list of every script. The box itself is ScriptEditor, which colours
 * the script and offers what can come next.
 *
 * A project had one script, and this was its editor. It is one script's now,
 * by the script's own id: a project keeps the roster cleaning, the household
 * file and the tables in scripts of their own, each named, run, renamed and
 * deleted on its own.
 */

import { useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { Loading, Spinner } from '@/components/ui'
import { ScriptHelp } from '@/components/ProjectScriptHelp'
import { ScriptEditor } from '@/components/ScriptEditor'
import type { ScriptEditorHandle } from '@/components/ScriptEditor'
import { api } from '@/lib/api'
import { relativeTime } from '@/lib/format'
import { useAuth } from '@/hooks/useAuth'
import { useDialog } from '@/hooks/useDialog'
import { useToast } from '@/hooks/useToast'
import {
  clearDraft,
  draftFrom,
  readDraft,
  recallLog,
  rememberLog,
  writeDraft,
} from '@/lib/script-drafts'
import type { Draft, LogLine } from '@/lib/script-drafts'
import { EMPTY_VOCABULARY, indexLanguage } from '@/lib/script-language'
import type { ScriptNames, Vocabulary } from '@/lib/script-language'
import { commandStarts, failedLine } from '@/lib/script-lines'

interface Script {
  id: string
  /** What it is called in its project, and on the Scripts page. */
  name: string
  project_id: string
  project_name: string
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
    /** The script the box was last filled for, and the one open now. */
    filled: string | null
    script: string
    inBox: string
    /** What the editor last put in the box itself. */
    shown: string
    /** The saved text as the editor last knew it. */
    saved: string
    /** The recorded run as the editor last knew it. */
    knownRun: string
  },
): string | null {
  // Opening on a script. Falling back to the last run matters here: a blank
  // box on a script whose data was plainly built by something is the
  // complaint this started from.
  //
  // Judged by the script rather than by the box, because an untouched box
  // would otherwise be measured against the previous script's saved text,
  // and a draft left in one script would turn up in the next one's editor.
  if (where.filled !== where.script) return openingText(answer)
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

interface RunResult {
  /** Whether what ran is now the saved script. */
  kept: boolean
  log: { command: string; message: string }[]
  saved: { id: string; name: string; created: boolean; rows: number }[]
}

export function ProjectScript({
  scriptId,
  projectId,
  projectName,
  canEdit,
  onDeleted,
}: {
  scriptId: string
  /** The project it belongs to, whose datasets it reads and writes - and
   *  whose names the editor offers. */
  projectId: string
  /** Named in the editor's title bar, beside the script's own name. */
  projectName: string
  /** Whether this reader may change the script. Running it writes the
   *  project's datasets, so that takes the manager role over the project,
   *  while anybody who can see the project can read it. The server refuses
   *  the rest either way; this is so that nothing invites them to try. */
  canEdit: boolean
  /** Called once the script is gone, so the page can open another. */
  onDeleted?: (projectId: string) => void
}) {
  const queryClient = useQueryClient()
  const ask = useDialog()
  const toast = useToast()
  // Drafts belong to the account that typed them. See `script-drafts`.
  const owner = useAuth().user?.id ?? ''
  const [text, setText] = useState('')
  // What the editor held when it was last saved, so "unsaved changes" is a
  // comparison rather than a flag somebody has to remember to clear.
  const [saved, setSaved] = useState('')
  // The output of the last run here, kept while the page is away: coming back
  // to a script shows what it just did. See `script-drafts`.
  const [log, setLogShown] = useState<LogLine[]>(() => recallLog(owner, scriptId))
  const setLog = (next: LogLine[]) => {
    rememberLog(owner, scriptId, next)
    setLogShown(next)
  }
  /** The draft put back in the box when the editor opened, if there was one,
   *  so the editor can say so. */
  const [restored, setRestored] = useState<Draft | null>(null)
  /** Whether the draft question has been settled for this script. Until it
   *  has, nothing may be written over the draft or cleared: the box is still
   *  empty, or still holds the saved script, and either would read as "no
   *  changes" and throw the draft away before it was put back. */
  const [draftSettled, setDraftSettled] = useState(false)
  /** Whether the draft is in the browser's storage, so it outlives the tab.
   *  When it cannot be, closing the tab asks first. */
  const [draftKept, setDraftKept] = useState(true)
  /** The side panel. Null until somebody picks: it then opens on the output
   *  of a script that has run and on the reference for one that has not. */
  const [panel, setPanel] = useState<'output' | 'reference' | null>(null)
  const [caret, setCaret] = useState({ line: 1, column: 1 })

  const box = useRef<ScriptEditorHandle>(null)

  /** Put an example where the cursor is, then carry on from the end of it.
   *  Through the editor, as typing it would be, so it arrives in the box the
   *  way a keystroke does. */
  const insert = (line: string) => box.current?.insertLine(line)

  const script = useQuery({
    queryKey: ['script', scriptId],
    queryFn: () => api.get<Script>(`/scripts/${scriptId}`),
    // Asked again whenever the editor opens, rather than shown from a copy up
    // to half a minute old. Somebody coming back to a draft has to see the
    // script as it is now, or a colleague's save in the meantime goes
    // unmentioned and Save writes over it.
    refetchOnMount: 'always',
  })

  // What the editor colours and offers: the language, read off the engine
  // and the same for every script, and this project's datasets with their
  // variables. Neither holds up the editor - without them it is a plain box
  // until they arrive.
  const vocabulary = useQuery({
    queryKey: ['script-language'],
    queryFn: () => api.get<Vocabulary>('/scripts/language'),
    staleTime: Infinity,
  })
  const names = useQuery({
    queryKey: ['script-names', projectId],
    queryFn: () => api.get<ScriptNames>(`/projects/${projectId}/script/names`),
  })
  const language = useMemo(
    () => indexLanguage(vocabulary.data ?? EMPTY_VOCABULARY, names.data),
    [vocabulary.data, names.data],
  )

  /** The script the box was last filled for. See `fillWith`.
   *
   *  Anything that refetches while somebody is typing - a failed run asking
   *  for the newer error, a window regaining focus - used to refill the box
   *  from the answer, throwing away the draft they were correcting. Reads,
   *  writes and the last error come from the query and are redrawn freely;
   *  the text is only replaced while nobody has changed it.
   */
  const filledFor = useRef<string | null>(null)
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
      script: scriptId,
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
    filledFor.current = scriptId
    shown.current = fill
    setText(fill)
    // `text` and `saved` are read above, so they belong here. The effect runs
    // again when they change and stops at `fillWith`, which is the point:
    // the first keystroke is what hands the box over.
  }, [script.data, scriptId, text, saved])

  // Put back what somebody had typed here and not saved, once the box has
  // been filled for the script. After the fill, so the editor's own marker
  // is on what the project opens on and the draft reads as theirs - which
  // it is - and no later answer writes over it. See `fillWith`.
  //
  // Not settled for a reader who may not edit: nothing is kept for them, and
  // if the right to edit arrives later - the page learning it a moment after
  // the script - the draft is put back then rather than having been passed
  // over, and then cleared as though there were none.
  useEffect(() => {
    if (draftSettled || !canEdit || script.data === undefined) return
    if (filledFor.current !== scriptId) return
    const draft = readDraft(owner, scriptId)
    if (draft && draft.text !== openingText(script.data)) {
      setText(draft.text)
      setRestored(draft)
    }
    setDraftSettled(true)
  }, [draftSettled, script.data, scriptId, canEdit, owner, text])

  const keep = useMutation({
    mutationFn: (next: string) => api.patch<Script>(`/scripts/${scriptId}`, { text: next }),
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
      queryClient.setQueryData(['script', scriptId], result)
      // The list beside the editor counts commands and says whether each
      // script is saved.
      queryClient.invalidateQueries({ queryKey: ['scripts'] })
      queryClient.invalidateQueries({ queryKey: ['project-overview', projectId] })
    },
  })

  const run = useMutation({
    mutationFn: (next: string) =>
      api.post<RunResult>(`/scripts/${scriptId}/run`, { text: next }),
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
      queryClient.invalidateQueries({ queryKey: ['script', scriptId] })
      queryClient.invalidateQueries({ queryKey: ['datasets'] })
      // A dataset it saved is one the next `use` can name, so the editor
      // offers it.
      queryClient.invalidateQueries({ queryKey: ['script-names', projectId] })
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
      queryClient.invalidateQueries({ queryKey: ['script', scriptId] })
      // A script that stopped partway saved what it got to, which is the
      // whole reason the run is not unwound.
      queryClient.invalidateQueries({ queryKey: ['datasets'] })
      // And the list beside the editor marks it as failed.
      queryClient.invalidateQueries({ queryKey: ['scripts'] })
    },
  })

  const drop = useMutation({
    mutationFn: () => api.delete<{ detail: string }>(`/scripts/${scriptId}`),
    onSuccess: async (result) => {
      // The script is gone, and with it anything kept for it here: a draft
      // of a script that no longer exists could only ever be put back into
      // nothing.
      clearDraft(owner, scriptId)
      rememberLog(owner, scriptId, [])
      toast.push(result.detail, 'success')
      queryClient.invalidateQueries({ queryKey: ['project-overview', projectId] })
      // The list is asked again before the page moves on, so what it opens
      // next is chosen from the scripts that are left.
      await queryClient.invalidateQueries({ queryKey: ['scripts'] })
      onDeleted?.(projectId)
    },
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  const rename = useMutation({
    mutationFn: (name: string) => api.patch<Script>(`/scripts/${scriptId}`, { name }),
    onSuccess: (result) => {
      // Only the name is written back. The text in the answer is what the
      // server holds, and the box may hold more than that by now.
      queryClient.setQueryData<Script>(['script', scriptId], (was) =>
        was ? { ...was, name: result.name } : result,
      )
      queryClient.invalidateQueries({ queryKey: ['scripts'] })
      queryClient.invalidateQueries({ queryKey: ['project-overview', projectId] })
    },
  })

  const dirty = text !== saved
  // Whether leaving would lose anything, which is not the same as `dirty`. A
  // project with nothing saved opens on the run on record, so the box differs
  // from the saved text before anybody touches it - Save is right to offer
  // itself, and asking "leave without saving?" would be a false alarm: coming
  // back opens on that same run. What is lost is a change from what the
  // editor opens on.
  const wouldLose = script.data !== undefined && text !== openingText(script.data)

  // Above the early return too, being hooks. Changes that leaving would lose
  // are kept as a draft as they are typed, and the draft goes once nothing
  // would be lost - saved, run cleanly, put back, or the script deleted. So
  // leaving the page, opening another script or reloading loses nothing.
  //
  // Not while the script is being deleted: the delete clears the draft, and
  // a keystroke landing after it would otherwise keep one for a script that
  // is gone.
  useEffect(() => {
    if (!draftSettled || !canEdit || script.data === undefined) return
    if (drop.isPending || drop.isSuccess) return
    if (wouldLose) {
      setDraftKept(
        writeDraft(
          owner,
          scriptId,
          draftFrom(readDraft(owner, scriptId), text, openingText(script.data), new Date().toISOString()),
        ),
      )
    } else {
      clearDraft(owner, scriptId)
      setRestored(null)
    }
  }, [draftSettled, canEdit, script.data, wouldLose, text, scriptId, owner, drop.isPending, drop.isSuccess])

  // Closing the tab loses a draft only where the browser would not keep it,
  // and only then is it left to the browser's own question.
  useEffect(() => {
    if (!wouldLose || draftKept) return
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault()
      event.returnValue = ''
    }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [wouldLose, draftKept])

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
  // This is about the buttons, not the box: typing stays free while a save
  // or a run is out, and what waits is firing a second request on top of the
  // first. A delete is the exception, and so is the moment after one, while
  // the page moves on: there is nothing left to send anything to.
  const busy = run.isPending || keep.isPending || drop.isPending || rename.isPending || drop.isSuccess
  const name = script.data?.name ?? ''
  const called = `${name || 'Script'} in ${projectName}`
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
  const commands = commandStarts(text).length
  const side = panel ?? (last || log.length ? 'output' : 'reference')

  const start = () => {
    setPanel('output')
    run.mutate(text)
  }

  /** Put the caret at the start of a line and bring it into view. */
  const goTo = (line: number) => box.current?.goTo(line)

  const notice = 'flex flex-wrap items-center gap-x-2 gap-y-1 border-b px-3 py-1.5 text-xs'
  const plain = `${notice} border-ink-200 bg-ink-50 text-ink-700 dark:border-dark-200 dark:bg-dark-100 dark:text-dark-700`
  const amber = `${notice} border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200`

  return (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col lg:flex-row">
      <section
        className="flex min-h-0 min-w-0 flex-1 flex-col"
        aria-label={called}
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
            <ScriptName
              name={name}
              canEdit={canEdit && !busy}
              saving={rename.isPending}
              onRename={async (next) => {
                try {
                  await rename.mutateAsync(next)
                  return null
                } catch (error) {
                  return (error as Error).message
                }
              }}
            >
              <Link
                to={`/projects/${projectId}`}
                className="truncate text-xs text-ink-500 hover:text-brand-700 dark:text-dark-500 dark:hover:text-brand-400"
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
            </ScriptName>
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
              <button
                className="btn-ghost btn-sm text-red-700 dark:text-red-300"
                disabled={busy}
                title="Delete this script"
                onClick={async () => {
                  const sure = await ask.confirm({
                    title: `Delete '${name}'?`,
                    message:
                      'The script goes, along with what its last run read and wrote. ' +
                      'The datasets it built stay exactly as they are - deleting the ' +
                      'recipe does not unmake what it cooked - and the project\'s ' +
                      'other scripts are not touched.',
                    confirmLabel: 'Delete script',
                    tone: 'danger',
                  })
                  if (sure) drop.mutate()
                }}
              >
                {drop.isPending && <Spinner className="h-3.5 w-3.5" />}
                Delete
              </button>
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
        {restored && wouldLose && script.data && (
          // Put back from a draft, which is easy to mistake for the saved
          // script - and if the saved one changed since, Save would write
          // over somebody else's work. Both are said, with the way back.
          <div className={plain}>
            <span>
              Your unsaved changes from {relativeTime(restored.at)} are back in the box.
              {restored.base !== openingText(script.data) &&
                ' The saved script has changed since you made them.'}
            </span>
            <button
              className="font-medium text-brand-700 hover:underline dark:text-brand-400"
              onClick={() => setText(script.data ? openingText(script.data) : '')}
            >
              Discard them
            </button>
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
          <ScriptEditor
            ref={box}
            label={called}
            value={text}
            onChange={setText}
            // Read-only once it is being deleted: anything typed then would be
            // typed into a script that is about to be gone.
            readOnly={!canEdit || drop.isPending || drop.isSuccess}
            index={language}
            stoppedLine={stopped}
            onCaret={setCaret}
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
                        {/* Kept as written: tabulate and summarize answer
                            with a table whose columns line up by spaces, which
                            scrolls rather than wraps so they stay lined up. */}
                        <div
                          className={`overflow-x-auto ${
                            entry.message.includes('\n') ? 'whitespace-pre' : 'whitespace-pre-wrap'
                          } ${
                            entry.ok
                              ? 'text-green-700 dark:text-green-400'
                              : 'text-red-700 dark:text-red-300'
                          }`}
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

/** The script's name, renamed where it is shown, as a file is in an editor's
 *  tab: click it, type, Enter. Escape or a name left empty puts it back.
 *
 *  What sits beside the name - its project, whether it is saved - is handed
 *  in and set aside while it is being renamed, so the field has the room and
 *  the toolbar stays on one line. */
function ScriptName({
  name,
  canEdit,
  saving,
  onRename,
  children,
}: {
  name: string
  canEdit: boolean
  saving: boolean
  /** Resolves to null once the name is kept, or to why it was not. */
  onRename: (name: string) => Promise<string | null>
  children?: ReactNode
}) {
  const [editing, setEditing] = useState<string | null>(null)
  const [problem, setProblem] = useState('')
  // Enter and then the field losing focus are two calls for one rename, and
  // the second must not send it again while the first is out.
  const sending = useRef(false)

  const finish = async () => {
    if (editing === null || sending.current) return
    const next = editing.trim().replace(/\s+/g, ' ')
    if (!next || next === name) {
      setEditing(null)
      setProblem('')
      return
    }
    sending.current = true
    const refused = await onRename(next).finally(() => {
      sending.current = false
    })
    // Left open on a name the project already has, with the reason, so it
    // can be changed rather than typed again from the start.
    if (refused) setProblem(refused)
    else {
      setEditing(null)
      setProblem('')
    }
  }

  if (editing === null) {
    return (
      <>
        {canEdit ? (
          <button
            className="truncate rounded-control px-1 text-[13px] font-semibold text-ink-800 hover:bg-ink-100 dark:text-dark-800 dark:hover:bg-dark-200"
            title="Rename this script"
            onClick={() => setEditing(name)}
          >
            {name}
          </button>
        ) : (
          <span className="truncate text-[13px] font-semibold text-ink-800 dark:text-dark-800">{name}</span>
        )}
        {children}
      </>
    )
  }
  return (
    <span className="relative flex min-w-0 items-center gap-1.5">
      <input
        autoFocus
        aria-label="Script name"
        aria-invalid={problem ? true : undefined}
        aria-describedby={problem ? 'script-name-problem' : undefined}
        className="input input-sm w-48 font-semibold"
        value={editing}
        maxLength={120}
        // Not disabled: a field that is disabled under the cursor drops its
        // focus, and with it the place to try another name.
        readOnly={saving}
        onChange={(event) => {
          setEditing(event.target.value)
          setProblem('')
        }}
        onFocus={(event) => event.target.select()}
        onBlur={() => void finish()}
        onKeyDown={(event) => {
          if (event.key === 'Enter') {
            event.preventDefault()
            void finish()
          } else if (event.key === 'Escape') {
            event.preventDefault()
            setEditing(null)
            setProblem('')
          }
        }}
      />
      {saving && <Spinner className="h-3.5 w-3.5" />}
      {problem && (
        // Under the field rather than beside it, where it would push the
        // toolbar's buttons onto a second line.
        <span
          id="script-name-problem"
          role="alert"
          className="absolute left-0 top-full z-20 mt-1 w-72 rounded-control border border-red-200 bg-red-50 px-2 py-1 text-xs text-red-800 shadow-md dark:border-red-500/30 dark:bg-dark-50 dark:text-red-300"
        >
          {problem}
        </span>
      )}
    </span>
  )
}
