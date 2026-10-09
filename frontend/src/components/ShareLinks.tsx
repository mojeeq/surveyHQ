import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, downloadFile } from '@/lib/api'
import { copyText } from '@/lib/clipboard'
import { useDialog } from '@/hooks/useDialog'
import { useToast } from '@/hooks/useToast'
import { formatNumber, relativeTime } from '@/lib/format'
import { Badge, Field, Modal, Spinner } from '@/components/ui'
import type { Dashboard, DashboardSavedView, Job } from '@/lib/types'

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
  const ask = useDialog()
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
          onPassword={async () => {
            if (link.has_password) {
              const sure = await ask.confirm({
                title: `Remove the password from \u201C${link.name}\u201D?`,
                message: 'Anyone with the link will then be able to open it.',
                confirmLabel: 'Remove password',
                tone: 'danger',
              })
              if (sure) change.mutate({ id: link.id, password: '' })
              return
            }
            const chosen = await ask.prompt({
              title: `Password for \u201C${link.name}\u201D`,
              label: 'Password',
              message: 'Anyone opening the link will be asked for this.',
              confirmLabel: 'Set password',
              validate: (entered) => (entered ? null : 'Enter a password, or cancel.'),
            })
            if (chosen) change.mutate({ id: link.id, password: chosen })
          }}
          onRename={async () => {
            const chosen = await ask.prompt({
              title: 'Name this link',
              label: 'Name',
              defaultValue: link.name,
              confirmLabel: 'Rename',
              validate: (entered) => (entered ? null : 'Give the link a name, or cancel.'),
            })
            if (chosen) change.mutate({ id: link.id, name: chosen })
          }}
          onDelete={async () => {
            const sure = await ask.confirm({
              title: `Delete \u201C${link.name}\u201D?`,
              message:
                'Closing it instead keeps the address, so it can be switched back on later.',
              confirmLabel: 'Delete link',
              tone: 'danger',
            })
            if (sure) remove.mutate(link.id)
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
 * A link needs SurveyHQ running and reachable. A ministry's own web host, a
 * report's appendix, a laptop taken to a meeting on an island with no
 * connection - those need the board itself, and a picture of it loses the one
 * thing that makes it a dashboard, which is that the reader can narrow it.
 */
function DownloadCopy({ dashboard }: { dashboard: Dashboard }) {
  // Saved views are the selections somebody already wrote down, so they are
  // what a report is of: "Malampa this week" is a report of Malampa this week.
  // Nobody has to describe the same thing twice, and the file and the view
  // cannot drift apart.
  const views = useQuery({
    queryKey: ['dashboard-views', dashboard.id, `/dashboards/${dashboard.id}`],
    queryFn: () => api.get<DashboardSavedView[]>(`/dashboards/${dashboard.id}/views`),
  })
  const [view, setView] = useState('')
  const chosen = views.data?.find((one) => one.id === view)

  // A report per value of a filter, in one run. The controls the board
  // already has are the ones worth bursting over: they are the questions
  // somebody decided this board gets asked.
  // `filters` on the dashboard is an untyped bag shared by several readers,
  // so the two fields wanted here are read out rather than the whole type
  // being narrowed underneath everyone else.
  const controls = (dashboard.filters ?? [])
    .map((raw) => ({
      variable: String(raw.variable ?? ''),
      label: String(raw.label ?? raw.variable ?? ''),
    }))
    .filter((control) => control.variable)
  const [burstBy, setBurstBy] = useState('')
  const [burstDone, setBurstDone] = useState(0)
  const counts = useQuery({
    queryKey: ['report-values', dashboard.id, burstBy],
    queryFn: () =>
      api.get<{ values: string[]; limit: number }>(
        `/dashboards/${dashboard.id}/report-values?variable=${encodeURIComponent(burstBy)}`,
      ),
    enabled: Boolean(burstBy),
  })
  const howMany = counts.data?.values.length ?? 0
  const tooMany = Boolean(counts.data) && howMany > (counts.data?.limit ?? 0)

  const burst = useMutation({
    mutationFn: async () => {
      setBurstDone(0)
      let job = await api.post<Job>(`/dashboards/${dashboard.id}/reports`, {
        variable: burstBy,
      })
      // Every value is a full pass over the dataset, so this is minutes. The
      // job carries its own progress and the bar follows it rather than
      // guessing from elapsed time.
      const deadline = Date.now() + 30 * 60 * 1000
      while (job.status === 'queued' || job.status === 'running') {
        if (Date.now() > deadline) {
          throw new Error(
            'The reports are still being written. Watch it under Administration \u2192 Background jobs.',
          )
        }
        await new Promise((resolve) => setTimeout(resolve, 2000))
        job = await api.get<Job>(`/system/jobs/${job.id}`)
        setBurstDone(Math.round((job.progress || 0) * 100))
      }
      if (job.status !== 'success') throw new Error(job.error || 'The run did not finish.')
      await downloadFile(
        `/dashboards/${dashboard.id}/reports/${job.id}.zip`,
        undefined,
        `${dashboard.slug || 'dashboard'}-reports.zip`,
        'GET',
      )
      return job
    },
    onSuccess: (job) => {
      const skipped = (job.result?.skipped as unknown[] | undefined)?.length ?? 0
      toast.push(
        skipped
          ? `Reports downloaded. ${skipped} could not be built - see the job for which.`
          : 'Reports downloaded.',
        skipped ? 'info' : 'success',
      )
    },
    onError: (error: Error) => toast.push(error.message, 'error'),
  })
  const toast = useToast()
  const [busy, setBusy] = useState(false)
  return (
    <div className="mb-4 rounded-card border border-ink-200 bg-ink-50 px-3 py-2.5">
      <div className="flex flex-wrap items-center gap-3">
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-ink-800">Download as a web page</p>
          <p className="text-xs text-ink-500">
            One HTML file you can put on any web host or send to somebody. Its filter
            dropdowns still work: the numbers behind every widget travel with it, as do
            the libraries that draw the charts, so it opens with no internet. A widget
            that cannot be worked out again offline - a data quality panel, a median -
            says on its face that it is showing the day it was exported. A map still
            needs the internet for its background tiles.
          </p>
          {Boolean(views.data?.length) && (
            <label className="mt-2 flex flex-wrap items-center gap-2 text-xs text-ink-600">
              Of
              <select
                className="input w-auto py-1 text-xs"
                value={view}
                onChange={(event) => setView(event.target.value)}
              >
                <option value="">everything, with the filters left open</option>
                {views.data?.map((one) => (
                  <option key={one.id} value={one.id}>
                    just {one.name}
                  </option>
                ))}
              </select>
            </label>
          )}
          {chosen && (
            <p className="mt-1.5 text-xs text-ink-500">
              The file is narrowed to {chosen.name} and carries nothing else: the rows
              outside it are never computed, so it is safe to send to whoever that
              selection belongs to. Its controls are gone rather than preset.
            </p>
          )}
        </div>
        <button
          className="btn-secondary btn-sm shrink-0"
          disabled={busy}
          onClick={async () => {
            setBusy(true)
            try {
              await downloadFile(
                `/dashboards/${dashboard.id}/export.html${view ? `?view=${view}` : ''}`,
                undefined,
                // Only a fallback: the server names the file, and names it
                // after the view, so a folder of provincial reports is not
                // fourteen copies of one name.
                `${dashboard.slug || 'dashboard'}${
                  chosen ? `-${chosen.name.toLowerCase().replace(/[^a-z0-9]+/g, '-')}` : ''
                }.html`,
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

      {controls.length > 0 && (
        <div className="mt-3 border-t border-ink-200 pt-3">
          <p className="text-sm font-medium text-ink-800">One report for each</p>
          <p className="text-xs text-ink-500">
            Writes a separate file for every value of a filter and hands them back as a
            zip, each one narrowed to its own value the way a single report is. Every
            value is a full pass over the data, so a dozen of them takes minutes.
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <select
              className="input w-auto py-1 text-xs"
              value={burstBy}
              onChange={(event) => setBurstBy(event.target.value)}
              disabled={burst.isPending}
            >
              <option value="">Choose a filter…</option>
              {controls.map((control) => (
                <option key={control.variable} value={control.variable}>
                  {control.label || control.variable}
                </option>
              ))}
            </select>
            <button
              className="btn-secondary btn-sm"
              disabled={!burstBy || burst.isPending || tooMany || howMany === 0}
              onClick={() => burst.mutate()}
            >
              {burst.isPending && <Spinner className="h-4 w-4" />}
              {burst.isPending
                ? `Writing… ${burstDone}%`
                : howMany
                  ? `Write ${howMany} reports`
                  : 'Write the reports'}
            </button>
          </div>
          {tooMany && (
            <p className="mt-1.5 text-xs text-red-600">
              That filter has {howMany} values, past the limit of {counts.data?.limit}. A
              report for each would be hours of work and more files than anybody reads.
            </p>
          )}
        </div>
      )}
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
            className="input input-sm w-40"
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
