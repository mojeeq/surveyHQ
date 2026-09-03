/**
 * Narrows a page to one project.
 *
 * Indicators, quality rules and alerts all hang off a dataset, and a dataset
 * belongs to a project - so this is a question about their dataset rather than
 * a second project stored on each of them that could disagree with it. Which
 * also means an indicator moves projects when its dataset does, with nothing
 * to keep in step.
 *
 * Null is every project; the empty string is the shared area, which is a real
 * place rather than the absence of one.
 */
import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import type { Project } from '@/lib/types'

export default function ProjectFilter({
  value,
  onChange,
  label = 'Project',
}: {
  value: string | null
  onChange: (project: string | null) => void
  label?: string
}) {
  const projects = useQuery({
    queryKey: ['projects'],
    queryFn: () => api.get<Project[]>('/projects'),
  })

  if (!projects.data?.length) return null

  return (
    <label className="flex items-center gap-2 text-sm text-ink-600">
      {label}
      <select
        className="input w-52 py-1.5"
        value={value === null ? '__all__' : value}
        onChange={(event) => {
          const chosen = event.target.value
          onChange(chosen === '__all__' ? null : chosen)
        }}
      >
        <option value="__all__">All projects</option>
        <option value="">Shared area</option>
        {projects.data.map((project) => (
          <option key={project.id} value={project.id}>
            {project.name}
          </option>
        ))}
      </select>
    </label>
  )
}

/** The query-string fragment for a filter value, empty when it is "all". */
export function projectParam(value: string | null): string {
  return value === null ? '' : `&project_id=${encodeURIComponent(value)}`
}
