import { useQuery } from '@tanstack/react-query'

import { useEffect,useMemo,useState } from 'react'

import { useSearchParams } from 'react-router-dom'

import { api } from '@/lib/api'

import { useAuth } from '@/hooks/useAuth'

import { useToast } from '@/hooks/useToast'


import type {
Chart,
Dataset,
Page,
Project
} from '@/lib/types'






import { AggregateBuilder } from '@/components/explore/AggregateBuilder'
import { CrosstabBuilder } from '@/components/explore/CrosstabBuilder'
import { MultiSelectBuilder } from '@/components/explore/MultiSelectBuilder'
import { Mode,modeOf,openedIn } from '@/components/explore/shared'
import {
Card,
EmptyState,
ErrorNote,
Loading,
PageHeader,
Tabs
} from '@/components/ui'


export default function Explore() {
  const [params, setParams] = useSearchParams()
  const toast = useToast()
  const { can } = useAuth()
  const [mode, setMode] = useState<Mode>('aggregate')

  const datasets = useQuery({
    queryKey: ['datasets', 'all'],
    queryFn: () => api.get<Page<Dataset>>('/datasets?limit=200&status=ready'),
  })
  const projects = useQuery({
    queryKey: ['projects'],
    queryFn: () => api.get<Project[]>('/projects'),
  })

  // Both live in the URL, so a link to an analysis lands on the same two
  // choices rather than resetting to whatever happens to be first.
  const projectId = params.get('project') ?? ''
  const inProject = useMemo(
    () =>
      (datasets.data?.items ?? []).filter((item) =>
        projectId === ''
          ? true
          : projectId === 'none'
            ? item.project_id === null
            : item.project_id === projectId,
      ),
    [datasets.data, projectId],
  )

  // Editing a saved chart opens it here, which is where its query was built
  // in the first place. Everything is prefilled, so "change the variable" is
  // changing the variable rather than rebuilding the chart from memory.
  const editingId = params.get('chart') ?? ''
  const editing = useQuery({
    queryKey: ['chart', editingId],
    queryFn: () => api.get<Chart>(`/dashboards/charts/${editingId}`),
    enabled: Boolean(editingId),
  })

  // A saved chart is edited in whichever builder made it, so opening one has
  // to switch to that tab first.
  useEffect(() => {
    if (editing.data) setMode(modeOf(editing.data))
  }, [editing.data])

  const requested = editing.data?.dataset_id || (params.get('dataset') ?? '')
  // A dataset from another project stops being a valid choice the moment the
  // project filter changes, so fall back rather than showing an empty picker.
  const datasetId = inProject.some((item) => item.id === requested)
    ? requested
    : (inProject[0]?.id ?? '')

  const dataset = useQuery({
    queryKey: ['dataset', datasetId],
    queryFn: () => api.get<Dataset>(`/datasets/${datasetId}`),
    enabled: Boolean(datasetId),
  })

  const variables = dataset.data?.variables ?? []
  // Every variable can be grouped on, including the ones with a value per row.
  // Hiding them was meant to keep a 20,000-row tabulation out of the way, but
  // it hid interview__key - and "one row per interview, with these columns" is
  // a thing people legitimately want to tabulate. The count travels with the
  // name instead, and the row limit still decides how much comes back.
  const groupable = useMemo(() => variables.filter((v) => !v.is_hidden), [variables])
  const numeric = useMemo(() => variables.filter((v) => v.var_type === 'numeric'), [variables])

  if (datasets.isLoading) return <Loading />
  if (!datasets.data?.items.length) {
    return (
      <Card>
        <EmptyState
          icon="▤"
          title="No datasets ready to analyse"
          description="Upload a data file or import from a Survey Solutions server first."
        />
      </Card>
    )
  }

  return (
    <>
      <PageHeader
        title={editing.data ? `Editing “${editing.data.name}”` : 'Explore'}
        description={
          editing.data
            ? 'Change the grouping, the measure, the filters or the chart type. Saving writes back to this chart, so every dashboard showing it follows.'
            : 'Build tabulations and charts against any dataset.'
        }
        actions={
          <div className="flex flex-wrap items-center gap-2">
            {editing.data && (
              <button
                className="btn-secondary"
                onClick={() => {
                  const next = new URLSearchParams(params)
                  next.delete('chart')
                  setParams(next)
                }}
              >
                Stop editing
              </button>
            )}
            <select
              className="input w-52"
              value={projectId}
              onChange={(event) =>
                setParams(
                  event.target.value ? { project: event.target.value } : {},
                )
              }
            >
              <option value="">All projects</option>
              <option value="none">Shared area</option>
              {projects.data?.map((project) => (
                <option key={project.id} value={project.id}>
                  {project.name}
                </option>
              ))}
            </select>
            <select
              className="input w-64"
              value={datasetId}
              disabled={!inProject.length}
              onChange={(event) =>
                setParams(
                  projectId
                    ? { project: projectId, dataset: event.target.value }
                    : { dataset: event.target.value },
                )
              }
            >
              {inProject.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
          </div>
        }
      />

      <Tabs
        tabs={[
          { id: 'aggregate', label: 'Tabulate & chart' },
          { id: 'crosstab', label: 'Cross-tabulation' },
          { id: 'multiselect', label: 'Tick all that apply' },
        ]}
        active={mode}
        onChange={(id) => setMode(id as Mode)}
      />

      {!inProject.length ? (
        <Card className="mt-4">
          <EmptyState
            icon="▤"
            title="Nothing to analyse in this project"
            description="Assign a dataset to it from the Datasets page, or upload straight into it."
          />
        </Card>
      ) : dataset.isLoading ? (
        <Loading />
      ) : !dataset.data ? (
        <ErrorNote error={new Error('Dataset could not be loaded')} />
      ) : mode === 'aggregate' ? (
        <AggregateBuilder
          key={editingId || datasetId}
          datasetId={datasetId}
          datasetName={dataset.data.name}
          groupable={groupable}
          numeric={numeric}
          allVariables={variables}
          canSave={can('analyst')}
          editing={openedIn('aggregate', editing.data)}
          onSaved={() => toast.push('Chart saved', 'success')}
        />
      ) : mode === 'crosstab' ? (
        <CrosstabBuilder
          key={editingId || datasetId}
          datasetId={datasetId}
          datasetName={dataset.data.name}
          groupable={groupable}
          numeric={numeric}
          allVariables={variables}
          canSave={can('analyst')}
          editing={openedIn('crosstab', editing.data)}
        />
      ) : (
        <MultiSelectBuilder
          key={editingId || datasetId}
          datasetId={datasetId}
          datasetName={dataset.data.name}
          allVariables={variables}
          canSave={can('analyst')}
          editing={openedIn('multiselect', editing.data)}
        />
      )}
    </>
  )
}