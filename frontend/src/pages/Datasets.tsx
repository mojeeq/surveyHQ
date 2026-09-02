import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '@/lib/api'
import { useAuth } from '@/hooks/useAuth'
import { useToast } from '@/hooks/useToast'
import { formatBytes, formatNumber, relativeTime } from '@/lib/format'
import type { Dataset, Page } from '@/lib/types'
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

export default function Datasets() {
  const { can } = useAuth()
  const toast = useToast()
  const queryClient = useQueryClient()
  const [search, setSearch] = useState('')
  const [uploadOpen, setUploadOpen] = useState(false)

  const datasets = useQuery({
    queryKey: ['datasets', search],
    queryFn: () =>
      api.get<Page<Dataset>>(`/datasets?limit=100&search=${encodeURIComponent(search)}`),
  })

  const remove = useMutation({
    mutationFn: (id: string) => api.delete(`/datasets/${id}`),
    onSuccess: () => {
      toast.push('Dataset deleted', 'success')
      queryClient.invalidateQueries({ queryKey: ['datasets'] })
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
            <button className="btn-primary" onClick={() => setUploadOpen(true)}>
              Upload data
            </button>
          )
        }
      />

      <div className="mb-4 flex gap-2">
        <input
          className="input max-w-xs"
          placeholder="Search datasets…"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
      </div>

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
                <button className="btn-primary btn-sm" onClick={() => setUploadOpen(true)}>
                  Upload your first dataset
                </button>
              ) : undefined
            }
          />
        </Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {datasets.data.items.map((dataset) => (
            <article key={dataset.id} className="card flex flex-col p-5">
              <div className="flex items-start justify-between gap-2">
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

              <dl className="mt-4 grid grid-cols-3 gap-2 text-center">
                <div>
                  <dt className="text-[11px] uppercase text-ink-400">Rows</dt>
                  <dd className="text-sm font-semibold tabular-nums">
                    {formatNumber(dataset.row_count)}
                  </dd>
                </div>
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
                  {can('manager') && (
                    <button
                      className="btn-ghost btn-sm text-red-600"
                      onClick={() => {
                        if (
                          confirm(
                            `Delete "${dataset.name}"? Charts and indicators built on it will stop working.`,
                          )
                        )
                          remove.mutate(dataset.id)
                      }}
                    >
                      Delete
                    </button>
                  )}
                </div>
              </div>
            </article>
          ))}
        </div>
      )}

      <UploadModal open={uploadOpen} onClose={() => setUploadOpen(false)} />
    </>
  )
}

function StatusBadge({ status }: { status: Dataset['status'] }) {
  if (status === 'ready') return <Badge tone="success" icon="✓">Ready</Badge>
  if (status === 'failed') return <Badge tone="danger" icon="⚠">Failed</Badge>
  return <Badge tone="warning" icon="◷">{status}</Badge>
}

function UploadModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const toast = useToast()
  const queryClient = useQueryClient()
  const fileRef = useRef<HTMLInputElement>(null)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [tags, setTags] = useState('')
  const [combineAll, setCombineAll] = useState(false)
  const [isZip, setIsZip] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const submit = async () => {
    const file = fileRef.current?.files?.[0]
    if (!file) {
      setError('Choose a file to upload.')
      return
    }
    setBusy(true)
    setError('')
    const form = new FormData()
    form.append('file', file)
    form.append('name', name || file.name.replace(/\.[^.]+$/, ''))
    form.append('description', description)
    form.append('tags', tags)
    form.append('combine_all', String(combineAll))
    try {
      const dataset = await api.upload<Dataset>('/datasets/upload', form)
      const archive = dataset.meta?.archive
      toast.push(
        archive
          ? `Combined ${archive.files_combined.length} file(s) into ${formatNumber(
              dataset.row_count,
            )} rows`
          : `Imported ${formatNumber(dataset.row_count)} rows and ${dataset.column_count} variables`,
        'success',
      )
      if (archive?.files_skipped?.length) {
        toast.push(
          `${archive.files_skipped.length} file(s) had different columns and were not appended`,
          'info',
        )
      }
      queryClient.invalidateQueries({ queryKey: ['datasets'] })
      setName('')
      setDescription('')
      setTags('')
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Upload failed')
    } finally {
      setBusy(false)
    }
  }

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
            Upload and import
          </button>
        </>
      }
    >
      {error && (
        <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
          {error}
        </div>
      )}
      <Field
        label="Data file"
        hint="Stata (.dta), SPSS (.sav), CSV, tab-delimited, Excel, or a .zip of them. Variable and value labels are kept."
      >
        <input
          ref={fileRef}
          type="file"
          accept={ACCEPTED}
          className="input py-1.5"
          onChange={(event) =>
            setIsZip(Boolean(event.target.files?.[0]?.name.toLowerCase().endsWith('.zip')))
          }
        />
      </Field>

      {isZip && (
        <div className="mb-4 rounded-lg border border-brand-200 bg-brand-50 p-3">
          <p className="text-sm text-brand-900">
            The files inside will be appended into one dataset, with a{' '}
            <code className="text-xs">source_file</code> column recording which file each
            row came from.
          </p>
          <label className="mt-2 flex items-start gap-2 text-sm text-brand-900">
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
      <Field label="Name" hint="Defaults to the file name">
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
