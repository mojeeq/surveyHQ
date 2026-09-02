import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '@/lib/api'
import { useToast } from '@/hooks/useToast'
import type { Project } from '@/lib/types'
import ProjectPicker from './ProjectPicker'
import { Badge, Modal } from './ui'

/**
 * Moves an existing dataset or dashboard between projects.
 *
 * Shown as the project it is currently in, because that is the fact worth
 * seeing at a glance; clicking it opens the move. Both ends of a move need
 * manager rights on the server, so a refusal here is expected rather than
 * exceptional and is surfaced as a message, not a silent no-op.
 */
export default function AssignProject({
  kind,
  id,
  projectId,
  canMove,
}: {
  kind: 'dataset' | 'dashboard'
  id: string
  projectId: string | null
  canMove: boolean
}) {
  const toast = useToast()
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [choice, setChoice] = useState(projectId ?? '')

  const projects = useQuery({
    queryKey: ['projects'],
    queryFn: () => api.get<Project[]>('/projects'),
  })
  const current = projects.data?.find((project) => project.id === projectId)
  const label = projectId ? (current?.name ?? 'Another project') : 'Shared area'

  const move = useMutation({
    mutationFn: () =>
      api.put<{ detail: string }>(`/projects/assign/${kind}/${id}`, {
        project_id: choice || null,
      }),
    onSuccess: (result) => {
      toast.push(result.detail, 'success')
      queryClient.invalidateQueries()
      setOpen(false)
    },
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  if (!canMove) {
    return <Badge tone={projectId ? 'info' : 'neutral'}>{label}</Badge>
  }

  return (
    <>
      <button className="btn-secondary" onClick={() => setOpen(true)} title="Move to a project">
        ◫ {label}
      </button>
      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title={`Move this ${kind}`}
        footer={
          <>
            <button className="btn-secondary" onClick={() => setOpen(false)}>
              Cancel
            </button>
            <button
              className="btn-primary"
              onClick={() => move.mutate()}
              disabled={move.isPending || (choice || null) === (projectId ?? null)}
            >
              Move
            </button>
          </>
        }
      >
        <ProjectPicker
          value={choice}
          onChange={setChoice}
          label="Move to"
          hint={`Moving out of a project needs manager rights on it, so this ${kind} cannot be taken from a project you do not manage.`}
        />
      </Modal>
    </>
  )
}
