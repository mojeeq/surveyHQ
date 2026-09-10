/**
 * The conversation about one widget.
 *
 * A monitoring board raises questions - "why is Torba low", "does this include
 * allowances" - and those questions were being asked in email beside the
 * board, where the next person to open it never saw them. This puts them on
 * the widget they are about.
 *
 * A comment belongs to the reading it was made under as well as to the widget.
 * Said while the board is narrowed to Malampa, it is about Malampa, so it is
 * shown under that view and not beside another province's numbers. A note made
 * on the board as it opens carries no view and is shown everywhere, because a
 * general remark is true whatever is selected.
 */

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { relativeTime } from '@/lib/format'
import { useAuth } from '@/hooks/useAuth'
import { useToast } from '@/hooks/useToast'
import type { WidgetComment } from '@/lib/types'
import { Modal } from '@/components/ui'

/** The query key every part of this feature reads and invalidates. */
export const commentsKey = (dashboardId: string, viewId: string) => [
  'widget-comments',
  dashboardId,
  viewId,
]

/**
 * Every comment on the board under the reading being looked at.
 *
 * Fetched once for the whole board rather than once per widget: a page with
 * ten widgets on it would otherwise open ten requests to say that nine of them
 * have nothing to show.
 */
export function useComments(dashboardId: string, viewId: string, enabled: boolean) {
  return useQuery({
    queryKey: commentsKey(dashboardId, viewId),
    queryFn: () =>
      api.get<WidgetComment[]>(
        `/dashboards/${dashboardId}/comments${viewId ? `?view_id=${viewId}` : ''}`,
      ),
    enabled,
  })
}

/** Whether a comment has been changed since it was posted.
 *
 *  Not a bare inequality: the two timestamps are written by separate defaults
 *  a few microseconds apart, so every comment came back claiming to have been
 *  edited the moment it was made. A couple of seconds is well under how long
 *  it takes anybody to notice a typo and well over that gap.
 */
function wasEdited(comment: WidgetComment): boolean {
  const made = Date.parse(comment.created_at)
  const changed = Date.parse(comment.updated_at)
  return Number.isFinite(made) && Number.isFinite(changed) && changed - made > 2000
}

/** The comments on one widget, threaded: each question with its answers. */
function threaded(comments: WidgetComment[]): {
  parent: WidgetComment
  replies: WidgetComment[]
}[] {
  const tops = comments.filter((comment) => !comment.parent_id)
  return tops.map((parent) => ({
    parent,
    replies: comments.filter((comment) => comment.parent_id === parent.id),
  }))
}

export function WidgetComments({
  dashboardId,
  widgetId,
  widgetTitle,
  viewId,
  viewName,
  comments,
  onClose,
}: {
  dashboardId: string
  widgetId: string
  widgetTitle: string
  /** The saved view open on the board, which a new comment is said under. */
  viewId: string
  viewName: string
  /** This widget's comments, already fetched for the whole board. */
  comments: WidgetComment[]
  onClose: () => void
}) {
  const toast = useToast()
  const { user, can } = useAuth()
  const queryClient = useQueryClient()
  const [draft, setDraft] = useState('')
  const [replyTo, setReplyTo] = useState('')
  const [replyDraft, setReplyDraft] = useState('')
  const [editing, setEditing] = useState('')
  const [editDraft, setEditDraft] = useState('')
  const [showResolved, setShowResolved] = useState(false)

  const refresh = () =>
    queryClient.invalidateQueries({ queryKey: commentsKey(dashboardId, viewId) })

  const say = useMutation({
    mutationFn: (payload: { body: string; parent_id?: string }) =>
      api.post<WidgetComment>(`/dashboards/${dashboardId}/comments`, {
        widget_id: widgetId,
        // A reply belongs to the thread's reading, which the server settles;
        // sending the current view with it would be a second opinion.
        ...(payload.parent_id ? {} : { view_id: viewId || null }),
        ...payload,
      }),
    onSuccess: () => {
      setDraft('')
      setReplyDraft('')
      setReplyTo('')
      refresh()
    },
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  const change = useMutation({
    mutationFn: ({ id, ...body }: { id: string; body?: string; is_resolved?: boolean }) =>
      api.patch(`/dashboards/${dashboardId}/comments/${id}`, body),
    onSuccess: () => {
      setEditing('')
      refresh()
    },
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  const remove = useMutation({
    mutationFn: (id: string) => api.delete(`/dashboards/${dashboardId}/comments/${id}`),
    onSuccess: refresh,
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  const threads = threaded(comments)
  const open = threads.filter((thread) => !thread.parent.is_resolved)
  const done = threads.filter((thread) => thread.parent.is_resolved)
  const shown = showResolved ? threads : open

  const mine = (comment: WidgetComment) => comment.created_by === user?.id
  const canRemove = (comment: WidgetComment) => mine(comment) || can('analyst')

  const line = (comment: WidgetComment, isReply: boolean) => (
    <div key={comment.id} className={isReply ? 'ml-6 border-l border-ink-200 pl-3' : ''}>
      <div className="flex flex-wrap items-baseline gap-x-2">
        <span className="text-sm font-medium text-ink-800">{comment.author_name}</span>
        <span className="text-xs text-ink-400">{relativeTime(comment.created_at)}</span>
        {wasEdited(comment) && <span className="text-xs text-ink-400">edited</span>}
        {/* Which reading it was said under, on the board-wide list where the
            two kinds sit side by side. Without it a note about one province
            and a note about the survey look identical. */}
        {!comment.view_id && viewId && (
          <span className="rounded bg-ink-100 px-1.5 text-xs text-ink-500">
            about the whole board
          </span>
        )}
      </div>
      {editing === comment.id ? (
        <div className="mt-1">
          <textarea
            className="input min-h-[64px] w-full text-sm"
            value={editDraft}
            onChange={(event) => setEditDraft(event.target.value)}
          />
          <div className="mt-1 flex gap-2">
            <button
              className="btn-primary btn-sm"
              disabled={!editDraft.trim()}
              onClick={() => change.mutate({ id: comment.id, body: editDraft.trim() })}
            >
              Save
            </button>
            <button className="btn-ghost btn-sm" onClick={() => setEditing('')}>
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <p className="mt-0.5 whitespace-pre-wrap text-sm text-ink-700">{comment.body}</p>
      )}
      <div className="mt-1 flex flex-wrap gap-3 text-xs">
        {!isReply && (
          <button
            className="text-brand-700 hover:underline"
            onClick={() => {
              setReplyTo(replyTo === comment.id ? '' : comment.id)
              setReplyDraft('')
            }}
          >
            Reply
          </button>
        )}
        {mine(comment) && editing !== comment.id && (
          <button
            className="text-ink-500 hover:underline"
            onClick={() => {
              setEditing(comment.id)
              setEditDraft(comment.body)
            }}
          >
            Edit
          </button>
        )}
        {!isReply && (
          <button
            className="text-ink-500 hover:underline"
            onClick={() =>
              change.mutate({ id: comment.id, is_resolved: !comment.is_resolved })
            }
          >
            {comment.is_resolved ? 'Reopen' : 'Mark as dealt with'}
          </button>
        )}
        {canRemove(comment) && (
          <button
            className="text-danger-600 hover:underline"
            onClick={() => {
              if (confirm('Delete this comment?')) remove.mutate(comment.id)
            }}
          >
            Delete
          </button>
        )}
      </div>
    </div>
  )

  return (
    <Modal
      open
      onClose={onClose}
      title={`Comments on "${widgetTitle}"`}
      footer={
        <button className="btn-secondary" onClick={onClose}>
          Close
        </button>
      }
    >
      <p className="mb-3 text-sm text-ink-500">
        {viewId
          ? `A comment left here belongs to the "${viewName}" view and is shown when that view is open. Notes made on the board itself are shown here too.`
          : 'A comment left here is about the board as it opens, and is shown under every view. To comment on one province or one week, open the saved view for it first.'}
      </p>

      {!shown.length ? (
        <p className="mb-4 text-sm text-ink-400">
          Nothing has been said about this widget yet.
        </p>
      ) : (
        <div className="mb-4 space-y-4">
          {shown.map(({ parent, replies }) => (
            <div
              key={parent.id}
              className={`rounded-card border border-ink-200 p-3 ${
                parent.is_resolved ? 'opacity-60' : ''
              }`}
            >
              {parent.is_resolved && (
                <p className="mb-1 text-xs font-medium uppercase tracking-wide text-ink-400">
                  Dealt with
                </p>
              )}
              {line(parent, false)}
              {replies.length > 0 && (
                <div className="mt-3 space-y-3">
                  {replies.map((reply) => line(reply, true))}
                </div>
              )}
              {replyTo === parent.id && (
                <div className="ml-6 mt-3 border-l border-ink-200 pl-3">
                  <textarea
                    className="input min-h-[64px] w-full text-sm"
                    placeholder="Answer this"
                    value={replyDraft}
                    onChange={(event) => setReplyDraft(event.target.value)}
                  />
                  <div className="mt-1 flex gap-2">
                    <button
                      className="btn-primary btn-sm"
                      disabled={!replyDraft.trim() || say.isPending}
                      onClick={() =>
                        say.mutate({ body: replyDraft.trim(), parent_id: parent.id })
                      }
                    >
                      Reply
                    </button>
                    <button className="btn-ghost btn-sm" onClick={() => setReplyTo('')}>
                      Cancel
                    </button>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {done.length > 0 && (
        <button
          className="mb-4 text-xs text-ink-500 hover:underline"
          onClick={() => setShowResolved(!showResolved)}
        >
          {showResolved
            ? 'Hide what has been dealt with'
            : `Show ${done.length} dealt with`}
        </button>
      )}

      <textarea
        className="input min-h-[80px] w-full text-sm"
        placeholder="Say something about these figures"
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
      />
      <button
        className="btn-primary btn-sm mt-2"
        disabled={!draft.trim() || say.isPending}
        onClick={() => say.mutate({ body: draft.trim() })}
      >
        Post comment
      </button>
    </Modal>
  )
}

/** How many open threads a widget has, for the count beside its title. */
export function openThreads(comments: WidgetComment[]): number {
  return comments.filter((comment) => !comment.parent_id && !comment.is_resolved).length
}
