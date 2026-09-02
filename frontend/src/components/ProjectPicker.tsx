import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import type { Project } from '@/lib/types'
import { Field } from './ui'

/**
 * Chooses the project something belongs to, in the one place that decision is
 * made: on upload, on create, and when moving an existing dataset or dashboard.
 *
 * The empty value is the shared area, not "unset" - it is a real destination
 * that every user can see, and the wording says so rather than leaving a blank
 * option to be guessed at.
 */
export default function ProjectPicker({
  value,
  onChange,
  label = 'Project',
  hint,
  managedOnly = true,
}: {
  value: string
  onChange: (projectId: string) => void
  label?: string
  hint?: string
  /** Only offer projects this user can actually put things into. */
  managedOnly?: boolean
}) {
  const projects = useQuery({
    queryKey: ['projects'],
    queryFn: () => api.get<Project[]>('/projects'),
  })

  const options = (projects.data ?? []).filter(
    (project) =>
      !managedOnly || project.your_role === 'manager' || project.your_role === 'admin',
  )

  return (
    <Field
      label={label}
      hint={
        hint ??
        (options.length
          ? 'The shared area is visible to every user; a project is visible only to its members.'
          : 'You have no projects to assign to, so this stays in the shared area.')
      }
    >
      <select
        className="input"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        disabled={!options.length}
      >
        <option value="">Shared area (everyone)</option>
        {options.map((project) => (
          <option key={project.id} value={project.id}>
            {project.name}
          </option>
        ))}
      </select>
    </Field>
  )
}
