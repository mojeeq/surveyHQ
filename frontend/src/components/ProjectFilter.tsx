/**
 * The workspace-wide project switcher.
 *
 * A dataset owns the project relationship for charts, indicators, quality
 * rules and alerts, so one project choice can consistently narrow all of those
 * views. Null is every project; the empty string is the shared area.
 *
 * `value`/`onChange` remain supported for the older pages that kept local
 * project state. The global scope is authoritative and the effect below keeps
 * those local states in step while they are migrated away.
 */
import { useEffect } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import type { Project } from '@/lib/types'
import { useProjectScope, type ProjectScope } from '@/hooks/useProjectScope'

export default function ProjectFilter({
  value,
  onChange,
  label = 'Project',
  compact = false,
}: {
  value?: ProjectScope
  onChange?: (project: ProjectScope) => void
  label?: string
  compact?: boolean
}) {
  const queryClient = useQueryClient()
  const { project, setProject } = useProjectScope()
  const projects = useQuery({
    queryKey: ['projects', 'scope-picker'],
    // The API client normally scopes project collections too. This marker asks
    // for the complete accessible list because a switcher must be able to move
    // out of the project that is currently selected.
    queryFn: () => api.get<Project[]>('/projects?scope=all'),
  })

  useEffect(() => {
    if (onChange && value !== project) onChange(project)
  }, [onChange, project, value])

  useEffect(() => {
    if (
      project &&
      projects.data &&
      !projects.data.some((candidate) => candidate.id === project)
    ) {
      setProject(null)
      queryClient.invalidateQueries()
    }
  }, [project, projects.data, queryClient, setProject])

  if (!projects.data?.length) return null

  const choose = (next: ProjectScope) => {
    setProject(next)
    onChange?.(next)
    // Some older screens don't subscribe to the workspace scope yet. Invalidating
    // makes their existing queries refetch through the scoped API client now,
    // rather than waiting until the user navigates away and back.
    queryClient.invalidateQueries()
  }

  return (
    <label
      className={`flex items-center gap-2 text-sm text-ink-600 dark:text-dark-600 ${
        compact ? 'min-w-0' : ''
      }`}
      title={compact ? 'Project workspace' : undefined}
    >
      {!compact && label}
      <select
        className={`input py-1.5 ${compact ? 'w-44 lg:w-52' : 'w-52'}`}
        value={project === null ? '__all__' : project}
        onChange={(event) => {
          const selected = event.target.value
          choose(selected === '__all__' ? null : selected)
        }}
        aria-label={compact ? 'Project workspace' : label}
      >
        <option value="__all__">All projects</option>
        <option value="">Shared area</option>
        {projects.data.map((candidate) => (
          <option key={candidate.id} value={candidate.id}>
            {candidate.name}
          </option>
        ))}
      </select>
    </label>
  )
}

/** The query-string fragment for dataset-owned resources. */
export function projectParam(value: ProjectScope): string {
  return value === null ? '' : `&project_id=${encodeURIComponent(value)}`
}

/**
 * Dataset listings spell the shared area `none`, because an empty project_id
 * there means "no project filter" rather than the shared area itself.
 */
export function datasetProjectParam(value: ProjectScope): string {
  return value === null ? '' : `&project_id=${encodeURIComponent(value || 'none')}`
}
