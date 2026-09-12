/**
 * The workspace-wide project switcher.
 *
 * A dataset owns the project relationship for charts, indicators, quality
 * rules and alerts, so one project choice can consistently narrow all of those
 * views. Null is every project; the empty string is the shared area.
 *
 * `value`/`onChange` remain supported for older pages that kept local project
 * state. Those page-level instances are now compatibility adapters only: they
 * synchronize their local state with the global workspace but do not render a
 * second selector. The one visible project switcher lives in the app header.
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

  // Only the compact instance in Layout is visible. Older pages still mount
  // this component so their local project state follows the workspace scope,
  // but showing those controls as well would duplicate the header switcher.
  if (!compact || !projects.data?.length) return null

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
      className="flex min-w-0 items-center gap-2 text-sm text-ink-600 dark:text-dark-600"
      title="Project workspace"
    >
      <select
        className="input w-44 py-1.5 lg:w-52"
        value={project === null ? '__all__' : project}
        onChange={(event) => {
          const selected = event.target.value
          choose(selected === '__all__' ? null : selected)
        }}
        aria-label="Project workspace"
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
