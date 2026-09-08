import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, downloadFile } from '@/lib/api'
import { copyText } from '@/lib/clipboard'
import { useToast } from '@/hooks/useToast'
import { formatNumber, relativeTime } from '@/lib/format'
import { Badge, Field, Modal, Spinner } from '@/components/ui'
import type { Dashboard } from '@/lib/types'

export interface ShareLink {
  id: string
  name: string
  token: string
  is_active: boolean
  has_password: boolean
  /** When it stops opening. Null is a link with no end. */
  expires_at: string | null
  /** Worked out by the server, whose clock is the one that decides. */
  expired: boolean
  view_count: number
  last_viewed_at: string | null
  created_at: string
}

const urlFor = (token: string) => `${location.origin}/shared/${token}`

/** The yyyy-mm-dd a date input wants, read in the reader's own zone. */
function dateInputValue(iso: string | null | undefined): string {
  if (!iso) return ''
  const at = new Date(iso)
  if (Number.isNaN(at.getTime())) return ''
  const pad = (part: number) => String(part).padStart(2, '0')
  return `${at.getFullYear()}-${pad(at.getMonth() + 1)}-${pad(at.getDate())}`
}

/**
 * The last moment of the chosen day, where the person choosing it is.
 *
 * "Expires on the 3rd" means it works on the 3rd and is shut on the 4th, which
 * is how anyone reads a date on a pass. Taking the date at midnight would kill
 * it a day early, and doing the arithmetic in UTC would kill it early in Port
 * Vila and late in Suva.
 */
function endOfDay(value: string): string | null {
  if (!value) return null
  const [year, month, day] = value.split('-').map(Number)
  if (!year || !month || !day) return null
  return new Date(year, month - 1, day, 23, 59, 59, 999).toISOString()
}

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
  const [expires, setExpires] = useState('')

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
        expires_at: endOfDay(expires),
      }),
    onSuccess: (link) => {
      setName('')
      setPassword('')
      setExpires('')
      refresh()
      copy(link.token, toast)
    },
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  const change = useMutation({
    mutationFn: ({
      id,
      ...body
    }: { id: string } & Partial<Omit<ShareLink, 'expires_at'>> & {
      password?: string
      expires_at?: string | null
    }) =>
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

      <DownloadCopy dashboard={dashboard} />

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
          expired={link.expired}
          expiresAt={link.expires_at}
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
          onExpiry={(expires_at) => change.mutate({ id: link.id, expires_at })}
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
          <Field
            label="Stops working after"
            hint="Optional. It works all of that day and is closed the next morning."
          >
            <input
              className="input"
              type="date"
              value={expires}
              onChange={(event) => setExpires(event.target.value)}
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

/**
 * The dashboard as a file, for putting somewhere this platform is not.
 *
 * A link needs susoDash running and reachable. A ministry's own web host, a
 * report's appendix, a laptop taken to a meeting on an island with no
 * connection - those need the board itself, and a picture of it loses the one
 * thing that makes it a dashboard, which is that the reader can narrow it.
 */
function DownloadCopy({ dashboard }: { dashboard: Dashboard }) {
  const toast = useToast()
  const [busy, setBusy] = useState(false)
  return (
    <div className="mb-4 rounded-card border border-ink-200 bg-ink-50 px-3 py-2.5">
      <div className="flex flex-wrap items-center gap-3">
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-ink-800">Download as a web page</p>
          <p className="text-xs text-ink-500">
            One HTML file you can put on any web host or send to somebody. Its filter
            dropdowns still work: the numbers behind every widget travel with it. Charts
            and maps are drawn by libraries fetched from the internet, and a widget that
            cannot be worked out again offline - a data quality panel, a median - says on
            its face that it is showing the day it was exported.
          </p>
        </div>
        <button
          className="btn-secondary btn-sm shrink-0"
          disabled={busy}
          onClick={async () => {
            setBusy(true)
            try {
              await downloadFile(
                `/dashboards/${dashboard.id}/export.html`,
                undefined,
                `${dashboard.slug || 'dashboard'}.html`,
                'GET',
              )
            } catch (error) {
              toast.push((error as Error).message, 'error')
            } finally {
              setBusy(false)
            }
          }}
        >
          {busy && <Spinner className="h-4 w-4" />}
          {busy ? 'Building the file' : 'Download'}
        </button>
      </div>
    </div>
  )
}

function LinkRow({
  title,
  token,
  active,
  expired = false,
  expiresAt,
  hasPassword = false,
  note,
  onCopy,
  onToggle,
  onPassword,
  onRename,
  onDelete,
  onExpiry,
}: {
  title: string
  token: string
  active: boolean
  /** Its date has passed. Shut to readers, but not closed by anybody. */
  expired?: boolean
  expiresAt?: string | null
  hasPassword?: boolean
  note?: string
  onCopy: () => void
  onToggle?: () => void
  onPassword?: () => void
  onRename?: () => void
  onDelete?: () => void
  /** Give the link an end, or take it off again with null. */
  onExpiry?: (expiresAt: string | null) => void
}) {
  // Closed by hand and run out are two different things to the person looking
  // at this list and one thing to a reader: either way the address is shut.
  const open = active && !expired
  return (
    <div
      className={`mb-2 rounded-card border px-3 py-2.5 ${
        open ? 'border-ink-200' : 'border-ink-200 bg-ink-50'
      }`}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className={`text-sm font-medium ${open ? 'text-ink-800' : 'text-ink-500'}`}>
          {title}
        </span>
        {hasPassword && <Badge tone="info">Password</Badge>}
        {expired && <Badge tone="warning">Expired</Badge>}
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
        className={`mt-1 block break-all text-xs ${open ? 'text-ink-600' : 'text-ink-400 line-through'}`}
      >
        {urlFor(token)}
      </code>
      {onExpiry && (
        // In the row rather than behind a dialog: an end date is the thing
        // most often got wrong when the link is made and wanted a week later,
        // and a date field is quicker to read than a sentence about one.
        <label className="mt-1.5 flex flex-wrap items-center gap-2 text-xs text-ink-500">
          Stops working after
          <input
            type="date"
            className="input h-7 w-40 py-0 text-xs"
            value={dateInputValue(expiresAt)}
            onChange={(event) => onExpiry(endOfDay(event.target.value))}
          />
          {expiresAt ? (
            <button className="text-brand-600 hover:underline" onClick={() => onExpiry(null)}>
              No end date
            </button>
          ) : (
            <span className="text-ink-400">no end date</span>
          )}
        </label>
      )}
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
