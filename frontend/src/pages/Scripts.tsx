/**
 * Every script, and the order they have to run in - and the place they are
 * written.
 *
 * An office runs several projects, and the scripts are not independent of
 * each other - one writes a cleaned person file, that file is moved to the
 * project that reports on it, and the second script reads it. Run them the
 * other way round and the second builds on last week's data, silently,
 * because nothing fails. Nothing on any single project's page can show that,
 * because the relationship is between projects, so this page shows all of
 * them at once, with the order read off what each run actually opened and
 * saved.
 *
 * The scripts used to be edited on each project's own page, behind a tab, so
 * writing one, putting it in order and deleting it were three trips between
 * two pages. They are all here now, laid out as an editor is: the list down
 * the side, the open script in the middle, its output and the reference
 * beside it.
 *
 * A project can have several scripts - clean the roster, build the household
 * file, make the tables - and the order runs between those too: the tables
 * script reads what the cleaning one writes. Each is listed by its own name,
 * with its project under it.
 *
 * The step is what the list is for, and it is not a position in a queue.
 * Scripts that wait on nobody are all first, and numbering them 1, 2, 3 would
 * tell somebody to do one at a time what they can do in any order. So they are
 * grouped by step, and a step above the first says who it waits for.
 */
import { useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ProjectScript } from '@/components/ProjectScript'
import { api } from '@/lib/api'
import { useAuth } from '@/hooks/useAuth'
import { useToast } from '@/hooks/useToast'
import { relativeTime } from '@/lib/format'
import { adoptDraft, lastOpen, rememberOpen, useDrafts } from '@/lib/script-drafts'
import { firstOf, nextName, whichToOpen } from '@/lib/script-open'
import type { Project } from '@/lib/types'
import { EmptyState, ErrorNote, Loading, Spinner } from '@/components/ui'

interface ScriptPlace {
  script_id: string
  /** What it is called in its project. */
  name: string
  /** What it is called among every script: its name where that is unique,
   *  with its project beside it where it is not. "Waits for" uses these. */
  label: string
  project_id: string
  project_name: string
  step: number
  waits_for: string[]
  in_a_cycle: boolean
  reads: string[]
  writes: string[]
  lines: number
  /** Whether `lines` counted the saved script. False means it counted the
   *  last run, which was never kept. */
  saved: boolean
  /** False when there is no text at all: a run from before the text of a run
   *  was recorded. */
  text_kept: boolean
  last_run_at: string | null
  last_error: string
  /** Whether this reader may change this script, which is not the same as
   *  being able to see it. The page lists every project somebody can view. */
  can_edit: boolean
  /** Where this sits among the scripts it shares a step with. */
  rank: number
  /** When it was started. A project's oldest script is the one a link to
   *  "the project's script" means. */
  created_at: string | null
}

/** Somebody who may write a script for this project: running one writes its
 *  datasets, which takes the manager role over it. */
function mayWrite(project: Project): boolean {
  return (
    (project.your_role === 'manager' || project.your_role === 'admin') &&
    project.status !== 'archived'
  )
}

export default function Scripts() {
  const queryClient = useQueryClient()
  const toast = useToast()
  const [params, setParams] = useSearchParams()
  // The scripts with changes nobody has saved yet, which are kept while the
  // editor is away and marked in the list. See `script-drafts`.
  const owner = useAuth().user?.id ?? ''
  const drafts = useDrafts(owner)

  const scripts = useQuery({
    queryKey: ['scripts'],
    queryFn: () => api.get<{ places: ScriptPlace[] }>('/scripts'),
  })
  // Every project, not the workspace's: a script for any of them can be
  // started here. The same key as the Projects page, which asks the same.
  const projects = useQuery({
    queryKey: ['projects', 'all'],
    queryFn: () => api.get<Project[]>('/projects?scope=all'),
  })

  /** Put one step in a new order.
   *
   *  The whole step goes, not the one that moved: a rank is a position among
   *  these, and sending one would leave the rest where nobody put them.
   */
  const reorder = useMutation({
    mutationFn: (script_ids: string[]) =>
      api.put<{ places: ScriptPlace[] }>('/scripts/order', { script_ids }),
    onSuccess: (result) => queryClient.setQueryData(['scripts'], result),
    // The server refuses a move across a step and says which dependency
    // fixes it. That is the useful half of this feature, so it is shown
    // rather than swallowed.
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  const places = useMemo(() => scripts.data?.places ?? [], [scripts.data])

  /** Grouped by step, with the ones in a ring kept out of the order. */
  const { steps, tangled } = useMemo(() => {
    const ordered = places.filter((one) => !one.in_a_cycle)
    const grouped = new Map<number, ScriptPlace[]>()
    for (const place of ordered) {
      grouped.set(place.step, [...(grouped.get(place.step) ?? []), place])
    }
    return {
      steps: [...grouped.entries()].sort((a, b) => a[0] - b[0]),
      tangled: places.filter((one) => one.in_a_cycle),
    }
  }, [places])

  const listed = useMemo(
    () => [...steps.flatMap(([, group]) => group), ...tangled],
    [steps, tangled],
  )
  const asked = params.get('script')
  const askedProject = params.get('project')
  // With no script in the address, one is chosen and written there: a
  // project's first script for a link that names the project, which is every
  // link from before a project could have several; or the script that was
  // open last, or else the first in the list. Coming back to the page from
  // anywhere in the app, the sidebar included, should be coming back to where
  // you were - and an editor that opens on nothing is a page to click through
  // before it does anything. See `whichToOpen`.
  //
  // Written into the address rather than only worked out, so the open script
  // stays open when the list changes under it.
  useEffect(() => {
    if (asked) {
      rememberOpen(owner, asked)
      return
    }
    if (scripts.isLoading || scripts.error) return
    const target = whichToOpen(listed, { project: askedProject, last: lastOpen(owner) })
    if (target && 'script' in target) setParams({ script: target.script }, { replace: true })
  }, [asked, askedProject, listed, scripts.isLoading, scripts.error, setParams, owner])

  // Drafts were kept by project while a project had one script. Each goes to
  // the script that was the project's, so nobody's unsaved work is left under
  // a key nothing reads any more.
  useEffect(() => {
    for (const projectId of new Set(places.map((one) => one.project_id))) {
      const first = firstOf(places, projectId)
      if (first) adoptDraft(owner, projectId, first.script_id)
    }
  }, [places, owner])

  if (scripts.isLoading) return <Loading />
  if (scripts.error) return <ErrorNote error={scripts.error} retry={scripts.refetch} />

  const openId = asked
  const open = places.find((one) => one.script_id === openId)
  // Projects somebody here may start a script in. Any of them: a project
  // can have as many scripts as it needs.
  const startable = (projects.data ?? [])
    .filter(mayWrite)
    .sort((a, b) => a.name.localeCompare(b.name))
  // A link named a project with no script in it yet, which is an invitation
  // to start one there - where the reader may.
  const startingIn =
    !openId && askedProject && !places.some((one) => one.project_id === askedProject)
      ? (projects.data ?? []).find((one) => one.id === askedProject)
      : undefined
  const failing = places.filter((one) => one.last_error).length

  /** Open another script. Nothing is lost by it: changes not saved in the
   *  one being left are kept, and are back when it is opened again. */
  const choose = (scriptId: string) => {
    if (scriptId === openId) return
    // Replaced rather than pushed, so the back button leaves the page rather
    // than walking back through every script that was looked at.
    setParams({ script: scriptId }, { replace: true })
  }

  /** After a delete, another script of the same project if it has one, and
   *  otherwise the first in the list. Read from the list as asked again
   *  after the delete, so the script just deleted is not among them. */
  const afterDelete = (projectId: string) => {
    const left = queryClient.getQueryData<{ places: ScriptPlace[] }>(['scripts'])?.places ?? []
    const next = firstOf(left, projectId) ?? left[0]
    setParams(next ? { script: next.script_id } : {}, { replace: true })
  }

  return (
    <div className="flex flex-col gap-3 lg:h-[calc(100vh-128px)]">
      <div className="flex shrink-0 flex-wrap items-baseline gap-x-3 gap-y-1">
        <h1 className="text-[20px] font-semibold text-ink-900">Scripts</h1>
        <p className="text-[13px] text-ink-500 dark:text-dark-500">
          {places.length === 1 ? '1 script' : `${places.length} scripts`}
          {steps.length > 1 && ` in ${steps.length} steps`}
          {failing > 0 && `, ${failing} failed on the last run`}. The order is read
          from what each run opened and saved.
        </p>
      </div>

      <div className="card flex min-h-0 flex-1 flex-col overflow-hidden lg:flex-row">
        <nav
          aria-label="Scripts"
          className="flex max-h-72 shrink-0 flex-col border-b border-ink-200 dark:border-dark-200 lg:max-h-none lg:w-64 lg:border-b-0 lg:border-r"
        >
          <div className="flex shrink-0 items-center justify-between gap-2 border-b border-ink-200 py-1.5 pl-3 pr-1.5 dark:border-dark-200">
            <span className="text-[11px] font-semibold uppercase tracking-wide text-ink-500 dark:text-dark-500">
              Explorer
            </span>
            <NewScript
              projects={startable}
              places={places}
              // In the project of the script that is open, where the next
              // script is most likely to go.
              initialProject={open?.project_id}
              onCreated={choose}
            />
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto py-1">
            {steps.map(([step, group]) => {
              const waits = [...new Set(group.flatMap((one) => one.waits_for))]
              // Only where there is somewhere to go and the reader may move
              // both ends: swapping moves two scripts, not one.
              const movable = group.length > 1 && group.every((one) => one.can_edit)
              return (
                <Group
                  key={step}
                  // Counted from one for a reader. The step from the server is
                  // counted from zero, and "After step 1" on the scripts that
                  // are step 1 reads as off by one however true it is.
                  title={`Step ${step + 1}`}
                  detail={
                    step === 0
                      ? group.length > 1
                        ? 'any order'
                        : 'waits on nothing'
                      : `after ${waits.join(', ')}`
                  }
                >
                  {group.map((place, index) => (
                    <Entry
                      key={place.script_id}
                      place={place}
                      selected={place.script_id === openId}
                      drafted={drafts.has(place.script_id)}
                      onSelect={() => choose(place.script_id)}
                      onMove={
                        movable
                          ? (by) => {
                              const next = [...group]
                              const to = index + by
                              if (to < 0 || to >= next.length) return
                              ;[next[index], next[to]] = [next[to], next[index]]
                              reorder.mutate(next.map((one) => one.script_id))
                            }
                          : undefined
                      }
                      first={index === 0}
                      last={index === group.length - 1}
                      busy={reorder.isPending}
                    />
                  ))}
                </Group>
              )
            })}

            {tangled.length > 0 && (
              <Group title="No order" detail="each reads what another writes">
                {tangled.map((place) => (
                  <Entry
                    key={place.script_id}
                    place={place}
                    selected={place.script_id === openId}
                    drafted={drafts.has(place.script_id)}
                    onSelect={() => choose(place.script_id)}
                  />
                ))}
              </Group>
            )}

            {!places.length && (
              <p className="px-3 py-2 text-xs leading-relaxed text-ink-500 dark:text-dark-500">
                No scripts yet. Start one with <strong>New</strong> above.
              </p>
            )}
          </div>
        </nav>

        {open ? (
          <ProjectScript
            // One editor per script: what the last one logged, where its caret
            // was and which panel it had open belong to it.
            key={open.script_id}
            scriptId={open.script_id}
            projectId={open.project_id}
            projectName={open.project_name}
            canEdit={open.can_edit}
            onDeleted={afterDelete}
          />
        ) : startingIn && mayWrite(startingIn) ? (
          <div className="grid flex-1 place-items-center p-6">
            <div className="w-full max-w-sm">
              <h2 className="text-[15px] font-semibold text-ink-900 dark:text-dark-900">
                A script for {startingIn.name}
              </h2>
              <p className="mb-3 mt-1 text-xs leading-relaxed text-ink-500 dark:text-dark-500">
                {startingIn.name} has no script yet. A script reads the project&apos;s
                datasets, puts them together and writes new ones.
              </p>
              <StartScript
                projects={startable}
                places={places}
                initialProject={startingIn.id}
                onCreated={choose}
              />
            </div>
          </div>
        ) : (
          <div className="grid flex-1 place-items-center p-6">
            <EmptyState
              icon="▤"
              title={
                openId
                  ? 'No such script'
                  : startingIn
                    ? `${startingIn.name} has no script yet`
                    : 'No script open'
              }
              description={
                openId
                  ? 'The link names a script that is not there, or that you cannot see. It may have been deleted.'
                  : startingIn
                    ? 'Starting one takes the manager role on the project.'
                    : startable.length
                      ? 'Choose a script from the list, or start one with New. A script reads the project’s datasets, puts them together and writes new ones.'
                      : 'Nobody has written a script you can see yet. Starting one takes the manager role on a project.'
              }
            />
          </div>
        )}
      </div>
    </div>
  )
}

function Group({
  title,
  detail,
  children,
}: {
  title: string
  detail: string
  children: ReactNode
}) {
  return (
    <section className="pb-1">
      <h2 className="flex items-baseline gap-1.5 px-3 pb-0.5 pt-2 text-[11px] font-semibold uppercase tracking-wide text-ink-500 dark:text-dark-500">
        {title}
        <span className="truncate font-normal normal-case tracking-normal" title={detail}>
          · {detail}
        </span>
      </h2>
      <ul>{children}</ul>
    </section>
  )
}

/** The mark an editor puts on a file with unsaved changes. */
function Unsaved() {
  return (
    <span className="ml-1 text-amber-600 dark:text-amber-400" title="Unsaved changes, kept until you save or discard them">
      •<span className="sr-only"> unsaved changes</span>
    </span>
  )
}

const MARKS = {
  failed: 'bg-red-500',
  unsaved: 'bg-amber-500',
  ran: 'bg-brand-500',
  never: 'border border-ink-400 dark:border-dark-500',
} as const

/** How a script stands, as a dot with its meaning beside it for a screen
 *  reader and under the pointer - the line under the name says it in words. */
function Mark({ tone, label }: { tone: keyof typeof MARKS; label: string }) {
  return (
    <span className="mt-[5px] shrink-0" title={label}>
      <span aria-hidden className={`block h-2 w-2 rounded-full ${MARKS[tone]}`} />
      <span className="sr-only">{label}</span>
    </span>
  )
}

function Entry({
  place,
  selected,
  drafted,
  onSelect,
  onMove,
  first,
  last,
  busy,
}: {
  place: ScriptPlace
  selected: boolean
  /** Whether it has changes nobody has saved yet. */
  drafted: boolean
  onSelect: () => void
  /** Move this script earlier (-1) or later (+1) among its step. Absent
   *  where the step holds one script, or where the reader may not change
   *  every script in it. */
  onMove?: (by: -1 | 1) => void
  first?: boolean
  last?: boolean
  busy?: boolean
}) {
  const [tone, label]: [keyof typeof MARKS, string] = place.last_error
    ? ['failed', 'Last run failed']
    : !place.last_run_at
      ? ['never', 'Never run']
      : !place.saved
        ? ['unsaved', 'Ran, never saved']
        : ['ran', 'Ran']
  // Its project under its name: two projects' scripts can share a name, and
  // most will at first - every project's first script is "Main script".
  const detail = place.last_error
    ? `${place.project_name} · failed ${relativeTime(place.last_run_at)}`
    : [
        place.project_name,
        place.lines > 0
          ? `${place.lines} command${place.lines === 1 ? '' : 's'}${place.saved ? '' : ', not saved'}`
          : !place.last_run_at
            ? // Just started. "Its text was not kept" is about a run from
              // before a run's text was recorded, and there is no run here.
              'nothing written yet'
            : place.text_kept
              ? 'run without being saved'
              : 'its text was not kept',
        place.last_run_at ? relativeTime(place.last_run_at) : 'never run',
      ].join(' · ')

  return (
    <li className="group relative">
      <button
        onClick={onSelect}
        aria-current={selected ? 'true' : undefined}
        title={[
          `${place.name} in ${place.project_name}`,
          place.reads.length ? `Reads ${place.reads.join(', ')}` : '',
          place.writes.length ? `Writes ${place.writes.join(', ')}` : '',
          place.waits_for.length ? `Waits for ${place.waits_for.join(', ')}` : '',
        ]
          .filter(Boolean)
          .join('\n')}
        className={`flex w-full items-start gap-2 px-3 py-1.5 text-left ${onMove ? 'pr-14' : ''} ${
          selected
            ? 'bg-brand-50 text-brand-800 dark:bg-brand-500/15 dark:text-brand-200'
            : 'text-ink-700 hover:bg-ink-50 dark:text-dark-700 dark:hover:bg-dark-100'
        }`}
      >
        <Mark tone={tone} label={label} />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[13px] font-medium">
            {place.name}
            {drafted && <Unsaved />}
          </span>
          <span
            className={`block truncate text-[11px] ${
              place.last_error ? 'text-red-700 dark:text-red-300' : 'text-ink-500 dark:text-dark-500'
            }`}
          >
            {detail}
          </span>
        </span>
      </button>
      {onMove && (
        // Buttons rather than dragging: they work from a keyboard, say what
        // they do, and a step is a handful of scripts rather than a long list
        // to haul something up. Out of the way until the row is pointed at or
        // open, as an editor's row actions are.
        <span
          className={`absolute right-1 top-1 flex ${
            selected ? '' : 'opacity-0 focus-within:opacity-100 group-hover:opacity-100'
          }`}
        >
          <button
            className="btn-ghost btn-xs px-1.5"
            aria-label={`Run ${place.label} earlier`}
            title="Run earlier in this step"
            disabled={first || busy}
            onClick={() => onMove(-1)}
          >
            ↑
          </button>
          <button
            className="btn-ghost btn-xs px-1.5"
            aria-label={`Run ${place.label} later`}
            title="Run later in this step"
            disabled={last || busy}
            onClick={() => onMove(1)}
          >
            ↓
          </button>
        </span>
      )}
    </li>
  )
}

/** Start a script: in which project, and under what name. */
function NewScript({
  projects,
  places,
  initialProject,
  onCreated,
}: {
  projects: Project[]
  places: ScriptPlace[]
  initialProject?: string
  onCreated: (scriptId: string) => void
}) {
  const [open, setOpen] = useState(false)
  if (!projects.length) return null
  return (
    <div
      className="relative"
      onKeyDown={(event) => {
        if (event.key === 'Escape') setOpen(false)
      }}
    >
      <button
        className="btn-ghost btn-xs"
        aria-expanded={open}
        aria-haspopup="dialog"
        onClick={() => setOpen((was) => !was)}
        title="Start a new script"
      >
        + New
      </button>
      {open && (
        <div
          role="dialog"
          aria-label="New script"
          className="absolute right-0 top-full z-30 mt-1 w-64 rounded-control border border-ink-200 bg-white p-3 shadow-lg dark:border-dark-300 dark:bg-dark-50"
        >
          <StartScript
            projects={projects}
            places={places}
            initialProject={
              projects.some((one) => one.id === initialProject) ? initialProject : undefined
            }
            onCreated={(id) => {
              setOpen(false)
              onCreated(id)
            }}
            onCancel={() => setOpen(false)}
          />
        </div>
      )}
    </div>
  )
}

/** The form that starts one. A name left empty is the one the project has
 *  not used yet - "Main script", then "Main script 2" - shown in the box so
 *  it is no surprise. */
function StartScript({
  projects,
  places,
  initialProject,
  onCreated,
  onCancel,
}: {
  projects: Project[]
  places: ScriptPlace[]
  initialProject?: string
  onCreated: (scriptId: string) => void
  onCancel?: () => void
}) {
  const queryClient = useQueryClient()
  const [projectId, setProjectId] = useState(initialProject ?? projects[0]?.id ?? '')
  const [name, setName] = useState('')
  const create = useMutation({
    mutationFn: () =>
      api.post<{ id: string }>('/scripts', { project_id: projectId, name: name.trim() }),
    onSuccess: async (made) => {
      // In the list before it is opened, so the page has it to open.
      await queryClient.invalidateQueries({ queryKey: ['scripts'] })
      queryClient.invalidateQueries({ queryKey: ['project-overview', projectId] })
      onCreated(made.id)
    },
  })
  return (
    <form
      className="space-y-2.5"
      onSubmit={(event) => {
        event.preventDefault()
        if (projectId && !create.isPending) create.mutate()
      }}
    >
      <label className="block">
        <span className="mb-1 block text-xs font-medium text-ink-700 dark:text-dark-700">Project</span>
        <select
          className="input"
          value={projectId}
          onChange={(event) => {
            setProjectId(event.target.value)
            create.reset()
          }}
        >
          {projects.map((project) => (
            <option key={project.id} value={project.id}>
              {project.name}
            </option>
          ))}
        </select>
      </label>
      <label className="block">
        <span className="mb-1 block text-xs font-medium text-ink-700 dark:text-dark-700">Name</span>
        <input
          autoFocus
          className="input"
          value={name}
          maxLength={120}
          placeholder={nextName(places, projectId)}
          onChange={(event) => {
            setName(event.target.value)
            create.reset()
          }}
        />
      </label>
      {create.error && (
        <p role="alert" className="text-xs text-red-700 dark:text-red-300">
          {create.error.message}
        </p>
      )}
      <div className="flex justify-end gap-2">
        {onCancel && (
          <button type="button" className="btn-ghost btn-sm" onClick={onCancel}>
            Cancel
          </button>
        )}
        <button type="submit" className="btn-primary btn-sm" disabled={!projectId || create.isPending}>
          {create.isPending && <Spinner className="h-3.5 w-3.5 text-white" />}
          Create
        </button>
      </div>
    </form>
  )
}
