/**
 * Target sets: a survey's quotas, kept as lists of their own.
 *
 * A census carries a quota per enumeration area and two thousand of them. The
 * list is prepared before fieldwork, in a spreadsheet, by somebody who is not
 * watching a dashboard, and it is read by several indicators at once -
 * households enumerated, questionnaires received, interviews verified, all
 * against the same area quotas.
 *
 * So the list lives here rather than inside one indicator: pasted in once,
 * checked against the values the data actually holds, and pointed at by
 * whichever indicators are judged by it.
 */
import { useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { useAuth } from '@/hooks/useAuth'
import { useDialog } from '@/hooks/useDialog'
import { useToast } from '@/hooks/useToast'
import { by } from '@/lib/collections'
import { formatNumber } from '@/lib/format'
import { matchAgainst, parsePasted } from '@/lib/targets'
import type { Dataset, Variable } from '@/lib/types'
import { Card, EmptyState, Field, Modal, Spinner } from '@/components/ui'

interface TargetSetSummary {
  id: string
  name: string
  description: string
  dataset_id: string
  dataset_name: string
  variable: string
  categories: number
  total: number
  used_by: number
  updated_at: string | null
}

interface TargetSet {
  id: string
  name: string
  description: string
  dataset_id: string
  variable: string
  targets: Record<string, number>
}

/** How many rows the table draws at once. Two thousand <input>s is a stall. */
const SHOWN = 100

export default function Targets() {
  const { can } = useAuth()
  const toast = useToast()
  const ask = useDialog()
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState<TargetSetSummary | 'new' | null>(null)

  const sets = useQuery({
    queryKey: ['target-sets'],
    queryFn: () => api.get<TargetSetSummary[]>('/monitoring/target-sets'),
  })

  const remove = useMutation({
    mutationFn: (one: TargetSetSummary) =>
      api.delete<{ detail: string }>(`/monitoring/target-sets/${one.id}`),
    onSuccess: (answer) => {
      toast.push(answer.detail, 'success')
      queryClient.invalidateQueries({ queryKey: ['target-sets'] })
    },
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  return (
    <div>
      <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-ink-900 dark:text-dark-900">Targets</h1>
          <p className="mt-1 text-sm text-ink-500 dark:text-dark-500">
            A quota per group - per province, per enumeration area, per team - kept in
            one place and read by the indicators that are judged against it.
          </p>
        </div>
        {can('manager') && (
          <button className="btn-primary" onClick={() => setEditing('new')}>
            New target set
          </button>
        )}
      </div>

      {sets.isLoading && <Spinner className="h-5 w-5" />}

      {sets.data && !sets.data.length && (
        <EmptyState
          title="No target sets yet"
          description="Paste a list of groups and their quotas, and any indicator broken down by that variable can be judged against it."
        />
      )}

      <div className="grid gap-3 md:grid-cols-2">
        {(sets.data ?? []).map((one) => (
          <Card key={one.id} bodyClassName="p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <h3 className="text-sm font-semibold text-ink-800 dark:text-dark-800">
                  {one.name}
                </h3>
                <p className="mt-0.5 text-xs text-ink-500 dark:text-dark-500">
                  {one.dataset_name}
                  {one.variable ? ` · ${one.variable}` : ''}
                </p>
                {one.description && (
                  <p className="mt-1.5 text-sm text-ink-600 dark:text-dark-600">
                    {one.description}
                  </p>
                )}
                <p className="mt-2 text-sm text-ink-700 dark:text-dark-700">
                  <strong className="font-semibold">{formatNumber(one.categories)}</strong>{' '}
                  {one.categories === 1 ? 'group' : 'groups'}, adding up to{' '}
                  <strong className="font-semibold">{formatNumber(one.total)}</strong>
                </p>
                <p className="mt-0.5 text-xs text-ink-400 dark:text-dark-400">
                  {one.used_by
                    ? `Read by ${one.used_by} indicator${one.used_by === 1 ? '' : 's'}`
                    : 'Not used by any indicator yet'}
                </p>
              </div>
              {can('manager') && (
                <div className="flex shrink-0 gap-1">
                  <button className="btn-secondary btn-sm" onClick={() => setEditing(one)}>
                    Edit
                  </button>
                  <button
                    className="btn-ghost btn-sm text-red-600"
                    onClick={async () => {
                      const sure = await ask.confirm({
                        title: `Delete "${one.name}"?`,
                        message: one.used_by
                          ? `${one.used_by} indicator(s) read this set. They keep working: each goes back to whatever quotas it carries itself, which for most is none.`
                          : 'The list goes. Nothing else changes.',
                        confirmLabel: 'Delete',
                        tone: 'danger',
                      })
                      if (sure) remove.mutate(one)
                    }}
                  >
                    Delete
                  </button>
                </div>
              )}
            </div>
          </Card>
        ))}
      </div>

      {editing && (
        <TargetSetModal
          set={editing === 'new' ? undefined : editing}
          onClose={() => setEditing(null)}
        />
      )}
    </div>
  )
}

function TargetSetModal({
  set,
  onClose,
}: {
  set?: TargetSetSummary
  onClose: () => void
}) {
  const toast = useToast()
  const queryClient = useQueryClient()
  const editing = Boolean(set)

  const existing = useQuery({
    queryKey: ['target-set', set?.id],
    queryFn: () => api.get<TargetSet>(`/monitoring/target-sets/${set!.id}`),
    enabled: Boolean(set?.id),
  })

  const [name, setName] = useState(set?.name ?? '')
  const [description, setDescription] = useState(set?.description ?? '')
  const [datasetId, setDatasetId] = useState(set?.dataset_id ?? '')
  const [variable, setVariable] = useState(set?.variable ?? '')
  const [targets, setTargets] = useState<Record<string, number>>({})
  const [loaded, setLoaded] = useState(false)
  const [search, setSearch] = useState('')
  const [paste, setPaste] = useState('')
  const [report, setReport] = useState('')
  const pasteBox = useRef<HTMLTextAreaElement>(null)

  // The stored rows arrive after the dialog opens; taken once, so typing is
  // not undone by a refetch.
  if (existing.data && !loaded) {
    setTargets(existing.data.targets ?? {})
    setLoaded(true)
  }

  const datasets = useQuery({
    queryKey: ['datasets', 'ready'],
    queryFn: () => api.getAll<Dataset>('/datasets?status=ready'),
  })
  const dataset = useQuery({
    queryKey: ['dataset', datasetId],
    queryFn: () => api.get<Dataset>(`/datasets/${datasetId}`),
    enabled: Boolean(datasetId),
  })
  const variables: Variable[] = dataset.data?.variables ?? []

  // Every value the variable actually holds, so a pasted list can be checked
  // against it. A census variable has thousands, which is why this asks for
  // more than a filter dropdown would.
  const values = useQuery({
    queryKey: ['values', datasetId, variable, 'all'],
    queryFn: () =>
      api.get<{ value: string; label: string }[]>(
        `/datasets/${datasetId}/variables/${encodeURIComponent(variable)}/values?limit=20000`,
      ),
    enabled: Boolean(datasetId && variable),
  })
  const known = useMemo(
    // The label rather than the code: a breakdown reports a labelled
    // variable by its label, so that is the spelling a quota has to be
    // keyed by to be found.
    () => (values.data ?? []).map((one) => String(one.label || one.value)),
    [values.data],
  )

  const rows = useMemo(() => {
    const listed = Object.entries(targets).map(([category, target]) => ({ category, target }))
    listed.sort(by((row) => row.category))
    const needle = search.trim().toLowerCase()
    return needle
      ? listed.filter((row) => row.category.toLowerCase().includes(needle))
      : listed
  }, [targets, search])

  const total = useMemo(
    () => Object.values(targets).reduce((sum, value) => sum + (Number(value) || 0), 0),
    [targets],
  )

  const save = useMutation({
    mutationFn: () => {
      const body = { name, description, variable, targets }
      return set
        ? api.patch(`/monitoring/target-sets/${set.id}`, body)
        : api.post('/monitoring/target-sets', { ...body, dataset_id: datasetId })
    },
    onSuccess: () => {
      toast.push(editing ? 'Target set saved' : 'Target set created', 'success')
      queryClient.invalidateQueries({ queryKey: ['target-sets'] })
      queryClient.invalidateQueries({ queryKey: ['indicators'] })
      onClose()
    },
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  /** Read what was pasted, and say what it did before anything is saved. */
  const apply = () => {
    // A single column of numbers lands on the categories in the order the data
    // holds them, which is the order a spreadsheet of them was almost
    // certainly sorted in.
    const order = known.length ? [...known].sort(by((one) => one)) : []
    const parsed = parsePasted(paste, order)
    if (!parsed.rows.length) {
      setReport(
        order.length
          ? 'Nothing in that paste looked like a quota. A pair per line - "EA0508,346" - or one column of numbers for the groups below.'
          : 'Nothing read. Choose the dataset and variable first: a single column of numbers needs the list of groups to land on.',
      )
      return
    }
    const next: Record<string, number> = {}
    for (const row of parsed.rows) next[row.category] = row.target
    setTargets(next)

    const found = matchAgainst(Object.keys(next), known)
    const said: string[] = [
      `${formatNumber(parsed.rows.length)} ${parsed.rows.length === 1 ? 'quota' : 'quotas'} read`,
    ]
    if (parsed.header) said.push(`header "${parsed.header}" ignored`)
    if (parsed.skipped.length) said.push(`${parsed.skipped.length} line(s) had no number`)
    if (known.length) {
      said.push(`${formatNumber(found.matched.length)} matched a value in the data`)
      if (found.unknown.length) {
        said.push(
          `${formatNumber(found.unknown.length)} not found there (${found.unknown
            .slice(0, 3)
            .join(', ')}${found.unknown.length > 3 ? ', …' : ''})`,
        )
      }
      if (found.missing.length) {
        said.push(`${formatNumber(found.missing.length)} group(s) in the data got no quota`)
      }
    }
    setReport(said.join('. ') + '.')
    setPaste('')
  }

  return (
    <Modal
      open
      onClose={onClose}
      wide
      title={editing ? `Edit "${set!.name}"` : 'New target set'}
      footer={
        <>
          <button className="btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button
            className="btn-primary"
            onClick={() => save.mutate()}
            disabled={save.isPending || !name || !datasetId}
          >
            {save.isPending && <Spinner className="h-4 w-4 text-white" />}
            {editing ? 'Save changes' : 'Create'}
          </button>
        </>
      }
    >
      <div className="grid gap-x-4 sm:grid-cols-2">
        <Field label="Name">
          <input
            className="input"
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Enumeration area quotas"
          />
        </Field>
        <Field label="Dataset" hint={editing ? 'Fixed: the groups belong to it.' : ''}>
          <select
            className="input"
            value={datasetId}
            disabled={editing}
            onChange={(event) => {
              setDatasetId(event.target.value)
              setVariable('')
            }}
          >
            <option value="">Choose a dataset…</option>
            {(datasets.data?.items ?? []).map((one) => (
              <option key={one.id} value={one.id}>
                {one.name}
              </option>
            ))}
          </select>
        </Field>
      </div>

      <Field
        label="Groups are values of"
        hint="The variable the quotas are keyed by. An indicator broken down by this variable can be judged against this set."
      >
        <select
          className="input"
          value={variable}
          onChange={(event) => setVariable(event.target.value)}
        >
          <option value="">Choose a variable…</option>
          {variables.map((one) => (
            <option key={one.name} value={one.name}>
              {one.label ? `${one.name} - ${one.label}` : one.name}
            </option>
          ))}
        </select>
      </Field>

      <Field label="Description" hint="Optional. Where the quotas came from, and when.">
        <input
          className="input"
          value={description}
          onChange={(event) => setDescription(event.target.value)}
          placeholder="Sample design, March 2026"
        />
      </Field>

      <Field
        label="Paste the quotas"
        hint='A pair per line - "EA0508,346" - from a spreadsheet, a CSV, or tab separated. A single column of numbers works too: they land on the groups in order. Pasting replaces the list.'
      >
        <textarea
          ref={pasteBox}
          className="input h-28 font-mono text-xs"
          value={paste}
          onChange={(event) => setPaste(event.target.value)}
          placeholder={'EA0508,346\nEA0102,437\nEA0902,181'}
        />
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <button className="btn-secondary btn-sm" onClick={apply} disabled={!paste.trim()}>
            Read the paste
          </button>
          {values.isLoading && <span className="text-xs text-ink-400">Reading the groups…</span>}
        </div>
        {report && <p className="mt-2 text-xs text-ink-600 dark:text-dark-600">{report}</p>}
      </Field>

      <Field
        label={`The list: ${formatNumber(Object.keys(targets).length)} groups, adding up to ${formatNumber(total)}`}
        hint={
          Object.keys(targets).length > SHOWN
            ? `Showing the first ${SHOWN}. Search to find one.`
            : ''
        }
      >
        <input
          className="input mb-2"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Search the groups…"
        />
        <div className="max-h-64 overflow-auto rounded-card border border-ink-200 dark:border-dark-200">
          {!rows.length && (
            <p className="p-3 text-xs text-ink-500 dark:text-dark-500">
              Nothing here yet. Paste a list above.
            </p>
          )}
          {rows.slice(0, SHOWN).map((row) => (
            <label
              key={row.category}
              className="flex items-center gap-2 border-b border-ink-100 px-3 py-1.5 text-sm last:border-0 dark:border-dark-200"
            >
              <span
                className={`min-w-0 flex-1 truncate ${
                  known.length && !known.includes(row.category)
                    ? 'text-amber-700 dark:text-amber-400'
                    : 'text-ink-700 dark:text-dark-700'
                }`}
                title={
                  known.length && !known.includes(row.category)
                    ? 'No such value in the data'
                    : row.category
                }
              >
                {row.category}
              </span>
              <input
                className="input input-sm w-28"
                type="number"
                aria-label={`Quota for ${row.category}`}
                value={row.target}
                onChange={(event) =>
                  setTargets({ ...targets, [row.category]: Number(event.target.value) })
                }
              />
              <button
                className="btn-ghost btn-sm text-red-600"
                aria-label={`Remove ${row.category}`}
                onClick={() => {
                  const next = { ...targets }
                  delete next[row.category]
                  setTargets(next)
                }}
              >
                ✕
              </button>
            </label>
          ))}
        </div>
      </Field>
    </Modal>
  )
}
