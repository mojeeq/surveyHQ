import { useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { useAuth } from '@/hooks/useAuth'
import { useToast } from '@/hooks/useToast'
import { formatNumber } from '@/lib/format'
import ProjectPicker from '@/components/ProjectPicker'
import { Card, EmptyState, ErrorNote, Field, Loading, Modal } from '@/components/ui'
import type { BoundaryLayer } from '@/lib/types'

const FORMATS: Record<string, string> = {
  geojson: 'GeoJSON',
  geopackage: 'GeoPackage',
  shapefile: 'Shapefile',
}

/**
 * The frames fieldwork is organised into: enumeration areas, districts, villages.
 *
 * They live beside the datasets rather than inside one, because a national
 * frame is not survey data - it is the thing the survey data is checked
 * against, uploaded once and used by every round that works to it. A map
 * widget then draws whichever one it names, and can check the area each record
 * says it was in against the area it actually falls in.
 */
export default function BoundaryLibrary() {
  const { can } = useAuth()
  const toast = useToast()
  const queryClient = useQueryClient()
  const [adding, setAdding] = useState(false)

  const layers = useQuery({
    queryKey: ['boundaries'],
    queryFn: () => api.get<BoundaryLayer[]>('/boundaries'),
  })

  const remove = useMutation({
    mutationFn: (id: string) => api.delete(`/boundaries/${id}`),
    onSuccess: () => {
      toast.push('Boundary layer deleted', 'success')
      queryClient.invalidateQueries({ queryKey: ['boundaries'] })
    },
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  return (
    <section className="mt-8">
      <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
        <div>
          <h2 className="text-base font-semibold text-ink-800">Boundaries</h2>
          <p className="text-sm text-ink-500">
            The areas fieldwork is organised into, for drawing under a map and for
            checking that a record was collected where it says it was.
          </p>
        </div>
        {can('manager') && (
          <button className="btn-secondary btn-sm" onClick={() => setAdding(true)}>
            Add boundaries
          </button>
        )}
      </div>

      {layers.isLoading ? (
        <Loading />
      ) : layers.error ? (
        <ErrorNote error={layers.error} retry={layers.refetch} />
      ) : !layers.data?.length ? (
        <Card>
          <EmptyState
            icon="⬡"
            title="No boundary layers yet"
            description="Upload the enumeration-area frame from your GIS office as GeoJSON, a GeoPackage, or a zipped shapefile."
            action={
              can('manager') ? (
                <button className="btn-primary btn-sm" onClick={() => setAdding(true)}>
                  Add your first layer
                </button>
              ) : undefined
            }
          />
        </Card>
      ) : (
        <Card>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-ink-200 text-left text-xs uppercase tracking-wide text-ink-500">
                  <th className="py-2 pr-4 font-medium">Layer</th>
                  <th className="py-2 pr-4 font-medium">Areas</th>
                  <th className="py-2 pr-4 font-medium">Attributes</th>
                  <th className="py-2 pr-4 font-medium">From</th>
                  <th className="py-2 font-medium" />
                </tr>
              </thead>
              <tbody>
                {layers.data.map((layer) => (
                  <tr key={layer.id} className="border-b border-ink-100 last:border-0">
                    <td className="py-2 pr-4">
                      <div className="font-medium text-ink-800">{layer.name}</div>
                      {layer.description && (
                        <div className="text-xs text-ink-500">{layer.description}</div>
                      )}
                    </td>
                    <td className="py-2 pr-4 tabular-nums text-ink-700">
                      {formatNumber(layer.feature_count)}
                    </td>
                    <td className="py-2 pr-4">
                      {/* What a widget picks its area code and its label from,
                          so the answer is visible before the widget is opened. */}
                      <span className="font-mono text-xs text-ink-600">
                        {layer.properties.slice(0, 6).join(', ')}
                        {layer.properties.length > 6 && ` +${layer.properties.length - 6}`}
                      </span>
                    </td>
                    <td className="py-2 pr-4 text-xs text-ink-500">
                      {FORMATS[layer.source_format] ?? layer.source_format}
                    </td>
                    <td className="py-2 text-right">
                      {can('manager') && (
                        <button
                          className="btn-ghost btn-sm text-red-600"
                          onClick={() => {
                            if (
                              confirm(
                                `Delete "${layer.name}"? Maps drawing it will stop showing ` +
                                  'their outlines and stop checking recorded areas.',
                              )
                            )
                              remove.mutate(layer.id)
                          }}
                        >
                          Delete
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {adding && <AddBoundaries onClose={() => setAdding(false)} />}
    </section>
  )
}

function AddBoundaries({ onClose }: { onClose: () => void }) {
  const toast = useToast()
  const queryClient = useQueryClient()
  const input = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [projectId, setProjectId] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async () => {
    if (!file) return
    const form = new FormData()
    form.append('file', file)
    form.append('name', name.trim())
    form.append('description', description.trim())
    form.append('project_id', projectId)
    setBusy(true)
    try {
      const layer = await api.upload<BoundaryLayer>('/boundaries', form)
      queryClient.invalidateQueries({ queryKey: ['boundaries'] })
      toast.push(
        `"${layer.name}" added with ${formatNumber(layer.feature_count)} areas`,
        'success',
      )
      onClose()
    } catch (error) {
      toast.push((error as Error).message, 'error')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      open
      title="Add boundaries"
      onClose={onClose}
      footer={
        <>
          <button className="btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button className="btn-primary" disabled={!file || busy} onClick={submit}>
            {busy ? 'Reading…' : 'Add layer'}
          </button>
        </>
      }
    >
      <Field
        label="File"
        hint="GeoJSON (.geojson), a GeoPackage (.gpkg), or a shapefile zipped with its .dbf and .shx."
      >
        <input
          ref={input}
          type="file"
          className="input"
          accept=".geojson,.json,.gpkg,.zip"
          onChange={(event) => {
            const chosen = event.target.files?.[0] ?? null
            setFile(chosen)
            // Named after the file unless somebody types otherwise, which is
            // right nearly always: these arrive called what they are.
            if (chosen && !name) setName(chosen.name.replace(/\.[^.]+$/, ''))
          }}
        />
      </Field>

      <Field label="Name">
        <input
          className="input"
          value={name}
          placeholder="Enumeration areas 2026"
          onChange={(event) => setName(event.target.value)}
        />
      </Field>

      <Field label="Description" hint="Optional. Which frame this is, and when it was drawn.">
        <input
          className="input"
          value={description}
          onChange={(event) => setDescription(event.target.value)}
        />
      </Field>

      <ProjectPicker
        value={projectId}
        onChange={setProjectId}
        hint="Leave shared for a national frame every survey works to."
      />
    </Modal>
  )
}
