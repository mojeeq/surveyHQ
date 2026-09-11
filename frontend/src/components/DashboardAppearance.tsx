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
import ColorPicker from '@/components/ColorPicker'

/** Ready-made grounds, so a usable background does not need a colour picker. */
/** Title faces, as stacks rather than downloads.
 *
 *  Every one of these is already on the machine, so a dashboard on a field
 *  office screen with no internet still renders in the face it was designed
 *  in - which a webfont would not.
 */
export const TITLE_FONTS: { label: string; value: string; stack: string }[] = [
  { label: 'Interface', value: '', stack: '' },
  {
    label: 'Grotesque',
    value: 'grotesque',
    stack: '"Helvetica Neue", Helvetica, Arial, sans-serif',
  },
  {
    label: 'Serif',
    value: 'serif',
    stack: 'Georgia, "Times New Roman", "Nimbus Roman", serif',
  },
  {
    label: 'Slab',
    value: 'slab',
    stack: '"Rockwell", "Roboto Slab", "DejaVu Serif", Georgia, serif',
  },
  {
    label: 'Monospace',
    value: 'mono',
    stack: 'ui-monospace, "SFMono-Regular", Menlo, "DejaVu Sans Mono", monospace',
  },
]

export function titleFontStack(value?: string): string | undefined {
  return TITLE_FONTS.find((f) => f.value === value)?.stack || undefined
}

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
export function useBackgroundImage(
  basePath: string,
  appearance: Appearance | undefined,
  kind: 'background' | 'logo' = 'background',
) {
  const [url, setUrl] = useState<string | null>(null)
  const name = kind === 'logo' ? appearance?.logo_image : appearance?.background_image
  const version = kind === 'logo' ? appearance?.logo_version : appearance?.background_version

  useEffect(() => {
    if (!name) {
      setUrl(null)
      return
    }
    let objectUrl: string | null = null
    let cancelled = false
    api
      .getBlob(`${basePath}/${kind}`)
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
  }, [basePath, kind, name, version])

  return url
}

/**
 * A flat colour or a two-colour gradient, as one CSS background.
 *
 * The gloss on top is the same curve the cards and buttons carry, laid over
 * the colour in the same property rather than added as a class: `.aero-gloss`
 * sets `background-image`, and so does a gradient, so one of the two would
 * have won and the other would have been the one that disappeared.
 */
export function bandStyle(
  from?: string,
  to?: string,
  angle?: number,
  gloss = true,
): React.CSSProperties | undefined {
  if (!from) return undefined
  const sheen = gloss
    ? 'linear-gradient(to bottom, rgba(255,255,255,0.16) 0%, rgba(255,255,255,0.03) 46%, ' +
      'rgba(0,0,0,0.02) 54%, rgba(0,0,0,0.07) 100%),'
    : ''
  const colour = to
    ? `linear-gradient(${angle ?? 135}deg, ${from}, ${to})`
    : `linear-gradient(${from}, ${from})`
  return { backgroundColor: from, backgroundImage: `${sheen}${colour}` }
}

/**
 * Ready-made looks.
 *
 * Six choices rather than eight colour pickers. Dressing a board well from
 * scratch means picking a page ground, a masthead, a canvas, a tab band and a
 * filter bar that all agree, and getting one of the five wrong is what makes a
 * dashboard look worse than the plain grey it started as. These were picked
 * together, and every one of them is still only a starting point: each field
 * stays editable underneath.
 *
 * Each look is a patch, not a whole appearance - the grid, the logo, the title
 * size and the widget opacity are the board's own and are not touched.
 */
export const LOOKS: { key: string; label: string; note: string; patch: Appearance }[] = [
  {
    key: 'plain',
    label: 'Plain',
    note: 'The default grey, with no band and no ground.',
    patch: {
      page_background: '',
      page_background_2: '',
      header_background: '',
      header_background_2: '',
      background_color: '',
      tab_background: '',
      tab_color: '',
      filter_background: '',
      filter_color: '',
    },
  },
  {
    key: 'paper',
    label: 'Paper',
    note: 'A dark masthead over a pale page. The report look.',
    patch: {
      page_background: '#edf0f4',
      page_background_2: '#dfe5ec',
      page_angle: 160,
      header_background: '#1f2a37',
      header_background_2: '#38495e',
      header_angle: 135,
      background_color: '#f7f8fa',
      tab_background: '#e6ebf1',
      tab_color: '#1f2a37',
      filter_background: '#ffffff',
      filter_color: '#4a5565',
    },
  },
  {
    key: 'harbour',
    label: 'Harbour',
    note: 'Deep sea blue, for a board that hangs in an office.',
    patch: {
      page_background: '#0a2135',
      page_background_2: '#0f3a5c',
      page_angle: 160,
      header_background: '#0d4b74',
      header_background_2: '#1c84bd',
      header_angle: 120,
      background_color: '#0e2d47',
      tab_background: '#12395a',
      tab_color: '#d7e8f5',
      filter_background: '#12395a',
      filter_color: '#c2dcee',
    },
  },
  {
    key: 'forest',
    label: 'Forest',
    note: 'Green, and dark enough to read a chart against.',
    patch: {
      page_background: '#0d1e17',
      page_background_2: '#14291f',
      page_angle: 160,
      header_background: '#14503a',
      header_background_2: '#248059',
      header_angle: 120,
      background_color: '#11251c',
      tab_background: '#183326',
      tab_color: '#d3e8dd',
      filter_background: '#183326',
      filter_color: '#bcd8c9',
    },
  },
  {
    key: 'ochre',
    label: 'Ochre',
    note: 'Warm earth, which suits a printed cover page.',
    patch: {
      page_background: '#241a12',
      page_background_2: '#33261a',
      page_angle: 160,
      header_background: '#7b4818',
      header_background_2: '#bf7d2c',
      header_angle: 120,
      background_color: '#2b1f15',
      tab_background: '#3a2b1d',
      tab_color: '#f0dfc6',
      filter_background: '#3a2b1d',
      filter_color: '#e0cbab',
    },
  },
  {
    key: 'midnight',
    label: 'Midnight',
    note: 'Near black, for a screen left on overnight.',
    patch: {
      page_background: '#0b0f14',
      page_background_2: '#12181f',
      page_angle: 160,
      header_background: '#161f2b',
      header_background_2: '#293b52',
      header_angle: 120,
      background_color: '#101720',
      tab_background: '#1a242f',
      tab_color: '#cbd5e1',
      filter_background: '#1a242f',
      filter_color: '#b6c2d0',
    },
  },
]

/**
 * Paint the ground the whole page sits on, for as long as this board is open.
 *
 * Written as a custom property on the document rather than as a style on an
 * element, because the thing that has to be painted is the shell around the
 * board - the margin outside <main> - and a dashboard does not own that
 * element. The shell opts in by carrying `.app-ground`; every other page is
 * untouched, and leaving the dashboard puts the grey back.
 */
export function usePageGround(image?: string) {
  useEffect(() => {
    if (!image) return
    const root = document.documentElement
    root.style.setProperty('--app-ground', image)
    return () => {
      root.style.removeProperty('--app-ground')
    }
  }, [image])
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

/**
 * The two colours and the angle that make one band.
 *
 * A second colour is what turns a flat panel into a gradient, so the angle
 * only appears once there is something for it to run between - an angle
 * control on a single colour is a control that does nothing.
 */
function BandFields({
  label,
  hint,
  from,
  to,
  angle,
  onChange,
}: {
  label: string
  hint: string
  from: string
  to: string
  angle: number
  onChange: (next: { from?: string; to?: string; angle?: number }) => void
}) {
  return (
    <Field label={label} hint={hint}>
      <div className="space-y-2">
        {/* Two identical grids of swatches one above the other are two grids
            nobody can tell apart, and the picker's own label is read out
            rather than drawn. So each one is captioned. */}
        <p className="text-[11px] uppercase tracking-wide text-ink-400">Colour</p>
        <ColorPicker
          label={`${label} colour`}
          value={from}
          onChange={(next) => onChange({ from: next, ...(next ? {} : { to: '' }) })}
          allowNone
          noneLabel="None"
        />
        {from && (
          <>
            <p className="pt-1 text-[11px] uppercase tracking-wide text-ink-400">
              Second colour, for a gradient
            </p>
            <ColorPicker
              label={`${label} second colour`}
              value={to}
              onChange={(next) => onChange({ to: next })}
              allowNone
              noneLabel="Flat, with no gradient"
            />
            {to && (
              <label className="block text-xs text-ink-500">
                Gradient angle: {angle}&deg;
                <input
                  type="range"
                  className="w-full"
                  min={0}
                  max={350}
                  step={10}
                  value={angle}
                  onChange={(event) => onChange({ angle: Number(event.target.value) })}
                />
              </label>
            )}
          </>
        )}
        <div
          className="h-10 rounded-control border border-ink-200"
          style={bandStyle(from || '#e6e8ec', to || undefined, angle)}
          aria-hidden="true"
        />
      </div>
    </Field>
  )
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
  const logoInput = useRef<HTMLInputElement>(null)
  const [draft, setDraft] = useState<Appearance>({
    background_fit: 'cover',
    fade: 0,
    columns: 12,
    row_height: 74,
    canvas_width: 0,
    widget_opacity: 1,
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

  const uploadLogo = useMutation({
    mutationFn: (file: File) => {
      const form = new FormData()
      form.append('file', file)
      return api.put<{ appearance: Appearance }>(`/dashboards/${dashboardId}/logo`, form)
    },
    onSuccess: (updated) => {
      setDraft((current) => ({ ...current, ...updated.appearance }))
      toast.push('Logo uploaded', 'success')
      refresh()
    },
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  const removeLogo = useMutation({
    mutationFn: () => api.delete<{ appearance: Appearance }>(`/dashboards/${dashboardId}/logo`),
    onSuccess: (updated) => {
      setDraft((current) => ({
        ...current,
        ...updated.appearance,
        logo_image: undefined,
        logo_version: undefined,
      }))
      toast.push('Logo removed', 'info')
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
      <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-ink-500">
        Ready-made looks
      </p>

      <Field
        label="Start from one of these"
        hint="Each one sets the page, the title band, the board and the filter bar together. Everything below stays editable afterwards."
      >
        <div className="flex flex-wrap gap-2">
          {LOOKS.map((look) => (
            <button
              key={look.key}
              className="w-[104px] overflow-hidden rounded-control border border-ink-200 p-0 text-left hover:border-brand-500"
              title={look.note}
              onClick={() => setDraft({ ...draft, ...look.patch })}
            >
              <span
                className="block h-7"
                style={bandStyle(
                  look.patch.header_background || '#e6e8ec',
                  look.patch.header_background_2 || undefined,
                  look.patch.header_angle,
                )}
              />
              <span
                className="block h-5"
                style={bandStyle(
                  look.patch.page_background || '#eceef1',
                  look.patch.page_background_2 || undefined,
                  look.patch.page_angle,
                  false,
                )}
              />
              <span className="block bg-white px-2 py-1 text-[11px] text-ink-700">
                {look.label}
              </span>
            </button>
          ))}
        </div>
      </Field>

      <p className="mb-3 mt-5 border-t border-ink-200 pt-4 text-xs font-semibold uppercase tracking-wide text-ink-500">
        Header
      </p>

      <BandFields
        label="Title band"
        hint="A band behind the dashboard's name. With one set, the buttons move to a row of their own underneath it."
        from={draft.header_background ?? ''}
        to={draft.header_background_2 ?? ''}
        angle={draft.header_angle ?? 135}
        onChange={(next) =>
          setDraft({
            ...draft,
            ...(next.from === undefined ? {} : { header_background: next.from }),
            ...(next.to === undefined ? {} : { header_background_2: next.to }),
            ...(next.angle === undefined ? {} : { header_angle: next.angle }),
          })
        }
      />

      <Field
        label="Logo"
        hint="Shown beside the dashboard's title, and on its shared link. PNG, JPEG, GIF or WebP, up to 8 MB."
      >
        <input
          ref={logoInput}
          type="file"
          accept="image/png,image/jpeg,image/gif,image/webp"
          className="hidden"
          onChange={(event) => {
            const file = event.target.files?.[0]
            if (file) uploadLogo.mutate(file)
            event.target.value = ''
          }}
        />
        <div className="flex items-center gap-2">
          <button
            className="btn-secondary btn-sm"
            onClick={() => logoInput.current?.click()}
            disabled={uploadLogo.isPending}
          >
            {uploadLogo.isPending
              ? 'Uploading…'
              : draft.logo_image
                ? 'Replace logo'
                : 'Upload a logo'}
          </button>
          {draft.logo_image && (
            <button
              className="btn-ghost btn-sm text-red-600"
              onClick={() => removeLogo.mutate()}
              disabled={removeLogo.isPending}
            >
              Remove
            </button>
          )}
        </div>
      </Field>

      {draft.logo_image && (
        <Field label={`Logo height: ${draft.logo_height ?? 32}px`}>
          <input
            type="range"
            className="w-full"
            min={20}
            max={96}
            step={4}
            value={draft.logo_height ?? 32}
            onChange={(event) =>
              setDraft({ ...draft, logo_height: Number(event.target.value) })
            }
          />
        </Field>
      )}

      <div className="grid grid-cols-2 gap-3">
        <Field label={`Title size: ${draft.title_size ?? 24}px`}>
          <input
            type="range"
            className="w-full"
            min={16}
            max={64}
            step={2}
            value={draft.title_size ?? 24}
            onChange={(event) => setDraft({ ...draft, title_size: Number(event.target.value) })}
          />
        </Field>
        <Field label="Title font">
          <select
            className="input"
            value={draft.title_font ?? ''}
            onChange={(event) => setDraft({ ...draft, title_font: event.target.value })}
          >
            {TITLE_FONTS.map((font) => (
              <option key={font.value} value={font.value}>
                {font.label}
              </option>
            ))}
          </select>
        </Field>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <Field label="Title colour">
          <div className="flex items-center gap-2">
            <input
              type="color"
              className="h-9 w-12 cursor-pointer rounded-control border border-ink-200"
              value={draft.title_color || '#333333'}
              onChange={(event) => setDraft({ ...draft, title_color: event.target.value })}
            />
            {draft.title_color && (
              <button
                className="btn-ghost btn-sm"
                onClick={() => setDraft({ ...draft, title_color: undefined })}
              >
                Default
              </button>
            )}
          </div>
        </Field>
        <Field label="Alignment">
          <select
            className="input"
            value={draft.title_align ?? 'left'}
            onChange={(event) =>
              setDraft({ ...draft, title_align: event.target.value as 'left' | 'center' })
            }
          >
            <option value="left">Left</option>
            <option value="center">Centred</option>
          </select>
        </Field>
      </div>

      <label className="mb-3 flex items-center gap-2 text-sm text-ink-700">
        <input
          type="checkbox"
          checked={Boolean(draft.header_rule)}
          onChange={(event) => setDraft({ ...draft, header_rule: event.target.checked })}
        />
        A rule under the header
      </label>
      <label className="mb-4 flex items-center gap-2 text-sm text-ink-700">
        <input
          type="checkbox"
          checked={Boolean(draft.hide_subtitle)}
          onChange={(event) => setDraft({ ...draft, hide_subtitle: event.target.checked })}
        />
        Hide the description under the title
      </label>

      <p className="mb-3 mt-5 border-t border-ink-200 pt-4 text-xs font-semibold uppercase tracking-wide text-ink-500">
        Page
      </p>

      <BandFields
        label="Page ground"
        hint="What is painted behind the whole page, around the board. It stays on this dashboard: every other page keeps the usual grey."
        from={draft.page_background ?? ''}
        to={draft.page_background_2 ?? ''}
        angle={draft.page_angle ?? 160}
        onChange={(next) =>
          setDraft({
            ...draft,
            ...(next.from === undefined ? {} : { page_background: next.from }),
            ...(next.to === undefined ? {} : { page_background_2: next.to }),
            ...(next.angle === undefined ? {} : { page_angle: next.angle }),
          })
        }
      />

      <p className="mb-3 mt-5 border-t border-ink-200 pt-4 text-xs font-semibold uppercase tracking-wide text-ink-500">
        Canvas
      </p>

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
            <option value="12">12 - standard</option>
            <option value="16">16 - finer</option>
            <option value="24">24 - finest</option>
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

      <Field
        label={`Widget transparency: ${Math.round((1 - (draft.widget_opacity ?? 1)) * 100)}%`}
        hint="Lets the background through the widgets. It stops at 70% because the text on them has to stay readable."
      >
        <input
          type="range"
          className="w-full"
          min={0}
          max={0.7}
          step={0.05}
          value={1 - (draft.widget_opacity ?? 1)}
          onChange={(event) =>
            setDraft({ ...draft, widget_opacity: 1 - Number(event.target.value) })
          }
        />
      </Field>

      <Field
        label="Behind the page tabs"
        hint="A band under the tab strip. Worth setting when the background is close to the colour of the text on it."
      >
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            className={`h-8 rounded border-2 px-3 text-xs ${
              draft.tab_background ? 'border-ink-200 text-ink-600' : 'border-brand-600 text-brand-700'
            }`}
            onClick={() => setDraft({ ...draft, tab_background: '' })}
          >
            None
          </button>
          {['#ffffff', '#0f172a', '#334155', '#f8fafc'].map((colour) => (
            <button
              key={colour}
              type="button"
              aria-label={`Tab band ${colour}`}
              aria-pressed={draft.tab_background === colour}
              onClick={() => setDraft({ ...draft, tab_background: colour })}
              className={`h-8 w-8 rounded border-2 ${
                draft.tab_background === colour
                  ? 'border-brand-600 ring-2 ring-brand-200'
                  : 'border-ink-200'
              }`}
              style={{ backgroundColor: colour }}
            />
          ))}
          <input
            type="color"
            className="h-8 w-12 cursor-pointer rounded border border-ink-200 bg-white"
            title="Any other colour"
            value={draft.tab_background || '#ffffff'}
            onChange={(event) => setDraft({ ...draft, tab_background: event.target.value })}
          />
        </div>
      </Field>

      <Field label="Background colour">
        <ColorPicker
          value={color}
          onChange={(next) => setDraft({ ...draft, background_color: next })}
          allowNone
          noneLabel="No background colour"
        />
      </Field>

      <Field
        label="Filter bar colour"
        hint="The strip of filters above the widgets. White by default, which can float oddly over a coloured background."
      >
        <ColorPicker
          value={draft.filter_background ?? ''}
          onChange={(next) => setDraft({ ...draft, filter_background: next })}
          allowNone
          noneLabel="White"
        />
      </Field>

      <Field
        label="Filter label colour"
        hint="The names beside the dropdowns. Left alone they are grey, which a dark filter bar swallows."
      >
        <ColorPicker
          value={draft.filter_color ?? ''}
          onChange={(next) => setDraft({ ...draft, filter_color: next })}
          allowNone
          noneLabel="Default grey"
        />
      </Field>

      <Field
        label="Page tab colour"
        hint="The page names. Left alone the platform picks black or white from what is behind them, which is usually right and occasionally not."
      >
        <ColorPicker
          value={draft.tab_color ?? ''}
          onChange={(next) => setDraft({ ...draft, tab_color: next })}
          allowNone
          noneLabel="Choose it for me"
        />
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
