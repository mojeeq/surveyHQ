/**
 * Variables brought into this dataset from another one, on the dataset page.
 *
 * A merge makes a new dataset, and the charts already built on this one stay
 * where they were. This brings the other dataset's variables into this one
 * instead: the same dataset, the same rows, and everything built on it still
 * working - now with the new variables to use. They are kept up to date, so
 * a newer export of either side brings them in again.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import { api } from '@/lib/api'
import { formatDate } from '@/lib/format'
import type { Dataset } from '@/lib/types'
import { useToast } from '@/hooks/useToast'
import {
  describeLink,
  KEY_MATCHES,
  offers,
  ownVariables,
  type KeyMatch,
  type LinkCheck,
  type LinkedVariables,
  type LinkKey,
} from '@/lib/linked-variables'
import { Badge, Card, Field, Modal, Spinner } from '@/components/ui'

export function useLinkedVariables(datasetId: string) {
  return useQuery({
    queryKey: ['linked-variables', datasetId],
    queryFn: () => api.get<LinkedVariables[]>(`/datasets/${datasetId}/linked-variables`),
  })
}

function useRefreshAfter(datasetId: string) {
  const queryClient = useQueryClient()
  return () => {
    queryClient.invalidateQueries({ queryKey: ['linked-variables', datasetId] })
    queryClient.invalidateQueries({ queryKey: ['dataset', datasetId] })
    queryClient.invalidateQueries({ queryKey: ['preview', datasetId] })
    queryClient.invalidateQueries({ queryKey: ['datasets'] })
  }
}

/** The links on this dataset, with how each last went and the means to stop one. */
export function LinkedVariablesCard({
  datasetId,
  links,
  canEdit,
}: {
  datasetId: string
  links: LinkedVariables[]
  canEdit: boolean
}) {
  const toast = useToast()
  const refreshAfter = useRefreshAfter(datasetId)
  const [stopping, setStopping] = useState<LinkedVariables | null>(null)

  const refresh = useMutation({
    mutationFn: () => api.post<{ notes: string[] }>(`/datasets/${datasetId}/linked-variables/refresh`),
    onSuccess: (done) => {
      toast.push(done.notes[0] ?? 'Brought in again from the data as it is now', done.notes.length ? 'error' : 'success')
      refreshAfter()
    },
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  const remove = useMutation({
    mutationFn: ({ link, keep }: { link: LinkedVariables; keep: boolean }) =>
      api.delete(`/datasets/${datasetId}/linked-variables/${link.id}?keep_columns=${keep}`),
    onSuccess: (_, { link, keep }) => {
      toast.push(
        keep
          ? `${link.variables.join(', ')} kept as they are, and no longer brought up to date`
          : `${link.variables.join(', ')} removed`,
        'success',
      )
      refreshAfter()
    },
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  if (!links.length) return null

  return (
    <Card
      className="mb-6"
      title="Brought in from other datasets"
      subtitle="Part of this dataset, and brought in again whenever either dataset gets new data"
      actions={
        canEdit && (
          <button className="btn-ghost btn-sm" onClick={() => refresh.mutate()} disabled={refresh.isPending}>
            {refresh.isPending ? 'Bringing in…' : 'Bring in again now'}
          </button>
        )
      }
    >
      <ul className="space-y-2">
        {links.map((link) => (
          <li key={link.id} className="flex flex-wrap items-center gap-2 text-sm">
            <span className="min-w-0 flex-1 text-ink-700 dark:text-dark-700">{describeLink(link)}</span>
            {!link.source_exists ? (
              <Badge tone="danger" icon="!">
                {link.source_name} was deleted
              </Badge>
            ) : link.status.status === 'failed' ? (
              <span className="text-xs text-red-700" title={link.status.message}>
                <Badge tone="danger" icon="!">
                  Not brought in last time
                </Badge>{' '}
                {link.status.message}
              </span>
            ) : link.status.at ? (
              <span className="text-xs text-ink-500">
                {link.status.matched?.toLocaleString()} of {link.status.rows?.toLocaleString()} rows matched ·{' '}
                {formatDate(link.status.at)}
              </span>
            ) : null}
            {canEdit && (
              <button
                className="btn-ghost btn-sm text-red-600"
                onClick={() => setStopping(link)}
                disabled={remove.isPending}
              >
                Stop
              </button>
            )}
          </li>
        ))}
      </ul>
      {stopping && (
        // Three answers, not two: closing the dialog has to do nothing, and a
        // confirm reads a dismissal as its second answer.
        <Modal
          open
          onClose={() => setStopping(null)}
          title={`Stop bringing in ${stopping.variables.join(', ')}?`}
          footer={
            <>
              <button className="btn-secondary" onClick={() => setStopping(null)}>
                Cancel
              </button>
              <button
                className="btn-secondary"
                onClick={() => {
                  remove.mutate({ link: stopping, keep: true })
                  setStopping(null)
                }}
              >
                Keep them as they are
              </button>
              <button
                className="btn-danger"
                onClick={() => {
                  remove.mutate({ link: stopping, keep: false })
                  setStopping(null)
                }}
              >
                Remove them
              </button>
            </>
          }
        >
          <p className="text-sm text-ink-600">
            <strong>Remove them</strong> takes them out of this dataset, as if they had never been brought in.
            Charts and indicators that use them will say the variable is missing.
          </p>
          <p className="mt-2 text-sm text-ink-600">
            <strong>Keep them as they are</strong> leaves the values there now, no longer brought up to date
            from {stopping.source_name}.
          </p>
        </Modal>
      )}
    </Card>
  )
}

/** Choosing another dataset's variables to bring into this one. */
export function BringInModal({
  dataset,
  links,
  onClose,
}: {
  dataset: Dataset
  links: LinkedVariables[]
  onClose: () => void
}) {
  const toast = useToast()
  const refreshAfter = useRefreshAfter(dataset.id)
  const [sourceId, setSourceId] = useState('')
  const [keys, setKeys] = useState<LinkKey[] | null>(null)
  const [keyMatch, setKeyMatch] = useState<KeyMatch>('exact')
  const [chosen, setChosen] = useState<string[]>([])
  const [search, setSearch] = useState('')

  // Its own project's datasets: the ones it can be matched to.
  const candidates = useQuery({
    queryKey: ['datasets', 'linkable', dataset.project_id ?? ''],
    queryFn: () =>
      api.getAll<Dataset>(`/datasets?status=ready${dataset.project_id ? `&project_id=${dataset.project_id}` : ''}`),
  })
  const source = useQuery({
    queryKey: ['dataset', sourceId],
    queryFn: () => api.get<Dataset>(`/datasets/${sourceId}`),
    enabled: Boolean(sourceId),
  })

  const check = useQuery({
    queryKey: ['link-check', dataset.id, sourceId, keys, keyMatch, chosen],
    queryFn: () =>
      api.post<LinkCheck>(`/datasets/${dataset.id}/linked-variables/check`, {
        source_dataset_id: sourceId,
        keys: keys ?? [],
        key_match: keyMatch,
        variables: chosen,
      }),
    enabled: Boolean(sourceId),
  })

  // The keys the server suggests, taken as the starting point once.
  useEffect(() => {
    if (keys === null && check.data && check.data.keys.length) {
      setKeys(check.data.keys)
      setKeyMatch(check.data.key_match)
    }
  }, [check.data, keys])

  const chooseSource = (id: string) => {
    setSourceId(id)
    setKeys(null)
    setKeyMatch('exact')
    setChosen([])
  }

  const ours = ownVariables(dataset.variables ?? [], links)
  const theirs = source.data?.variables ?? []
  const offered = useMemo(
    () => offers(theirs, dataset.variables ?? [], keys ?? [], links),
    [theirs, dataset.variables, keys, links],
  )
  const shown = offered.filter(
    (one) =>
      !search ||
      one.name.toLowerCase().includes(search.toLowerCase()) ||
      (one.label ?? '').toLowerCase().includes(search.toLowerCase()),
  )

  const add = useMutation({
    mutationFn: () =>
      api.post<{ message: string }>(`/datasets/${dataset.id}/linked-variables`, {
        source_dataset_id: sourceId,
        keys: keys ?? [],
        key_match: keyMatch,
        variables: chosen,
      }),
    onSuccess: (done) => {
      toast.push(`Brought in ${chosen.join(', ')}. ${done.message}`, 'success')
      refreshAfter()
      onClose()
    },
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  const setKey = (index: number, patch: Partial<LinkKey>) =>
    setKeys((keys ?? []).map((key, i) => (i === index ? { ...key, ...patch } : key)))

  const problem = check.data?.error
  const ready = Boolean(sourceId && keys?.length && chosen.length && !problem && check.data?.match)

  return (
    <Modal
      open
      wide
      onClose={onClose}
      title={`Bring variables into ${dataset.name}`}
      footer={
        <>
          <button className="btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button className="btn-primary" onClick={() => add.mutate()} disabled={!ready || add.isPending}>
            {add.isPending && <Spinner className="h-4 w-4 text-white" />}
            Bring in {chosen.length ? `${chosen.length} variable${chosen.length === 1 ? '' : 's'}` : 'variables'}
          </button>
        </>
      }
    >
      <p className="mb-4 text-sm text-ink-500">
        The variables become part of <strong>{dataset.name}</strong>: the same dataset, the same rows in the same
        order, so its charts, indicators and quality checks keep working. Each row gets the other dataset's values
        where the keys match, and they are brought in again whenever either dataset gets new data.
      </p>

      <Field label="From dataset">
        <select
          className="input"
          aria-label="Dataset to bring variables from"
          value={sourceId}
          onChange={(event) => chooseSource(event.target.value)}
        >
          <option value="">Choose a dataset…</option>
          {(candidates.data?.items ?? [])
            .filter((one) => one.id !== dataset.id)
            .map((one) => (
              <option key={one.id} value={one.id}>
                {one.name} ({one.row_count.toLocaleString()} rows)
              </option>
            ))}
        </select>
      </Field>

      {sourceId && (
        <>
          <Field
            label="Matched on"
            hint={`A variable both have that says which row of ${source.data?.name ?? 'the other dataset'} belongs to each row here - the interview key, a household id. It must be unique there.`}
          >
            <div className="space-y-2">
              {(keys ?? []).map((key, index) => (
                <div key={index} className="flex flex-wrap items-center gap-2">
                  <select
                    className="input w-52"
                    aria-label={`Key ${index + 1} in ${dataset.name}`}
                    value={key.here}
                    onChange={(event) => setKey(index, { here: event.target.value })}
                  >
                    <option value="">In {dataset.name}…</option>
                    {ours.map((variable) => (
                      <option key={variable.name} value={variable.name}>
                        {variable.name}
                      </option>
                    ))}
                  </select>
                  <span className="text-ink-500">=</span>
                  <select
                    className="input w-52"
                    aria-label={`Key ${index + 1} in ${source.data?.name ?? 'the other dataset'}`}
                    value={key.there}
                    onChange={(event) => setKey(index, { there: event.target.value })}
                  >
                    <option value="">In {source.data?.name ?? 'the other'}…</option>
                    {theirs
                      .filter((variable) => !variable.name.endsWith('__mv'))
                      .map((variable) => (
                        <option key={variable.name} value={variable.name}>
                          {variable.name}
                        </option>
                      ))}
                  </select>
                  <button
                    type="button"
                    className="btn-ghost btn-sm text-red-600"
                    aria-label={`Remove key ${index + 1}`}
                    onClick={() => setKeys((keys ?? []).filter((_, i) => i !== index))}
                  >
                    ✕
                  </button>
                </div>
              ))}
              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  className="btn-ghost btn-sm"
                  title="A roster is matched on two: the interview and the line within it"
                  onClick={() => setKeys([...(keys ?? []), { here: '', there: '' }])}
                >
                  + {keys?.length ? 'Another key' : 'Choose a key'}
                </button>
                <label className="ml-auto flex items-center gap-2 text-xs text-ink-500">
                  Compare the keys
                  <select
                    className="input w-44 py-1 text-xs"
                    aria-label="How the keys are compared"
                    value={keyMatch}
                    onChange={(event) => setKeyMatch(event.target.value as KeyMatch)}
                  >
                    {KEY_MATCHES.map((one) => (
                      <option key={one.value} value={one.value} title={one.hint}>
                        {one.label}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
            </div>
          </Field>

          <div
            role="status"
            className={`mb-4 rounded-card border px-3 py-2 text-sm ${
              problem
                ? 'border-red-200 bg-red-50 text-red-800'
                : check.data?.match && check.data.match.matched < check.data.match.rows
                  ? 'border-amber-200 bg-amber-50 text-amber-900'
                  : 'border-ink-200 bg-ink-50 text-ink-700'
            }`}
          >
            {check.isFetching && !check.data ? 'Checking the keys…' : problem ?? check.data?.match?.sentence ?? 'Choose the key to match on.'}
          </div>

          <Field label="Variables to bring in">
            <div className="rounded-card border border-ink-200">
              <div className="flex items-center gap-2 border-b border-ink-200 px-3 py-2">
                <input
                  className="input flex-1 py-1 text-xs"
                  placeholder="Search variables…"
                  aria-label="Search the other dataset's variables"
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                />
                <span className="text-xs text-ink-500">{chosen.length} chosen</span>
              </div>
              <ul className="max-h-64 overflow-auto py-1">
                {shown.map((one) => (
                  <li key={one.name}>
                    <label
                      className={`flex items-center gap-2 px-3 py-1 text-sm ${
                        one.unavailable ? 'text-ink-500' : 'cursor-pointer hover:bg-ink-50'
                      }`}
                      title={one.unavailable}
                    >
                      <input
                        type="checkbox"
                        disabled={Boolean(one.unavailable)}
                        checked={chosen.includes(one.name)}
                        onChange={(event) =>
                          setChosen(
                            event.target.checked
                              ? [...chosen, one.name]
                              : chosen.filter((name) => name !== one.name),
                          )
                        }
                      />
                      <code className="font-mono text-xs">{one.name}</code>
                      <span className="truncate text-xs text-ink-500">
                        {one.unavailable ?? one.label}
                      </span>
                    </label>
                  </li>
                ))}
                {!shown.length && (
                  <li className="px-3 py-2 text-xs text-ink-500">
                    {source.isLoading ? 'Loading…' : 'No variables to show.'}
                  </li>
                )}
              </ul>
            </div>
          </Field>
        </>
      )}
    </Modal>
  )
}
