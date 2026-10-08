import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type UploadProgress } from '@/lib/api'
import { useAuth } from '@/hooks/useAuth'
import { useToast } from '@/hooks/useToast'
import { formatBytes, formatNumber, relativeTime, timeLeft } from '@/lib/format'
import { summarise } from '@/lib/inventory'
import type { ArchiveImport, Dataset, Job, Page, Project } from '@/lib/types'
import ImportReview, { type Review } from '@/components/ImportReview'
import BoundaryLibrary from '@/components/BoundaryLibrary'
import ProjectPicker from '@/components/ProjectPicker'
import {
  Badge,
  Card,
  EmptyState,
  ErrorNote,
  Field,
  Loading,
  Modal,
  PageHeader,
  Spinner,
} from '@/components/ui'

const ACCEPTED = '.dta,.sav,.csv,.tab,.tsv,.txt,.xlsx,.xls,.zip'


/** How an upload is going: the bar, the numbers, and when it will end.
 *
 *  A spinner on a four gigabyte export looks the same whether the transfer is
 *  moving at full speed or died ten minutes ago, which is the difference
 *  between waiting and wondering whether to start over.
 */
export function UploadBar({ progress }: { progress: UploadProgress }) {
  const done = progress.total > 0 ? progress.sent / progress.total : 0
  const finished = progress.sent >= progress.total
  return (
    <div className="mb-4">
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-ink-100 dark:bg-dark-200">
        <div
          className="h-full rounded-full bg-brand-500 transition-[width] duration-200"
          style={{ width: `${Math.min(100, done * 100).toFixed(1)}%` }}
        />
      </div>
      <p className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-ink-600 dark:text-dark-600">
        {finished ? (
          // Every byte is across and the server is reading it. No rate applies
          // to that, and no honest estimate of it either.
          <span>Sent {formatBytes(progress.total)}. Reading it now, which takes a few minutes for an export this size.</span>
        ) : (
          <>
            <span className="font-medium text-ink-800 dark:text-dark-800">
              {Math.floor(done * 100)}%
            </span>
            <span>
              {formatBytes(progress.sent)} of {formatBytes(progress.total)}
            </span>
            {progress.rate > 0 && <span>{formatBytes(progress.rate)}/s</span>}
            {progress.remaining !== null && <span>{timeLeft(progress.remaining)}</span>}
          </>
        )}
      </p>
    </div>
  )
}

export default function Datasets() {
  const { can } = useAuth()
  const toast = useToast()
  const queryClient = useQueryClient()
  const [search, setSearch] = useState('')
  const [uploadInto, setUploadInto] = useState<string | null>(null)
  const [showParadata, setShowParadata] = useState(false)
  // Collapsed by project, remembered per browser: a server with a dozen
  // projects on it is otherwise a page nobody can find anything on.
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>(() => {
    try {
      return JSON.parse(localStorage.getItem('surveyhq.datasets.collapsed') ?? '{}')
    } catch {
      return {}
    }
  })
  const [selected, setSelected] = useState<Set<string>>(new Set())

  const toggleGroup = (id: string) => {
    const next = { ...collapsed, [id]: !collapsed[id] }
    setCollapsed(next)
    try {
      localStorage.setItem('surveyhq.datasets.collapsed', JSON.stringify(next))
    } catch {
      /* a browser that refuses storage still gets the collapse, just not next time */
    }
  }

  const toggleOne = (id: string) => {
    const next = new Set(selected)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    setSelected(next)
  }

  const datasets = useQuery({
    queryKey: ['datasets', search],
    queryFn: () =>
      api.get<Page<Dataset>>(`/datasets?limit=200&search=${encodeURIComponent(search)}`),
  })
  const projects = useQuery({
    queryKey: ['projects'],
    queryFn: () => api.get<Project[]>('/projects'),
  })

  /**
   * Datasets under the project they belong to, with the shared area last.
   *
   * A survey export produces eight datasets at once, most of them roster levels
   * and paradata, so a flat list of every dataset stops being readable after
   * two projects. Grouping is what makes "which data belongs to this round"
   * answerable at a glance.
   */
  const grouped = useMemo(() => {
    const all = (datasets.data?.items ?? []).filter(
      (d) => showParadata || !d.tags.includes('paradata'),
    )
    const byProject = new Map<string, Dataset[]>()
    for (const dataset of all) {
      const key = dataset.project_id ?? ''
      byProject.set(key, [...(byProject.get(key) ?? []), dataset])
    }
    const groups = (projects.data ?? []).map((project) => ({
      id: project.id,
      name: project.name,
      datasets: byProject.get(project.id) ?? [],
    }))
    const shared = byProject.get('') ?? []
    if (shared.length) {
      groups.push({ id: '', name: 'Shared area', datasets: shared })
    }
    return groups
  }, [datasets.data, projects.data, showParadata])

  // What the whole shelf comes to, and what each project is of it. Computed
  // from the same filtered list the groups are built from, so hiding paradata
  // moves the totals too rather than leaving them quietly describing a
  // different set of datasets than the one on screen.
  const totals = useMemo(
    () => summarise(grouped.flatMap((group) => group.datasets)),
    [grouped],
  )

  const hiddenParadata = (datasets.data?.items ?? []).filter((d) =>
    d.tags.includes('paradata'),
  ).length

  const remove = useMutation({
    mutationFn: (id: string) => api.delete(`/datasets/${id}`),
    onSuccess: () => {
      toast.push('Dataset deleted', 'success')
      queryClient.invalidateQueries({ queryKey: ['datasets'] })
    },
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  const removeMany = useMutation({
    mutationFn: (body: { ids?: string[]; project_id?: string }) =>
      api.post<{ detail: string }>('/datasets/delete', body),
    onSuccess: (result) => {
      toast.push(result.detail, 'success')
      setSelected(new Set())
      queryClient.invalidateQueries({ queryKey: ['datasets'] })
      queryClient.invalidateQueries({ queryKey: ['projects'] })
    },
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  return (
    <>
      <PageHeader
        title="Datasets"
        description="Survey data imported from files or pulled from a Survey Solutions server."
        actions={
          can('manager') && (
            <button className="btn-primary" onClick={() => setUploadInto('')}>
              Upload data
            </button>
          )
        }
      />

      {totals.count > 0 && (
        <div className="mb-5 flex flex-wrap items-end gap-x-10 gap-y-3 border-b border-ink-200 pb-4 dark:border-dark-200">
          <Figure label="Projects" value={formatNumber(grouped.length)} />
          <Figure label="Datasets" value={formatNumber(totals.count)} />
          <Figure label="On disk" value={formatBytes(totals.bytes)} />
          {totals.unready > 0 && (
            <Figure
              label="Not ready"
              value={formatNumber(totals.unready)}
              hint="still importing, or failed"
            />
          )}
          {totals.updated && (
            <Figure label="Last import" value={relativeTime(totals.updated)} />
          )}
        </div>
      )}

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <input
          className="input max-w-xs"
          placeholder="Search datasets…"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
        {hiddenParadata > 0 && (
          <label className="flex items-center gap-2 text-sm text-ink-600">
            <input
              type="checkbox"
              checked={showParadata}
              onChange={(event) => setShowParadata(event.target.checked)}
            />
            Show paradata ({hiddenParadata})
          </label>
        )}
      </div>

      {selected.size > 0 && (
        <div className="mb-4 flex flex-wrap items-center gap-3 rounded-card border border-brand-200 bg-brand-50 px-4 py-2.5 text-sm">
          <span className="font-medium text-brand-900">
            {selected.size} dataset{selected.size === 1 ? '' : 's'} selected
          </span>
          <button className="btn-ghost btn-sm text-ink-600" onClick={() => setSelected(new Set())}>
            Clear
          </button>
          <button
            className="btn-ghost btn-sm ml-auto text-red-600"
            onClick={() => {
              if (
                confirm(
                  `Delete ${selected.size} dataset(s)? Charts, indicators and merges built on ` +
                    'them will stop working.',
                )
              )
                removeMany.mutate({ ids: [...selected] })
            }}
          >
            Delete selected
          </button>
        </div>
      )}

      {datasets.isLoading ? (
        <Loading />
      ) : datasets.error ? (
        <ErrorNote error={datasets.error} retry={datasets.refetch} />
      ) : !datasets.data?.items.length ? (
        <Card>
          <EmptyState
            icon="▤"
            title={search ? 'No datasets match your search' : 'No datasets yet'}
            description={
              search
                ? 'Try a different search term.'
                : 'Upload a Stata (.dta), SPSS, CSV or Excel file, or connect a Survey Solutions server to import automatically.'
            }
            action={
              can('manager') && !search ? (
                <button className="btn-primary btn-sm" onClick={() => setUploadInto('')}>
                  Upload your first dataset
                </button>
              ) : undefined
            }
          />
        </Card>
      ) : (
        <div className="space-y-8">
          {grouped.map((group) => (
            <section key={group.id || 'shared'}>
              <header className="mb-3 border-b border-ink-200 pb-2.5 dark:border-dark-200">
                <div className="flex flex-wrap items-center gap-3">
                <button
                  className="text-ink-400 hover:text-ink-700"
                  onClick={() => toggleGroup(group.id)}
                  aria-expanded={!collapsed[group.id]}
                  title={collapsed[group.id] ? 'Show these datasets' : 'Hide these datasets'}
                >
                  {collapsed[group.id] ? '▸' : '▾'}
                </button>
                <h2 className="text-sm font-semibold text-ink-800 dark:text-dark-800">
                  {group.id ? (
                    <Link to={`/projects/${group.id}`} className="hover:text-brand-700">
                      {group.name}
                    </Link>
                  ) : (
                    group.name
                  )}
                </h2>

                {/* Destructive actions sit to the right, away from the
                    project's own name. 'Delete all' beside a title is a
                    mis-click waiting to happen, and it is not what the
                    row is for. */}
                <div className="ml-auto flex flex-wrap items-center gap-1">
                {can('manager') && group.datasets.length > 0 && (
                  <>
                    <button
                      className="btn-ghost btn-sm text-ink-500"
                      onClick={() => {
                        const ids = group.datasets.map((d) => d.id)
                        const next = new Set(selected)
                        const allChosen = ids.every((id) => next.has(id))
                        for (const id of ids) {
                          if (allChosen) next.delete(id)
                          else next.add(id)
                        }
                        setSelected(next)
                      }}
                    >
                      {group.datasets.every((d) => selected.has(d.id))
                        ? 'Clear selection'
                        : 'Select all'}
                    </button>
                    <button
                      className="btn-ghost btn-sm text-red-600"
                      onClick={() => {
                        if (
                          confirm(
                            `Delete all ${group.datasets.length} dataset(s) in ${group.name}? ` +
                              'Charts, indicators and merges built on them will stop working.',
                          )
                        )
                          removeMany.mutate({ project_id: group.id })
                      }}
                    >
                      Delete all
                    </button>
                  </>
                )}

                {can('manager') && (
                  <button
                    className="btn-ghost btn-sm"
                    onClick={() => setUploadInto(group.id)}
                  >
                    + Upload into {group.id ? 'this project' : 'the shared area'}
                  </button>
                )}
                </div>
                </div>
                <GroupSummary datasets={group.datasets} />
              </header>

              {/* The header line already says an empty project is empty, so
                  there is nothing to repeat here. */}
              {collapsed[group.id] || !group.datasets.length ? null : (
                <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                  {group.datasets.map((dataset) => (
                    <DatasetCard
                      key={dataset.id}
                      dataset={dataset}
                      canManage={can('manager')}
                      selected={selected.has(dataset.id)}
                      onSelect={can('manager') ? () => toggleOne(dataset.id) : undefined}
                      onDelete={() => {
                        if (
                          confirm(
                            `Delete "${dataset.name}"? Charts and indicators built on it will stop working.`,
                          )
                        )
                          remove.mutate(dataset.id)
                      }}
                    />
                  ))}
                </div>
              )}
            </section>
          ))}
        </div>
      )}

      {/* Reference geography, under the data it describes. A frame is not a
          dataset - nothing is tabulated from it - but it is uploaded here for
          the same reason it is read here: it is what the data is checked
          against. */}
      <BoundaryLibrary />

      <UploadModal
        open={uploadInto !== null}
        projectId={uploadInto ?? ''}
        onClose={() => setUploadInto(null)}
      />
    </>
  )
}

/** One figure in the masthead. A number and what it counts, nothing drawn. */
function Figure({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div>
      <p className="text-[11px] font-semibold uppercase tracking-wide text-ink-500 dark:text-dark-500">
        {label}
      </p>
      <p className="mt-0.5 text-2xl font-semibold tabular-nums text-ink-900 dark:text-dark-900">
        {value}
      </p>
      {hint && <p className="text-[11px] text-ink-400 dark:text-dark-400">{hint}</p>}
    </div>
  )
}

/**
 * What a project holds, on one line, whether or not it is expanded.
 *
 * Text, not a bar. The only measure worth comparing projects on here would be
 * one somebody acts on, and neither row count nor file size is that: nobody
 * reorders their week on learning one project holds more rows than another.
 * What does get acted on is on this line - how many datasets, when the project
 * last received anything, and whether something in it failed to import.
 */
function GroupSummary({ datasets }: { datasets: Dataset[] }) {
  const totals = summarise(datasets)
  if (!totals.count) {
    return <p className="mt-1 pl-6 text-xs text-ink-400 dark:text-dark-400">Nothing here yet</p>
  }
  const parts = [
    `${formatNumber(totals.count)} dataset${totals.count === 1 ? '' : 's'}`,
    formatBytes(totals.bytes),
    totals.updated ? `updated ${relativeTime(totals.updated)}` : null,
  ].filter(Boolean)

  return (
    <div className="mt-1 flex flex-wrap items-center gap-x-2.5 gap-y-1 pl-6">
      <span className="text-xs text-ink-500 dark:text-dark-500">{parts.join(' · ')}</span>
      {/* The one thing on this line anybody has to do something about. */}
      {totals.unready > 0 && (
        <Badge tone="danger">
          {formatNumber(totals.unready)} not ready
        </Badge>
      )}
    </div>
  )
}

/**
 * One dataset in the list. Extracted so each project section renders the same
 * card rather than the page repeating it per group.
 */
function DatasetCard({
  dataset,
  canManage,
  selected = false,
  onSelect,
  onDelete,
}: {
  dataset: Dataset
  canManage: boolean
  /** Whether this one is in the current selection, for deleting several. */
  selected?: boolean
  onSelect?: () => void
  onDelete: () => void
}) {
  return (
    <article className={`card flex flex-col p-5 ${selected ? 'ring-2 ring-brand-400' : ''}`}>
      <div className="flex items-start justify-between gap-2">
        {onSelect && (
          <input
            type="checkbox"
            className="mt-1.5"
            checked={selected}
            onChange={onSelect}
            aria-label={`Select ${dataset.name}`}
          />
        )}
        <Link
          to={`/datasets/${dataset.id}`}
          className="min-w-0 flex-1 text-base font-semibold text-ink-900 hover:text-brand-700"
        >
          {dataset.name}
        </Link>
        <StatusBadge status={dataset.status} />
      </div>

      {dataset.description && (
        <p className="mt-1 line-clamp-2 text-sm text-ink-500">{dataset.description}</p>
      )}

      <dl className="mt-4 grid grid-cols-2 gap-2 text-center">
        <div>
          <dt className="text-[11px] uppercase text-ink-400">Columns</dt>
          <dd className="text-sm font-semibold tabular-nums">{dataset.column_count}</dd>
        </div>
        <div>
          <dt className="text-[11px] uppercase text-ink-400">Size</dt>
          <dd className="text-sm font-semibold">{formatBytes(dataset.file_size)}</dd>
        </div>
      </dl>

      {dataset.status === 'failed' && dataset.error && (
        <p className="mt-3 rounded border border-red-200 bg-red-50 px-2 py-1.5 text-xs text-red-700">
          {dataset.error}
        </p>
      )}

      <div className="mt-4 flex flex-wrap items-center gap-1.5">
        {dataset.source === 'survey_solutions' && (
          <Badge tone="info" icon="⇄">
            Survey Solutions
          </Badge>
        )}
        {dataset.source === 'derived' && <Badge tone="info">merged</Badge>}
        {dataset.tags.map((tag) => (
          <Badge key={tag}>{tag}</Badge>
        ))}
      </div>

      <div className="mt-4 flex items-center justify-between border-t border-ink-100 pt-3">
        <span className="text-xs text-ink-400">
          Updated {relativeTime(dataset.refreshed_at ?? dataset.updated_at)}
        </span>
        <div className="flex gap-1">
          <Link to={`/explore?dataset=${dataset.id}`} className="btn-ghost btn-sm">
            Analyse
          </Link>
          {canManage && (
            <button className="btn-ghost btn-sm text-red-600" onClick={onDelete}>
              Delete
            </button>
          )}
        </div>
      </div>
    </article>
  )
}

function StatusBadge({ status }: { status: Dataset['status'] }) {
  if (status === 'ready') return <Badge tone="success">Ready</Badge>
  if (status === 'failed') return <Badge tone="danger" icon="⚠">Failed</Badge>
  return <Badge tone="warning" icon="◷">{status}</Badge>
}


// Uploads above this are imported by the worker, so the answer to the POST is
// a job rather than a dataset. It matches the server's own threshold; being
// wrong either way only changes which word the button shows.
const BACKGROUND_BYTES = 48 * 1024 * 1024

function isJob(body: Dataset | ArchiveImport | Job | Review): body is Job {
  return 'job_type' in body
}

/** Watch a queued import to its end, and answer as the inline path would.
 *
 *  The worker records the same report the request used to return, so the modal
 *  that shows what an archive did does not need to know which path ran it.
 */
async function waitForImport(job: Job): Promise<Dataset | ArchiveImport | Review> {
  const deadline = Date.now() + 2 * 60 * 60 * 1000
  for (;;) {
    if (job.status === 'success') return job.result as unknown as ArchiveImport
    if (job.status === 'failed' || job.status === 'cancelled') {
      throw new Error(job.error || 'The import failed.')
    }
    if (Date.now() > deadline) {
      throw new Error(
        'The import is still running. Watch it under Administration \u2192 Background jobs.',
      )
    }
    await new Promise((resolve) => setTimeout(resolve, 2000))
    job = await api.get<Job>(`/system/jobs/${job.id}`)
  }
}

function UploadModal({
  open,
  projectId: initialProject,
  onClose,
}: {
  open: boolean
  /** Preselected from the section the upload was started in. */
  projectId: string
  onClose: () => void
}) {
  const toast = useToast()
  const queryClient = useQueryClient()
  const fileRef = useRef<HTMLInputElement>(null)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [tags, setTags] = useState('')
  const [combineAll, setCombineAll] = useState(false)
  const [projectId, setProjectId] = useState(initialProject)
  const [mode, setMode] = useState<'replace' | 'append'>('replace')
  const [isZip, setIsZip] = useState(false)
  /** The files to import, in the order they will be imported. */
  const [chosen, setChosen] = useState<{ file: File; label: string }[]>([])
  const [versionColumn, setVersionColumn] = useState('version')
  const [busy, setBusy] = useState(false)
  const [stage, setStage] = useState<'' | 'uploading' | 'importing'>('')
  const [sent, setSent] = useState<UploadProgress | null>(null)
  const info = useQuery({
    queryKey: ['platform-info'],
    queryFn: () => api.get<{ max_upload_mb: number }>('/system/info'),
    staleTime: 5 * 60 * 1000,
  })
  const [error, setError] = useState('')
  const [result, setResult] = useState<ArchiveImport | null>(null)
  const [review, setReview] = useState<Review | null>(null)

  // The modal is kept mounted, so a fresh open from another section has to
  // move the selection rather than keep the last one.
  useEffect(() => {
    if (open) setProjectId(initialProject)
  }, [open, initialProject])

  const submit = async () => {
    if (!chosen.length) {
      setError('Choose a file to upload.')
      return
    }
    // Checked here as well as on the server, because the alternative is
    // spending twenty minutes uploading a file that was always going to be
    // refused. The limit comes from the server, so the two cannot drift.
    // The two multi-file operations are different, and the server refuses a
    // mixture rather than guessing. Saying so here saves sending the files
    // first and being told afterwards.
    const zips = chosen.filter((item) => item.file.name.toLowerCase().endsWith('.zip')).length
    if (zips && zips !== chosen.length) {
      setError(
        'Choose either several .zip archives, which are appended together, or ' +
          'several data files, which each become their own dataset. Not a mixture.',
      )
      return
    }
    const limitMb = info.data?.max_upload_mb ?? 0
    const total = chosen.reduce((sum, item) => sum + item.file.size, 0)
    if (limitMb > 0 && total > limitMb * 1024 * 1024) {
      setError(
        `${chosen.length > 1 ? 'These files come to' : `${chosen[0].file.name} is`} ` +
          `${formatBytes(total)} and the limit is ${formatBytes(limitMb * 1024 * 1024)}. ` +
          'Raise MAX_UPLOAD_MB in .env and restart, or upload them one at a time.',
      )
      return
    }
    setBusy(true)
    setError('')
    setStage(total > BACKGROUND_BYTES ? 'uploading' : 'importing')
    const form = new FormData()
    for (const item of chosen) form.append('file', item.file)
    const first = chosen[0].file
    // A name belongs to one dataset. Several data files each become their own,
    // named after the file, so there is nothing here for a name to apply to.
    const several = chosen.length > 1 && !isZip
    form.append(
      'name',
      several ? '' : name || (isZip ? '' : first.name.replace(/\.[^.]+$/, '')),
    )
    if (isZip && (chosen.length > 1 || versionColumn.trim())) {
      // Parallel to the files, in the order they will be imported.
      form.append('labels', JSON.stringify(chosen.map((item) => item.label)))
      form.append('version_column', versionColumn.trim())
    }
    form.append('description', description)
    form.append('tags', tags)
    form.append('combine_all', String(combineAll))
    form.append('project_id', projectId)
    form.append('mode', mode)
    form.append('review', 'true')
    try {
      let body = await api.upload<Dataset | ArchiveImport | Job | Review>(
        '/datasets/upload',
        form,
        (progress) => {
          setSent(progress)
          // The transfer is done and the server is reading it, which is a
          // different wait and deserves a different word. The bar would
          // otherwise sit at 100% for as long again.
          if (progress.sent >= progress.total) setStage('importing')
        },
      )
      if (isJob(body)) {
        // Too big to read inside the request, so the worker has it and this
        // watches the job it left behind.
        setStage('importing')
        body = await waitForImport(body)
      }
      if ("review" in body && body.review) { setReview(body as Review); return }
      queryClient.invalidateQueries({ queryKey: ['datasets'] })
      queryClient.invalidateQueries({ queryKey: ['projects'] })

      if ('datasets' in body) {
        // An archive produces several datasets and may have something important
        // to say about them - that rows are double counted, most of all. A toast
        // disappears; this stays until the user closes it.
        setResult(body)
        return
      }
      toast.push(
        `Imported ${formatNumber((body as Dataset).row_count)} rows and ${(body as Dataset).column_count} variables`,
        'success',
      )
      setName('')
      setDescription('')
      setTags('')
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Upload failed')
    } finally {
      setBusy(false)
      setStage('')
      setSent(null)
    }
  }

  const close = () => {
    setResult(null)
    onClose()
  }

  if (result) {
    return (
      <Modal
        open={open}
        onClose={close}
        title="Import finished"
        footer={
          <button className="btn-primary" onClick={close}>
            Done
          </button>
        }
      >
        <ArchiveResult result={result} />
      </Modal>
    )
  }

  if (review) return <ImportReview review={review} onClose={() => setReview(null)} onAccepted={(body) => {
    setReview(null); setResult(body)
    queryClient.invalidateQueries({ queryKey: ['datasets'] })
    queryClient.invalidateQueries({ queryKey: ['projects'] })
  }} />

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Upload survey data"
      footer={
        <>
          <button className="btn-secondary" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button className="btn-primary" onClick={submit} disabled={busy}>
            {busy && <Spinner className="h-4 w-4 text-white" />}
            {stage === 'uploading'
              ? 'Uploading\u2026'
              : stage === 'importing'
                ? 'Importing\u2026'
                : 'Upload and review'}
          </button>
        </>
      }
    >
      {sent && <UploadBar progress={sent} />}
      {error && (
        <div className="mb-4 rounded-card border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
          {error}
        </div>
      )}
      <ProjectPicker value={projectId} onChange={setProjectId} />

      <Field
        label="Data file"
        hint="Stata (.dta), SPSS (.sav), CSV, tab-delimited, Excel, or .zip archives. Choose several data files to load each as its own dataset, or several archives to append them together."
      >
        <input
          ref={fileRef}
          type="file"
          multiple
          accept={ACCEPTED}
          className="input py-1.5"
          onChange={(event) => {
            const files = Array.from(event.target.files ?? [])
            setIsZip(files.some((f) => f.name.toLowerCase().endsWith('.zip')))
            setChosen(
              files.map((file) => ({
                file,
                // The version number in the file name is the usual answer, so
                // it is offered rather than demanded.
                label: file.name.replace(/\.[^.]+$/, '').match(/(\d+)\D*$/)?.[1] ?? '',
              })),
            )
          }}
        />
      </Field>

      {chosen.length > 1 && !isZip && (
        <div className="mb-4 rounded-card border border-brand-200 bg-brand-50 p-3">
          {/* Nothing is appended and nothing is ordered here, so this panel
              lists the files and stops. The order buttons and the version
              column below belong to appending archives, and offering them
              would describe an operation that is not about to happen. */}
          <p className="text-sm text-brand-900">
            Each of these becomes <strong>its own dataset</strong>, named after
            its file. That is what a census round looks like: the interview
            level, each roster and the paradata are different tables, so they
            are not appended onto one another.
          </p>
          <ul className="mt-2 space-y-1.5">
            {chosen.map((item) => (
              <li key={item.file.name} className="flex items-center gap-2 text-sm">
                <span className="min-w-0 flex-1 truncate text-brand-900">
                  {item.file.name}
                </span>
                <span className="shrink-0 text-xs text-brand-800/70">
                  {formatBytes(item.file.size)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {chosen.length > 1 && isZip && (
        <div className="mb-4 rounded-card border border-brand-200 bg-brand-50 p-3">
          <p className="text-sm text-brand-900">
            These are imported <strong>in this order</strong>: the first under the
            choice below, the rest appended onto what it produces. Each file
            inside them meets its own kind - the interview level with the
            interview level, each roster with its roster, the paradata with the
            paradata.
          </p>
          <ol className="mt-2 space-y-1.5">
            {chosen.map((item, index) => (
              <li key={item.file.name} className="flex items-center gap-2 text-sm">
                <span className="w-5 shrink-0 text-right text-xs text-brand-800/70">
                  {index + 1}.
                </span>
                <button
                  className="btn-ghost btn-sm shrink-0 px-1 py-0"
                  title="Import this one earlier"
                  disabled={index === 0}
                  onClick={() => {
                    const next = [...chosen]
                    ;[next[index - 1], next[index]] = [next[index], next[index - 1]]
                    setChosen(next)
                  }}
                >
                  ▲
                </button>
                <span className="min-w-0 flex-1 truncate text-brand-900">
                  {item.file.name}
                </span>
                <span className="shrink-0 text-xs text-brand-800/70">
                  {formatBytes(item.file.size)}
                </span>
                <input
                  className="input w-24 py-1 text-xs"
                  placeholder="version"
                  value={item.label}
                  onChange={(event) =>
                    setChosen(
                      chosen.map((one, i) =>
                        i === index ? { ...one, label: event.target.value } : one,
                      ),
                    )
                  }
                />
              </li>
            ))}
          </ol>
          <div className="mt-3">
            <label className="label">Record which file each row came from in</label>
            <input
              className="input py-1 text-xs"
              placeholder="version"
              value={versionColumn}
              onChange={(event) => setVersionColumn(event.target.value)}
            />
            <p className="mt-1 text-xs text-brand-800/80">
              A variable holding each file&rsquo;s label above, so the versions stay
              tellable apart once they are in one dataset. Leave it empty to skip.
              A variable of that name already in the data is left alone.
            </p>
          </div>
        </div>
      )}

      {isZip && (
        <div className="mb-4 rounded-card border border-brand-200 bg-brand-50 p-3">
          <p className="text-sm text-brand-900">
            Each file inside becomes its own dataset, because an export holds one
            file per roster level - the interview, the household members, the
            people abroad - and those are different tables.
          </p>
          <p className="mt-1.5 text-sm text-brand-900">
            Upload a later round&rsquo;s archive and each of its files is{' '}
            <strong>appended</strong> to the dataset already holding that file name.
            A <code className="text-xs">source_file</code> column records which
            archive each row arrived in.
          </p>
          <div className="mt-3">
            <p className="text-xs font-semibold uppercase tracking-wide text-brand-900">
              When a dataset already holds that file
            </p>
            <label className="mt-1 flex items-start gap-2 text-sm text-brand-900">
              <input
                type="radio"
                className="mt-0.5"
                checked={mode === 'replace'}
                onChange={() => setMode('replace')}
              />
              <span>
                Replace its data
                <span className="block text-xs text-brand-800/80">
                  The dataset keeps its identity, so relationships, charts,
                  indicators and quality checks built on it go on working. Use
                  this for a fresh export of everything collected so far.
                </span>
              </span>
            </label>
            <label className="mt-1.5 flex items-start gap-2 text-sm text-brand-900">
              <input
                type="radio"
                className="mt-0.5"
                checked={mode === 'append'}
                onChange={() => setMode('append')}
              />
              <span>
                Add its rows to what is there
                <span className="block text-xs text-brand-800/80">
                  For an export that contains only what is new. Appending a
                  cumulative export counts the same interviews twice.
                </span>
              </span>
            </label>
          </div>

          <label className="mt-3 flex items-start gap-2 text-sm text-brand-900">
            <input
              type="checkbox"
              className="mt-0.5"
              checked={combineAll}
              onChange={(event) => setCombineAll(event.target.checked)}
            />
            <span>
              Combine every file, even where columns differ
              <span className="block text-xs text-brand-700">
                Leave this off for a Survey Solutions export, which holds one file per
                roster level rather than several rounds. Only files sharing a column set
                are appended.
              </span>
            </span>
          </label>
        </div>
      )}
      <Field
        label="Name"
        hint={
          isZip
            ? "Optional prefix for the datasets this archive creates, for telling two surveys apart in one project."
            : "Defaults to the file name"
        }
      >
        <input className="input" value={name} onChange={(e) => setName(e.target.value)} />
      </Field>
      <Field label="Description">
        <textarea
          className="input"
          rows={2}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
      </Field>
      <Field label="Tags" hint="Comma separated, e.g. round1, baseline">
        <input className="input" value={tags} onChange={(e) => setTags(e.target.value)} />
      </Field>
    </Modal>
  )
}


/**
 * What one archive upload did, per file inside it.
 *
 * An export holds one file per roster level, so this is several datasets rather
 * than one - and whether each was created or appended to is the thing worth
 * seeing. Warnings are shown first and cannot be dismissed by a timer, because
 * the one that matters says the data is counted twice.
 */
function ArchiveResult({ result }: { result: ArchiveImport }) {
  return (
    <div className="space-y-4">
      {result.warnings.map((warning) => (
        <p
          key={warning}
          className="rounded-card border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900"
        >
          ⚠ {warning}
        </p>
      ))}

      <p className="text-sm text-ink-600">
        {formatNumber(result.rows)} rows across {result.datasets.length} dataset
        {result.datasets.length === 1 ? '' : 's'}.
      </p>

      {[
        ['Created', result.created] as const,
        ['Replaced', result.replaced] as const,
        ['Appended to existing datasets', result.appended] as const,
        ['Skipped', result.skipped] as const,
      ]
        .filter(([, lines]) => lines.length > 0)
        .map(([label, lines]) => (
          <div key={label}>
            <p className="text-xs font-semibold uppercase tracking-wide text-ink-500">
              {label}
            </p>
            <ul className="mt-1 space-y-1">
              {lines.map((line) => (
                <li key={line} className="font-mono text-xs text-ink-700">
                  {line}
                </li>
              ))}
            </ul>
          </div>
        ))}
    </div>
  )
}
