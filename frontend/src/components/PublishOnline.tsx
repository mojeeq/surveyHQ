/**
 * Putting this board on a website: GitHub Pages, or a web server an
 * administrator has set up for it.
 *
 * A share link needs this platform running and reachable. A published board
 * does not: it is the HTML download - filters working, the numbers behind
 * every widget, never a row - sitting on the destination's server, so this
 * platform can be a laptop on an office network that is off at night while
 * the board is read on a public site. It can follow the data, published again
 * after every import that changes what it shows.
 */
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { Badge, Spinner, Toggle } from '@/components/ui'
import { useAuth } from '@/hooks/useAuth'
import { useDialog } from '@/hooks/useDialog'
import { useToast } from '@/hooks/useToast'
import { ApiError, api } from '@/lib/api'
import { copyText } from '@/lib/clipboard'
import { relativeTime } from '@/lib/format'
import { KIND_LABEL, pageUrl, pathProblem, suggestPath } from '@/lib/publishing'
import type { Publication, PublishTarget } from '@/lib/publishing'
import type { Dashboard, DashboardSavedView } from '@/lib/types'

export default function PublishOnline({ dashboard }: { dashboard: Dashboard }) {
  const toast = useToast()
  const ask = useDialog()
  const queryClient = useQueryClient()
  const isAdmin = useAuth().user?.role === 'admin'

  const targets = useQuery({
    queryKey: ['publish-targets'],
    queryFn: () => api.get<PublishTarget[]>('/publishing/targets'),
  })
  const published = useQuery({
    queryKey: ['publications', dashboard.id],
    queryFn: () => api.get<Publication[]>(`/dashboards/${dashboard.id}/publications`),
  })
  // The same query the download above asks, so the two share one answer.
  const views = useQuery({
    queryKey: ['dashboard-views', dashboard.id, `/dashboards/${dashboard.id}`],
    queryFn: () => api.get<DashboardSavedView[]>(`/dashboards/${dashboard.id}/views`),
  })

  const [targetId, setTargetId] = useState('')
  const [viewId, setViewId] = useState('')
  // Null until somebody types one: until then it follows the board's name
  // and the view chosen, so choosing a view renames the address with it.
  const [typedPath, setTypedPath] = useState<string | null>(null)
  const [follow, setFollow] = useState(true)

  const target = targets.data?.find((one) => one.id === (targetId || targets.data?.[0]?.id))
  const view = views.data?.find((one) => one.id === viewId)
  const path = typedPath ?? suggestPath(dashboard.name, view?.name)
  const problem = pathProblem(path)
  const frontTaken = !path.trim() && Boolean(target?.settings.contents_page)
  // Already there, from this board: the way to update it is the row above.
  const already = published.data?.find(
    (one) => one.target_id === target?.id && one.path === path.trim().replace(/^\/+|\/+$/g, ''),
  )
  const willBe = target ? pageUrl(target, path) : ''

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['publications', dashboard.id] })
    queryClient.invalidateQueries({ queryKey: ['publish-targets'] })
  }

  /** On a refusal because a page somebody else put there is at the address,
   *  ask, and send it again with the yes. */
  const withReplace = async <T,>(send: (replace: boolean) => Promise<T>): Promise<T | null> => {
    try {
      return await send(false)
    } catch (error) {
      if (!(error instanceof ApiError) || error.status !== 409 || !/did not put there/.test(error.message)) {
        throw error
      }
      const sure = await ask.confirm({
        title: 'Replace the page that is there?',
        message: `${error.message.replace(/ Choose another address, or replace it\.$/, '')} Replacing it deletes that page from the server.`,
        confirmLabel: 'Replace it',
        tone: 'danger',
      })
      return sure ? send(true) : null
    }
  }

  const publish = useMutation({
    mutationFn: () =>
      withReplace((replace) =>
        api.post<Publication>(`/dashboards/${dashboard.id}/publications`, {
          target_id: target!.id,
          path: path.trim(),
          view_id: viewId,
          auto_republish: follow,
          replace_existing: replace,
        }),
      ),
    onSuccess: (made) => {
      if (!made) return
      refresh()
      setTypedPath(null)
      toast.push(
        made.url ? `Published at ${made.url}` : `Published to ${made.target_name}`,
        'success',
      )
    },
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  const again = useMutation({
    mutationFn: (one: Publication) =>
      withReplace((replace) =>
        api.post<Publication>(`/dashboards/${dashboard.id}/publications/${one.id}/publish`, {
          replace_existing: replace,
        }),
      ),
    onSuccess: (done) => {
      refresh()
      if (done) toast.push(`${done.target_name} now shows the board as it is`, 'success')
    },
    onError: (error: Error) => {
      // Marked failed on the server, with the reason, which the list shows.
      refresh()
      toast.push(error.message, 'error')
    },
  })

  const following = useMutation({
    mutationFn: ({ one, on }: { one: Publication; on: boolean }) =>
      api.patch<Publication>(`/dashboards/${dashboard.id}/publications/${one.id}`, {
        auto_republish: on,
      }),
    onSuccess: refresh,
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  const takeDown = useMutation({
    mutationFn: ({ one, keep }: { one: Publication; keep: boolean }) =>
      api.delete<{ detail: string }>(
        `/dashboards/${dashboard.id}/publications/${one.id}${keep ? '?keep_files=true' : ''}`,
      ),
    onSuccess: (result) => {
      refresh()
      toast.push(result.detail, 'success')
    },
    onError: async (error: Error, { one, keep }) => {
      if (keep) {
        toast.push(error.message, 'error')
        return
      }
      // The server could not be reached. Offer to forget it here anyway,
      // which is the way out for a server that is gone for good.
      const forget = await ask.confirm({
        title: `${one.target_name} could not be reached`,
        message: `${error.message} Remove it from this list anyway? The page stays wherever it is.`,
        confirmLabel: 'Remove from the list',
        tone: 'danger',
      })
      if (forget) takeDown.mutate({ one, keep: true })
    },
  })

  const busy = publish.isPending || again.isPending || takeDown.isPending

  return (
    <section
      aria-label="Publish to a website"
      className="mb-4 rounded-card border border-ink-200 bg-ink-50 px-3 py-2.5 dark:border-dark-200 dark:bg-dark-100"
    >
      <p className="text-sm font-medium text-ink-800 dark:text-dark-800">Publish to a website</p>
      <p className="mt-0.5 text-xs text-ink-500 dark:text-dark-500">
        Puts this board on GitHub Pages or your own web server, where it stays readable when this
        platform is not. It is the same file as the web-page download: the filters work, and it
        carries the numbers each widget shows, never a row of data.
      </p>

      {published.data?.map((one) => (
        <div
          key={one.id}
          className="mt-3 rounded-control border border-ink-200 bg-white px-3 py-2 dark:border-dark-200 dark:bg-dark-50"
        >
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="text-sm font-medium text-ink-800 dark:text-dark-800">
              {one.target_name}
            </span>
            <Badge>{KIND_LABEL[one.target_kind as keyof typeof KIND_LABEL] ?? one.target_kind}</Badge>
            {one.view_name && <Badge>{one.view_name}</Badge>}
            {one.status === 'failed' ? (
              <Badge tone="danger" icon="!">
                Last publish failed
              </Badge>
            ) : (
              <span className="text-xs text-ink-500 dark:text-dark-500">
                Published {relativeTime(one.last_published_at)}
              </span>
            )}
          </div>
          {one.url ? (
            <a
              href={one.url}
              target="_blank"
              rel="noreferrer"
              className="mt-1 block truncate text-xs text-brand-700 hover:underline dark:text-brand-400"
            >
              {one.url}
            </a>
          ) : (
            <p className="mt-1 text-xs text-ink-500 dark:text-dark-500">
              At {one.path ? `${one.path}/` : 'the front of the folder'}. The destination has no web
              address set, so there is no link to show.
            </p>
          )}
          {one.status === 'failed' && one.last_error && (
            <p className="mt-1 text-xs text-red-700 dark:text-red-300">
              {one.last_error} The page that was there before is still online.
            </p>
          )}
          {one.notes.map((note) => (
            <p key={note} className="mt-1 text-xs text-amber-800 dark:text-amber-200">
              {note}
            </p>
          ))}
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <Toggle
              checked={one.auto_republish}
              onChange={(on) => following.mutate({ one, on })}
              label="Publish again after each import"
            />
            <span className="ml-auto flex flex-wrap gap-1">
              {one.url && (
                <button
                  className="btn-ghost btn-sm"
                  onClick={async () => {
                    if (await copyText(one.url)) toast.push('Link copied', 'success')
                  }}
                >
                  Copy link
                </button>
              )}
              <button className="btn-ghost btn-sm" disabled={busy} onClick={() => again.mutate(one)}>
                {again.isPending && again.variables?.id === one.id && <Spinner className="h-3.5 w-3.5" />}
                Publish again
              </button>
              <button
                className="btn-ghost btn-sm text-red-700 dark:text-red-300"
                disabled={busy}
                onClick={async () => {
                  const sure = await ask.confirm({
                    title: `Take it down from ${one.target_name}?`,
                    message:
                      'The page is deleted from the server, and its address stops working. ' +
                      'The board here is not touched.',
                    confirmLabel: 'Unpublish',
                    tone: 'danger',
                  })
                  if (sure) takeDown.mutate({ one, keep: false })
                }}
              >
                Unpublish
              </button>
            </span>
          </div>
        </div>
      ))}

      {targets.isSuccess && !targets.data.length ? (
        <p className="mt-3 text-xs text-ink-600 dark:text-dark-600">
          No website is set up for publishing yet.{' '}
          {isAdmin ? (
            <>
              Add GitHub Pages or a web server under{' '}
              <Link to="/admin" className="font-medium text-brand-700 hover:underline dark:text-brand-400">
                Administration, Publishing
              </Link>
              .
            </>
          ) : (
            'An administrator adds them under Administration, Publishing.'
          )}
        </p>
      ) : target ? (
        <div className="mt-3 border-t border-ink-200 pt-3 dark:border-dark-200">
          <div className="grid gap-2 sm:grid-cols-2">
            <label className="text-xs text-ink-600 dark:text-dark-600">
              To
              <select
                className="input mt-1"
                value={target.id}
                onChange={(event) => setTargetId(event.target.value)}
              >
                {targets.data?.map((one) => (
                  <option key={one.id} value={one.id}>
                    {one.name} ({KIND_LABEL[one.kind]})
                  </option>
                ))}
              </select>
            </label>
            <label className="text-xs text-ink-600 dark:text-dark-600">
              At the address
              <input
                className="input mt-1 font-mono"
                value={path}
                aria-invalid={problem || frontTaken ? true : undefined}
                onChange={(event) => setTypedPath(event.target.value)}
              />
            </label>
          </div>
          {Boolean(views.data?.length) && (
            <label className="mt-2 flex flex-wrap items-center gap-2 text-xs text-ink-600 dark:text-dark-600">
              Of
              <select
                className="input w-auto py-1 text-xs"
                value={viewId}
                onChange={(event) => setViewId(event.target.value)}
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
          {problem || frontTaken ? (
            <p className="mt-1.5 text-xs text-red-700 dark:text-red-300">
              {problem ??
                `${target.name} keeps a list of its dashboards at the front of its folder, so this board needs an address of its own.`}
            </p>
          ) : already ? (
            <p className="mt-1.5 text-xs text-ink-600 dark:text-dark-600">
              This board is already published there. Use Publish again above to update it, or
              choose another address for a second copy.
            </p>
          ) : (
            willBe && (
              <p className="mt-1.5 break-all text-xs text-ink-500 dark:text-dark-500">
                It will be at <span className="font-mono">{willBe}</span>
              </p>
            )
          )}
          <div className="mt-2 flex flex-wrap items-center gap-3">
            <Toggle checked={follow} onChange={setFollow} label="Publish again after each import" />
            <button
              className="btn-primary btn-sm ml-auto"
              disabled={busy || Boolean(problem) || frontTaken || Boolean(already)}
              onClick={() => publish.mutate()}
            >
              {publish.isPending && <Spinner className="h-4 w-4 text-white" />}
              {publish.isPending ? 'Publishing' : 'Publish'}
            </button>
          </div>
          {target.kind === 'github' && (
            <p className="mt-1.5 text-xs text-ink-500 dark:text-dark-500">
              GitHub takes a minute or so to put a new page live.
            </p>
          )}
        </div>
      ) : null}
    </section>
  )
}
