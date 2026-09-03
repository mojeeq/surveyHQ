/**
 * How a dashboard is dressed: background colour, background image, and how
 * much the image is faded so the widgets on top of it stay readable.
 *
 * A monitoring board is often left on a screen in a fieldwork office, and the
 * thing on that screen is usually meant to look like it belongs to the survey
 * it reports on rather than to the tool that drew it.
 */
import { useEffect, useRef, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { useToast } from '@/hooks/useToast'
import type { Appearance, Widget } from '@/lib/types'
import { Field, Modal } from '@/components/ui'

/** Ready-made grounds, so a usable background does not need a colour picker. */
export const BACKGROUNDS: { label: string; value: string }[] = [
  { label: 'None', value: '' },
  { label: 'Paper', value: '#f8fafc' },
  { label: 'Sand', value: '#f5f0e6' },
  { label: 'Mist', value: '#e8eef5' },
  { label: 'Slate', value: '#334155' },
  { label: 'Midnight', value: '#0f172a' },
]

/** Whether text on this colour has to be light. Null means no colour is set. */
export function isDark(color?: string): boolean {
  const hex = (color ?? '').replace('#', '')
  if (hex.length !== 6) return false
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(hex.slice(i, i + 2), 16))
  // Rec. 709 luma: the eye takes green as much brighter than blue at the same
  // number, so averaging the channels would call #0000ff light.
  return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255 < 0.5
}

/**
 * The dashboard's background image as an object URL.
 *
 * The image is behind the API's auth, and an <img> or a CSS url() cannot send
 * a bearer token, so it is fetched and handed to the browser as a blob. The
 * version stamp is in the dependencies: the file name never changes, so
 * replacing the image would otherwise go on showing the old one.
 */
export function useBackgroundImage(basePath: string, appearance: Appearance | undefined) {
  const [url, setUrl] = useState<string | null>(null)
  const name = appearance?.background_image
  const version = appearance?.background_version

  useEffect(() => {
    if (!name) {
      setUrl(null)
      return
    }
    let objectUrl: string | null = null
    let cancelled = false
    api
      .getBlob(`${basePath}/background`)
      .then((blob) => {
        if (cancelled) return
        objectUrl = URL.createObjectURL(blob)
        setUrl(objectUrl)
      })
      // A missing or unreadable background is not worth an error banner over
      // the dashboard it is only the backdrop to.
      .catch(() => setUrl(null))
    return () => {
      cancelled = true
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [basePath, name, version])

  return url
}

/** The CSS for a canvas carrying this appearance, image included. */
export function canvasStyle(
  appearance: Appearance | undefined,
  imageUrl: string | null,
): React.CSSProperties | undefined {
  const color = appearance?.background_color
  if (!color && !imageUrl) return undefined

  const fit = appearance?.background_fit ?? 'cover'
  const fade = Number(appearance?.fade ?? 0)
  const style: React.CSSProperties = { backgroundColor: color || undefined }
  if (imageUrl) {
    // The veil is a gradient of one colour laid over the image in the same
    // property, which is how an image is dimmed without a second element
    // sitting between the background and the widgets.
    const veil = fade > 0 ? `linear-gradient(rgba(255,255,255,${fade}),rgba(255,255,255,${fade})),` : ''
    style.backgroundImage = `${veil}url(${imageUrl})`
    style.backgroundSize = fit === 'tile' ? 'auto' : fit
    style.backgroundRepeat = fit === 'tile' ? 'repeat' : 'no-repeat'
    style.backgroundPosition = 'center'
  }
  return style
}

export default function AppearanceModal({
  dashboardId,
  appearance,
  widgets,
  onClose,
}: {
  dashboardId: string
  appearance: Appearance
  /** Every widget, so a change of column count can carry them with it. */
  widgets: Widget[]
  onClose: () => void
}) {
  const toast = useToast()
  const queryClient = useQueryClient()
  const fileInput = useRef<HTMLInputElement>(null)
  const [draft, setDraft] = useState<Appearance>({
    background_fit: 'cover',
    fade: 0,
    columns: 12,
    row_height: 74,
    canvas_width: 0,
    ...appearance,
  })

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['dashboard', dashboardId] })
  }

  const save = useMutation({
    mutationFn: (next: Appearance) => {
      const before = Number(appearance.columns) || 12
      const after = Number(next.columns) || 12
      if (before === after) {
        return api.patch(`/dashboards/${dashboardId}`, { appearance: next })
      }
      // Widget positions are in columns, not pixels, so changing the count
      // without moving them would halve every widget on the way to 24 and
      // overflow every one on the way back. Scaled, they stay where they look.
      const scale = after / before
      return api.patch(`/dashboards/${dashboardId}`, {
        appearance: next,
        widgets: widgets.map((widget) => {
          const layout = widget.layout ?? {}
          const w = Math.max(1, Math.min(after, Math.round(Number(layout.w ?? 6) * scale)))
          return {
            id: widget.id,
            title: widget.title,
            widget_type: widget.widget_type,
            chart_id: widget.chart_id,
            indicator_id: widget.indicator_id,
            dataset_id: widget.dataset_id,
            config: widget.config,
            position: widget.position,
            page: widget.page ?? 0,
            layout: {
              ...layout,
              x: Math.max(0, Math.min(after - w, Math.round(Number(layout.x ?? 0) * scale))),
              w,
            },
          }
        }),
      })
    },
    onSuccess: () => {
      toast.push('Appearance saved', 'success')
      refresh()
      onClose()
    },
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  const upload = useMutation({
    mutationFn: (file: File) => {
      const form = new FormData()
      form.append('file', file)
      return api.put<{ appearance: Appearance }>(`/dashboards/${dashboardId}/background`, form)
    },
    onSuccess: (updated) => {
      // The stamp the server just wrote has to reach the draft, or saving the
      // rest of this form afterwards would overwrite the image away again.
      setDraft((current) => ({ ...current, ...updated.appearance }))
      toast.push('Background image uploaded', 'success')
      refresh()
    },
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  const removeImage = useMutation({
    mutationFn: () => api.delete<{ appearance: Appearance }>(`/dashboards/${dashboardId}/background`),
    onSuccess: (updated) => {
      setDraft((current) => ({
        ...current,
        ...updated.appearance,
        background_image: undefined,
        background_version: undefined,
      }))
      toast.push('Background image removed', 'info')
      refresh()
    },
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  const color = draft.background_color ?? ''

  return (
    <Modal
      open
      onClose={onClose}
      title="Dashboard appearance"
      footer={
        <>
          <button className="btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button className="btn-primary" onClick={() => save.mutate(draft)}>
            Save
          </button>
        </>
      }
    >
      <Field
        label="Canvas width"
        hint="Wider than the window gives more room to spread out, and scrolls sideways to reach it."
      >
        <select
          className="input"
          value={String(draft.canvas_width ?? 0)}
          onChange={(event) =>
            setDraft({ ...draft, canvas_width: Number(event.target.value) })
          }
        >
          <option value="0">Fit the window</option>
          <option value="1600">Wide (1600px)</option>
          <option value="2000">Wider (2000px)</option>
          <option value="2600">Widest (2600px)</option>
        </select>
      </Field>

      <div className="grid gap-x-4 sm:grid-cols-2">
        <Field
          label="Columns"
          hint="More columns place widgets more finely. Existing widgets move with it."
        >
          <select
            className="input"
            value={String(draft.columns ?? 12)}
            onChange={(event) => setDraft({ ...draft, columns: Number(event.target.value) })}
          >
            <option value="12">12 — standard</option>
            <option value="16">16 — finer</option>
            <option value="24">24 — finest</option>
          </select>
        </Field>
        <Field label="Row height" hint="Taller rows make every widget taller.">
          <select
            className="input"
            value={String(draft.row_height ?? 74)}
            onChange={(event) => setDraft({ ...draft, row_height: Number(event.target.value) })}
          >
            <option value="56">Compact</option>
            <option value="74">Standard</option>
            <option value="96">Tall</option>
          </select>
        </Field>
      </div>

      <Field label="Background colour">
        <div className="flex flex-wrap items-center gap-2">
          {BACKGROUNDS.map((option) => (
            <button
              key={option.label}
              type="button"
              title={option.label}
              aria-label={option.label}
              aria-pressed={color === option.value}
              onClick={() => setDraft({ ...draft, background_color: option.value })}
              className={`h-8 w-8 rounded-full border-2 transition ${
                color === option.value ? 'border-brand-600 ring-2 ring-brand-200' : 'border-ink-200'
              }`}
              style={{
                backgroundColor: option.value || '#ffffff',
                backgroundImage: option.value
                  ? undefined
                  : 'linear-gradient(45deg,transparent 45%,#ef4444 45%,#ef4444 55%,transparent 55%)',
              }}
            />
          ))}
          <input
            type="color"
            className="h-8 w-12 cursor-pointer rounded border border-ink-200 bg-white"
            title="Any other colour"
            value={color || '#ffffff'}
            onChange={(event) => setDraft({ ...draft, background_color: event.target.value })}
          />
        </div>
      </Field>

      <Field
        label="Background image"
        hint="PNG, JPEG, GIF or WebP, up to 8 MB. It sits behind the widgets."
      >
        <div className="flex flex-wrap items-center gap-2">
          <input
            ref={fileInput}
            type="file"
            accept="image/png,image/jpeg,image/gif,image/webp"
            className="hidden"
            onChange={(event) => {
              const file = event.target.files?.[0]
              if (file) upload.mutate(file)
              event.target.value = ''
            }}
          />
          <button
            className="btn-secondary btn-sm"
            onClick={() => fileInput.current?.click()}
            disabled={upload.isPending}
          >
            {upload.isPending
              ? 'Uploading…'
              : draft.background_image
                ? 'Replace image'
                : 'Choose an image'}
          </button>
          {draft.background_image && (
            <button
              className="btn-ghost btn-sm text-red-600"
              onClick={() => removeImage.mutate()}
              disabled={removeImage.isPending}
            >
              Remove image
            </button>
          )}
        </div>
      </Field>

      {draft.background_image && (
        <>
          <Field label="How the image fills the page">
            <select
              className="input"
              value={draft.background_fit ?? 'cover'}
              onChange={(event) =>
                setDraft({ ...draft, background_fit: event.target.value as Appearance['background_fit'] })
              }
            >
              <option value="cover">Fill the page, cropping if it has to</option>
              <option value="contain">Fit the whole image in</option>
              <option value="tile">Repeat it</option>
            </select>
          </Field>
          <Field
            label={`Fade: ${Math.round((draft.fade ?? 0) * 100)}%`}
            hint="Washes the image out so charts and tables on top of it stay readable."
          >
            <input
              type="range"
              className="w-full"
              min={0}
              max={0.9}
              step={0.05}
              value={draft.fade ?? 0}
              onChange={(event) => setDraft({ ...draft, fade: Number(event.target.value) })}
            />
          </Field>
        </>
      )}
    </Modal>
  )
}
