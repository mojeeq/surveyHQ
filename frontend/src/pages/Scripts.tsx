/**
 * Every project's script, and the order they have to run in - and the place
 * they are written.
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
import { useToast } from '@/hooks/useToast'
import { relativeTime } from '@/lib/format'
import { lastOpen, rememberOpen, useDrafts } from '@/lib/script-drafts'
import type { Project } from '@/lib/types'
import { EmptyState, ErrorNote, Loading } from '@/components/ui'

interface ScriptPlace {
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
  const drafts = useDrafts()

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
    mutationFn: (project_ids: string[]) =>
      api.put<{ places: ScriptPlace[] }>('/scripts/order', { project_ids }),
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
  const asked = params.get('project')
  // With nothing in the address, the script that was open last, or else the
  // first in the list: coming back to the page from anywhere in the app, the
  // sidebar included, should be coming back to where you were - and an
  // editor that opens on nothing is a page to click through before it does
  // anything.
  //
  // Written into the address rather than only worked out, so the open script
  // stays open when the list changes under it. Deleting it takes it out of
  // the list, and an editor that then jumped to whichever script was first
  // would carry off whatever had been typed in its place.
  useEffect(() => {
    if (asked) {
      rememberOpen(asked)
      return
    }
    if (scripts.isLoading) return
    const back = lastOpen()
    const known =
      !!back &&
      (places.some((one) => one.project_id === back) ||
        !!projects.data?.some((one) => one.id === back))
    // A script that was being started has no place in the list yet; wait for
    // the projects before deciding it is gone.
    if (back && !known && projects.isLoading) return
    const target = known ? back : listed[0]?.project_id
    if (target) setParams({ project: target }, { replace: true })
  }, [asked, listed, places, projects.data, projects.isLoading, scripts.isLoading, setParams])

  if (scripts.isLoading) return <Loading />
  if (scripts.error) return <ErrorNote error={scripts.error} retry={scripts.refetch} />

  const openId = asked ?? listed[0]?.project_id ?? null
  const open = places.find((one) => one.project_id === openId)
  const openProject = projects.data?.find((one) => one.id === openId)
  // Projects somebody here may start a script for, which have none yet.
  const startable = (projects.data ?? [])
    .filter((one) => mayWrite(one) && !places.some((place) => place.project_id === one.id))
    .sort((a, b) => a.name.localeCompare(b.name))
  const failing = places.filter((one) => one.last_error).length

  // Scripts being started - a project with none saved yet - that are open or
  // have changes waiting. They are in no step until they are saved or run.
  const fresh = (projects.data ?? []).filter(
    (one) =>
      mayWrite(one) &&
      !places.some((place) => place.project_id === one.id) &&
      (one.id === openId || drafts.has(one.id)),
  )

  /** Open another script. Nothing is lost by it: changes not saved in the
   *  one being left are kept, and are back when it is opened again. */
  const choose = (projectId: string) => {
    if (projectId === openId) return
    // Replaced rather than pushed, so the back button leaves the page rather
    // than walking back through every script that was looked at.
    setParams({ project: projectId }, { replace: true })
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
            <NewScript projects={startable} onChoose={choose} />
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto py-1">
            {fresh.length > 0 && (
              <Group title="New" detail="not saved yet">
                {fresh.map((project) => (
                  <li key={project.id}>
                    <button
                      onClick={() => choose(project.id)}
                      aria-current={project.id === openId ? 'true' : undefined}
                      className={`flex w-full items-start gap-2 px-3 py-1.5 text-left ${
                        project.id === openId
                          ? 'bg-brand-50 text-brand-800 dark:bg-brand-500/15 dark:text-brand-200'
                          : 'text-ink-700 hover:bg-ink-50 dark:text-dark-700 dark:hover:bg-dark-100'
                      }`}
                    >
                      <Mark tone="new" label="Not saved yet" />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-[13px] font-medium">
                          {project.name}
                          {drafts.has(project.id) && <Unsaved />}
                        </span>
                      </span>
                    </button>
                  </li>
                ))}
              </Group>
            )}

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
                      key={place.project_id}
                      place={place}
                      selected={place.project_id === openId}
                      drafted={drafts.has(place.project_id)}
                      onSelect={() => choose(place.project_id)}
                      onMove={
                        movable
                          ? (by) => {
                              const next = [...group]
                              const to = index + by
                              if (to < 0 || to >= next.length) return
                              ;[next[index], next[to]] = [next[to], next[index]]
                              reorder.mutate(next.map((one) => one.project_id))
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
                    key={place.project_id}
                    place={place}
                    selected={place.project_id === openId}
                    drafted={drafts.has(place.project_id)}
                    onSelect={() => choose(place.project_id)}
                  />
                ))}
              </Group>
            )}

            {!places.length && !openProject && (
              <p className="px-3 py-2 text-xs leading-relaxed text-ink-500 dark:text-dark-500">
                No scripts yet. Start one with <strong>New</strong> above.
              </p>
            )}
          </div>
        </nav>

        {openId && !open && projects.isLoading ? (
          <div className="grid flex-1 place-items-center">
            <Loading />
          </div>
        ) : openId && (open || openProject) ? (
          <ProjectScript
            // One editor per script: what the last one logged, where its caret
            // was and which panel it had open belong to it.
            key={openId}
            projectId={openId}
            projectName={open?.project_name ?? openProject?.name ?? ''}
            canEdit={open ? open.can_edit : !!openProject && mayWrite(openProject)}
          />
        ) : (
          <div className="grid flex-1 place-items-center p-6">
            <EmptyState
              icon="▤"
              title={openId && projects.isSuccess ? 'No such project' : 'No script open'}
              description={
                openId && projects.isSuccess
                  ? 'The link names a project that is not there, or that you cannot see.'
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
  new: 'border border-brand-500',
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
  const detail = place.last_error
    ? `failed ${relativeTime(place.last_run_at)}`
    : [
        place.lines > 0
          ? `${place.lines} command${place.lines === 1 ? '' : 's'}${place.saved ? '' : ', not saved'}`
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
          place.project_name,
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
            {place.project_name}
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
            aria-label={`Run ${place.project_name} earlier`}
            title="Run earlier in this step"
            disabled={first || busy}
            onClick={() => onMove(-1)}
          >
            ↑
          </button>
          <button
            className="btn-ghost btn-xs px-1.5"
            aria-label={`Run ${place.project_name} later`}
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

/** Start a script for a project that has none. */
function NewScript({
  projects,
  onChoose,
}: {
  projects: Project[]
  onChoose: (projectId: string) => void
}) {
  const [open, setOpen] = useState(false)
  if (!projects.length) return null
  return (
    <div
      className="relative"
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setOpen(false)
      }}
      onKeyDown={(event) => {
        if (event.key === 'Escape') setOpen(false)
      }}
    >
      <button
        className="btn-ghost btn-xs"
        aria-expanded={open}
        aria-haspopup="menu"
        onClick={() => setOpen((was) => !was)}
        title="Start a script for a project that has none"
      >
        + New
      </button>
      {open && (
        <div
          role="menu"
          className="absolute right-0 top-full z-30 mt-1 max-h-72 w-60 overflow-y-auto rounded-control border border-ink-200 bg-white py-1 shadow-lg dark:border-dark-300 dark:bg-dark-50"
        >
          <p className="px-3 pb-1 pt-0.5 text-[11px] text-ink-500 dark:text-dark-500">
            A script for…
          </p>
          {projects.map((project) => (
            <button
              key={project.id}
              role="menuitem"
              className="block w-full truncate px-3 py-1.5 text-left text-[13px] text-ink-700 hover:bg-ink-50 dark:text-dark-700 dark:hover:bg-dark-100"
              onClick={() => {
                setOpen(false)
                onChoose(project.id)
              }}
            >
              {project.name}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
