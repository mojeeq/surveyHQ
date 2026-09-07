import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { copyText } from '@/lib/clipboard'
import { useToast } from '@/hooks/useToast'
import { formatNumber, relativeTime } from '@/lib/format'
import { Badge, Field, Modal } from '@/components/ui'
import type { Dashboard } from '@/lib/types'

export interface ShareLink {
  id: string
  name: string
  token: string
  is_active: boolean
  has_password: boolean
  view_count: number
  last_viewed_at: string | null
  created_at: string
}

const urlFor = (token: string) => `${location.origin}/shared/${token}`

/**
 * Every address this dashboard is published at.
 *
 * One board goes to a minister, to the field supervisors and to a donor, and
 * those audiences do not end together. With a single link, closing the donor's
 * access closed everybody's - so the way to do it was to build the dashboard
 * again somewhere else. Each audience gets its own address here, closable on
 * its own and reopenable at the same address, because by then the link is
 * already in somebody's inbox.
 */
export default function ShareLinks({
  dashboard,
  onClose,
}: {
  dashboard: Dashboard
  onClose: () => void
}) {
  const toast = useToast()
  const queryClient = useQueryClient()
  const [name, setName] = useState('')
  const [password, setPassword] = useState('')

  const links = useQuery({
    queryKey: ['share-links', dashboard.id],
    queryFn: () => api.get<ShareLink[]>(`/dashboards/${dashboard.id}/share-links`),
  })

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['share-links', dashboard.id] })
    queryClient.invalidateQueries({ queryKey: ['dashboard', dashboard.id] })
  }

  const create = useMutation({
    mutationFn: () =>
      api.post<ShareLink>(`/dashboards/${dashboard.id}/share-links`, {
        name: name.trim(),
        password: password.trim(),
      }),
    onSuccess: (link) => {
      setName('')
      setPassword('')
      refresh()
      copy(link.token, toast)
    },
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  const change = useMutation({
    mutationFn: ({ id, ...body }: { id: string } & Partial<ShareLink> & { password?: string }) =>
      api.patch(`/dashboards/${dashboard.id}/share-links/${id}`, body),
    onSuccess: refresh,
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  const remove = useMutation({
    mutationFn: (id: string) => api.delete(`/dashboards/${dashboard.id}/share-links/${id}`),
    onSuccess: () => {
      refresh()
      toast.push('Link deleted', 'info')
    },
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  return (
    <Modal
      open
      wide
      title="Share links"
      onClose={onClose}
      footer={
        <button className="btn-secondary" onClick={onClose}>
          Done
        </button>
      }
    >
      <p className="mb-4 text-sm text-ink-600">
        Each link is its own address. Close one when its audience is done with it and
        the others carry on working.
      </p>

      {dashboard.is_public && dashboard.public_token && (
        <LinkRow
          title="Original link"
          note={
            dashboard.public_hostname
              ? `Also answers on ${dashboard.public_hostname}`
              : 'The address this dashboard has always had, and the one a custom web address uses.'
          }
          token={dashboard.public_token}
          active
          onCopy={() => copy(dashboard.public_token!, toast)}
        />
      )}

      {links.data?.map((link) => (
        <LinkRow
          key={link.id}
          title={link.name}
          token={link.token}
          active={link.is_active}
          hasPassword={link.has_password}
          note={
            link.view_count
              ? `Opened ${formatNumber(link.view_count)} time${link.view_count === 1 ? '' : 's'}${
                  link.last_viewed_at ? `, last ${relativeTime(link.last_viewed_at)}` : ''
                }`
              : 'Not opened yet'
          }
          onCopy={() => copy(link.token, toast)}
          onToggle={() => change.mutate({ id: link.id, is_active: !link.is_active })}
          onPassword={() => {
            if (link.has_password) {
              if (confirm(`Remove the password from "${link.name}"? Anyone with the link will then be able to open it.`))
                change.mutate({ id: link.id, password: '' })
              return
            }
            const chosen = prompt(`Password for "${link.name}"`)
            if (chosen && chosen.trim()) change.mutate({ id: link.id, password: chosen.trim() })
          }}
          onRename={() => {
            const chosen = prompt('Name this link', link.name)
            if (chosen && chosen.trim()) change.mutate({ id: link.id, name: chosen.trim() })
          }}
          onDelete={() => {
            if (
              confirm(
                `Delete "${link.name}"? Closing it instead keeps the address, so it can ` +
                  'be switched back on later.',
              )
            )
              remove.mutate(link.id)
          }}
        />
      ))}

      <div className="mt-5 rounded-card border border-ink-200 p-3">
        <p className="mb-3 text-sm font-medium text-ink-800">Add a link</p>
        <div className="grid gap-x-4 sm:grid-cols-2">
          <Field label="Who is it for" hint="Shown here only, so you can tell them apart.">
            <input
              className="input"
              value={name}
              placeholder="Field supervisors"
              onChange={(event) => setName(event.target.value)}
            />
          </Field>
          <Field label="Password" hint="Optional. Leave blank for a link anyone can open.">
            <input
              className="input"
              type="text"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </Field>
        </div>
        <button
          className="btn-primary btn-sm"
          disabled={create.isPending}
          onClick={() => create.mutate()}
        >
          {create.isPending ? 'Creating…' : 'Create link'}
        </button>
      </div>
    </Modal>
  )
}

function LinkRow({
  title,
  token,
  active,
  hasPassword = false,
  note,
  onCopy,
  onToggle,
  onPassword,
  onRename,
  onDelete,
}: {
  title: string
  token: string
  active: boolean
  hasPassword?: boolean
  note?: string
  onCopy: () => void
  onToggle?: () => void
  onPassword?: () => void
  onRename?: () => void
  onDelete?: () => void
}) {
  return (
    <div
      className={`mb-2 rounded-card border px-3 py-2.5 ${
        active ? 'border-ink-200' : 'border-ink-200 bg-ink-50'
      }`}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className={`text-sm font-medium ${active ? 'text-ink-800' : 'text-ink-500'}`}>
          {title}
        </span>
        {hasPassword && <Badge tone="info">Password</Badge>}
        {!active && <Badge tone="neutral">Closed</Badge>}
        <div className="ml-auto flex flex-wrap items-center gap-1">
          <button className="btn-ghost btn-sm" onClick={onCopy}>
            Copy
          </button>
          {onRename && (
            <button className="btn-ghost btn-sm" onClick={onRename}>
              Rename
            </button>
          )}
          {onPassword && (
            <button className="btn-ghost btn-sm" onClick={onPassword}>
              {hasPassword ? 'Remove password' : 'Set password'}
            </button>
          )}
          {onToggle && (
            <button className="btn-ghost btn-sm" onClick={onToggle}>
              {active ? 'Close' : 'Reopen'}
            </button>
          )}
          {onDelete && (
            <button className="btn-ghost btn-sm text-red-600" onClick={onDelete}>
              Delete
            </button>
          )}
        </div>
      </div>
      <code
        className={`mt-1 block break-all text-xs ${active ? 'text-ink-600' : 'text-ink-400 line-through'}`}
      >
        {urlFor(token)}
      </code>
      {note && <p className="mt-1 text-xs text-ink-500">{note}</p>}
    </div>
  )
}

async function copy(token: string, toast: ReturnType<typeof useToast>) {
  // Through the helper rather than navigator.clipboard directly: that object
  // does not exist on a plain HTTP deployment, and the optional chain this
  // used to be written as short-circuited to nothing there - no copy, and no
  // message saying so.
  if (await copyText(urlFor(token))) {
    toast.push('Link copied to your clipboard', 'success')
    return
  }
  // A browser that refuses every way of copying is not a failure worth an
  // error banner: the address is on screen to be selected.
  toast.push('Copy the link from the box below', 'info')
}
