/**
 * Every project's script, and the order they have to run in.
 *
 * A script belongs to a project and is edited there, which is right: it is
 * that project's recipe, read top to bottom. But an office runs several
 * projects, and the scripts are not independent of each other - one writes a
 * cleaned person file, that file is moved to the project that reports on it,
 * and the second script reads it. Run them the other way round and the second
 * builds on last week's data, silently, because nothing fails.
 *
 * Nothing on any single project's page can show that, because the
 * relationship is between projects. So this page shows all of them at once,
 * with the order read off what each run actually opened and saved.
 *
 * The step is what the page is for, and it is not a position in a queue.
 * Scripts that wait on nobody are all first, and numbering them 1, 2, 3 would
 * tell somebody to do one at a time what they can do in any order. So they are
 * grouped by step, and a step above the first says who it waits for.
 */
import { useMemo } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { relativeTime } from '@/lib/format'
import { Badge, Card, EmptyState, ErrorNote, Loading, PageHeader } from '@/components/ui'

interface ScriptPlace {
  project_id: string
  project_name: string
  step: number
  waits_for: string[]
  in_a_cycle: boolean
  reads: string[]
  writes: string[]
  lines: number
  last_run_at: string | null
  last_error: string
  /** Whether this reader may change this script, which is not the same as
   *  being able to see it. The page lists every project somebody can view. */
  can_edit: boolean
}

export default function Scripts() {
  const scripts = useQuery({
    queryKey: ['scripts'],
    queryFn: () => api.get<{ places: ScriptPlace[] }>('/scripts'),
  })

  const places = scripts.data?.places ?? []

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

  if (scripts.isLoading) return <Loading />
  if (scripts.error) return <ErrorNote error={scripts.error} retry={scripts.refetch} />

  const failing = places.filter((one) => one.last_error).length

  return (
    <div>
      <PageHeader
        title="Scripts"
        description="Every project's data preparation, and the order it has to run in"
      />

      {!places.length ? (
        <Card>
          <EmptyState
            icon="▤"
            title="No scripts yet"
            description="A project's script is written on its Command tab. Once one has run, it appears here with what it reads and writes, and a way straight back to it."
          />
        </Card>
      ) : (
        <div className="space-y-4">
          <p className="text-[13px] text-ink-600 dark:text-dark-600">
            {places.length === 1 ? '1 script' : `${places.length} scripts`}
            {steps.length > 1 && `, in ${steps.length} steps`}
            {failing > 0 && `, ${failing} with an error from the last run`}. The order
            is read from what each run actually opened and saved, not from the text.
          </p>

          {steps.map(([step, group]) => (
            <section key={step} className="space-y-2">
              <h2 className="text-[13px] font-semibold text-ink-700 dark:text-dark-700">
                {/* Counted from one for a reader. The step from the server is
                    counted from zero, and "After step 1" on the scripts that
                    are step 1 reads as off by one however true it is. */}
                Step {step + 1}
                <span className="ml-2 font-normal text-ink-500 dark:text-dark-500">
                  {group.length > 1
                    ? `${group.length} scripts, in any order`
                    : '1 script'}
                  {step === 0 && ', waiting on nothing'}
                </span>
              </h2>
              <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                {group.map((place) => (
                  <ScriptCard key={place.project_id} place={place} />
                ))}
              </div>
            </section>
          ))}

          {tangled.length > 0 && (
            <section className="space-y-2">
              <h2 className="text-[13px] font-semibold text-ink-700 dark:text-dark-700">
                No order
                <span className="ml-2 font-normal text-ink-500 dark:text-dark-500">
                  each reads what another writes, so there is no first
                </span>
              </h2>
              <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                {tangled.map((place) => (
                  <ScriptCard key={place.project_id} place={place} />
                ))}
              </div>
            </section>
          )}
        </div>
      )}
    </div>
  )
}

function ScriptCard({ place }: { place: ScriptPlace }) {
  return (
    // Full height so the cards in a row match and their buttons line up: the
    // Card's own body is the thing that has to stretch, not just the section.
    <Card className="flex h-full flex-col" bodyClassName="flex-1">
      <div className="flex h-full flex-col space-y-3 p-4">
        <div className="flex items-start justify-between gap-2">
          {/* Straight to the script, not to the project. A page that lists
              every script and sends you to a project page, open on Data, to
              find a tab called Command is a list you cannot act on.

              For a reader who may not change it, the project: the script tab
              is not offered to them, and a link that lands them somewhere
              other than where it said is the fault this page had already. */}
          <Link
            to={`/projects/${place.project_id}${place.can_edit ? '?tab=script' : ''}`}
            className="text-[14px] font-semibold text-brand-600 hover:underline dark:text-brand-400"
          >
            {place.project_name}
          </Link>
          {place.last_error ? (
            <Badge tone="danger">Last run failed</Badge>
          ) : place.last_run_at ? (
            <Badge tone="success">Ran</Badge>
          ) : (
            <Badge tone="neutral">Never run</Badge>
          )}
        </div>

        <dl className="space-y-1.5 text-[13px]">
          <Row label="Reads" names={place.reads} />
          <Row label="Writes" names={place.writes} />
          {place.waits_for.length > 0 && (
            <Row label="Waits for" names={place.waits_for} />
          )}
        </dl>

        {place.last_error && (
          <p className="rounded-control bg-red-50 px-2.5 py-1.5 text-xs text-red-700 dark:bg-red-500/10 dark:text-red-300">
            {place.last_error}
          </p>
        )}

        <p className="text-xs text-ink-500 dark:text-dark-500">
          {place.lines > 0
            ? `${place.lines} command${place.lines === 1 ? '' : 's'}`
            : 'Run without being saved'}
          {place.last_run_at && ` · last run ${relativeTime(place.last_run_at)}`}
        </p>

        {/* On its own line at the foot of the card, pushed down so that every
            card's button sits on the same line however much its reads and
            writes ran to. Said out loud as well as on the title: "open the
            project" is what the heading already meant, and is what sent
            people looking for a tab called Command.

            Only where there is an editor to open. Running a script writes the
            project's datasets, so it takes the manager role over that project
            - while the page lists every project a reader can see. Shown to
            everybody, the button would put most of them back on the project
            with nothing said, which is the fault this page had already. */}
        {place.can_edit && (
          <div className="mt-auto flex justify-end pt-1">
            <Link
              to={`/projects/${place.project_id}?tab=script`}
              className="btn-secondary btn-sm"
            >
              Edit script
            </Link>
          </div>
        )}
      </div>
    </Card>
  )
}

function Row({ label, names }: { label: string; names: string[] }) {
  return (
    <div className="flex gap-2">
      <dt className="shrink-0 text-ink-500 dark:text-dark-500">{label}</dt>
      <dd className="min-w-0 text-ink-700 dark:text-dark-700">
        {names.length ? names.join(', ') : <span className="text-ink-400">nothing</span>}
      </dd>
    </div>
  )
}
