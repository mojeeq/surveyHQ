import {
keepPreviousData,
useMutation,
useQuery,
useQueryClient,
} from '@tanstack/react-query'

import { useCallback,useEffect,useMemo,useRef,useState } from 'react'


import { useParams } from 'react-router-dom'

import GridLayout,{ type Layout } from 'react-grid-layout'

import 'react-grid-layout/css/styles.css'

import 'react-resizable/css/styles.css'

import { api,ApiError } from '@/lib/api'

import { copyText } from '@/lib/clipboard'

import { useAuth } from '@/hooks/useAuth'

import { useToast } from '@/hooks/useToast'

import { CHART_THEMES } from '@/lib/charts'


import { relativeTime } from '@/lib/format'

import type {
Dashboard,
DrillLevel,
DrillStep,
Widget,
WidgetComment,
WidgetGroup
} from '@/lib/types'

import AssignProject from '@/components/AssignProject'




import ShareLinks from '@/components/ShareLinks'

import DashboardFilters,{
controlsForPage,
toFilterGroup,
type FilterControl
} from '@/components/DashboardFilters'


import {
openThreads,
useComments,
WidgetComments,
} from '@/components/WidgetComments'

import ErrorBoundary from '@/components/ErrorBoundary'


import AppearanceModal,{
bandStyle,
canvasStyle,
isDark,
titleFontStack,
useBackgroundImage,
usePageGround
} from '@/components/DashboardAppearance'

import { canDescend,CrossFilter,DrillDownModal,drilledLevel,DrillTrail,FilterControlsModal,levelLabel,SavedViews,withCrossFilter,withDrillPath } from '@/components/dashboard/filters'
import { PageTabs } from '@/components/dashboard/PageTabs'
import { appearanceOf,CANVAS_PADDING,cardStyle,COLUMNS,ROW_HEIGHT,styleOf,widgetTone } from '@/components/dashboard/shared'
import {
  boxOf,
  GROUP_BAR_ROWS,
  GroupBar,
  GroupFrames,
  groupItemId,
  isGroupItem,
  groupIdOf,
} from '@/components/dashboard/WidgetGroups'
import { PublicLinkBar,SharePasswordPrompt } from '@/components/dashboard/sharing'
import { AddWidgetModal,EditWidgetModal } from '@/components/dashboard/WidgetEditor'
import { WidgetFrame } from '@/components/dashboard/WidgetFrame'
import {
Badge,
Card,
EmptyState,
ErrorNote,
Loading,
PageHeader
} from '@/components/ui'


export default function DashboardView({ publicToken }: { publicToken?: string }) {
  const { id = '' } = useParams()
  const { can } = useAuth()
  const toast = useToast()
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [adding, setAdding] = useState(false)
  const [activePage, setActivePage] = useState(0)
  const [filterValues, setFilterValues] = useState<Record<string, string>>({})
  /** What was clicked on a chart, filtering the rest of the page by it. */
  const [picked, setPicked] = useState<CrossFilter | null>(null)
  /** How far down the board's hierarchy the reader has clicked, and where. */
  const [path, setPath] = useState<DrillStep[]>([])
  useEffect(() => {
    setPicked(null)
    setPath([])
  }, [activePage])
  const [editingFilters, setEditingFilters] = useState(false)
  const [editingDrill, setEditingDrill] = useState(false)
  /** Which saved view is on screen: the bar shows which one you opened, and a
   *  comment left while it is open belongs to it. */
  const [openedView, setOpenedView] = useState({ id: '', name: '' })
  /** The widget whose comment thread is open. */
  const [commenting, setCommenting] = useState<Widget | null>(null)
  const [editingStyle, setEditingStyle] = useState(false)
  const [editingWidget, setEditingWidget] = useState<Widget | null>(null)
  const [width, setWidth] = useState(1200)
  const [sharing, setSharing] = useState(false)

  const isPublic = Boolean(publicToken)
  const basePath = isPublic ? `/public/dashboards/${publicToken}` : `/dashboards/${id}`

  const dashboard = useQuery({
    queryKey: ['dashboard', id, publicToken],
    queryFn: () => api.get<Dashboard>(basePath),
  })

  // 401 on a public path means the link is password protected and this reader
  // has not given it yet; any other error is a real one.
  const locked =
    isPublic && (dashboard.error as ApiError | null)?.status === 401

  const filterControls: FilterControl[] = (dashboard.data?.filters ??
    []) as unknown as FilterControl[]

  const pages = (dashboard.data?.pages ?? []) as { name?: string }[]
  // A dashboard with no named pages is one unnamed page, which is what every
  // dashboard made before this feature is.
  const pageCount = Math.max(1, pages.length)
  const page = Math.min(activePage, pageCount - 1)
  const pageNames = Array.from(
    { length: pageCount },
    (_, index) => pages[index]?.name || `Page ${index + 1}`,
  )
  // Pages ask different questions, so each carries its own filters.
  const pageControls = controlsForPage(filterControls, page)

  // One hierarchy for the whole board: drilling is a question asked of the
  // page ("show me Malampa"), not of the one chart that was clicked.
  const hierarchy = (dashboard.data?.drilldown ?? []) as DrillLevel[]

  // How much board there is to arrange on. More columns is finer placement
  // rather than more room; a canvas wider than the window is more room, and
  // scrolls sideways to reach it.
  const columns = Number(appearanceOf(dashboard.data).columns) || COLUMNS
  const rowHeight = Number(appearanceOf(dashboard.data).row_height) || ROW_HEIGHT
  const fixedWidth = Number(appearanceOf(dashboard.data).canvas_width) || 0
  const declaredOpacity = appearanceOf(dashboard.data).widget_opacity
  // Opaque unless asked otherwise, and never so faint that the text on it
  // stops being readable against whatever is behind.
  const widgetOpacity = Math.min(1, Math.max(0.3, Number(declaredOpacity ?? 1)))
  const canvasWidth = Math.max(fixedWidth || width, 320)

  // The grid needs a width in pixels, and it has to keep up with the window.
  //
  // This used to read clientWidth in a callback ref, which React calls when
  // the node is attached and never again: the board was laid out for whatever
  // the window was at load and stayed that way, so widening the browser left a
  // strip of empty space and narrowing it cut the right-hand widgets off. The
  // observer goes on the ref rather than in an effect so it is attached and
  // detached with the node itself, and it catches the window, the sidebar
  // collapsing and a phone turning sideways alike - all one event to the grid.
  const watcher = useRef<ResizeObserver | null>(null)
  const measureGrid = useCallback((node: HTMLDivElement | null) => {
    watcher.current?.disconnect()
    watcher.current = null
    if (!node) return
    setWidth(node.clientWidth)
    if (typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver((entries) => {
      const measured = entries[0]?.contentRect.width
      // A container measured at nothing is a hidden tab, not a narrow one.
      // Laying the board out for a zero-width canvas would stack every widget
      // into a single column before the page has even been looked at.
      if (measured && measured > 0) setWidth(Math.round(measured))
    })
    observer.observe(node)
    watcher.current = observer
  }, [])

  const rendered = useQuery({
    // The values are part of the key, so changing a filter refetches rather
    // than showing the previous selection's numbers under the new label. So is
    // the page, whose filters are its own.
    queryKey: ['dashboard-data', id, publicToken, activePage, filterValues, picked, path],
    queryFn: () =>
      api.post<{ widgets: Record<string, any> }>(
        `${basePath}/data?drill_level=${path.length}` +
          // The widget a click was made on is left unfiltered; the widget a
          // drill was made on is not, because descending is the whole point.
          (picked ? `&every_widget_but=${picked.from}` : ''),
        withCrossFilter(
          withDrillPath(toFilterGroup(pageControls, filterValues), path),
          picked,
        ),
      ),
    enabled: Boolean(dashboard.data),
    // Keep showing the numbers already on screen while the filtered ones are
    // fetched. Every filter change is a new query key, so without this each
    // one tore the whole board down to spinners and rebuilt it - and going
    // back to a selection you had already made was smooth only because that
    // key happened to be cached. Now both directions read the same.
    placeholderData: keepPreviousData,
    refetchInterval: dashboard.data?.refresh_interval_seconds
      ? dashboard.data.refresh_interval_seconds * 1000
      : false,
  })

  // When the numbers on screen were fetched. TanStack tracks this per query,
  // so it is the render's own timestamp rather than the moment the page loaded
  // - a board left up on a wall refreshing every minute says so honestly.
  const fetchedAt = rendered.dataUpdatedAt
    ? new Date(rendered.dataUpdatedAt).toISOString()
    : ''
  // Follows the filter labels, so it reads on a dark canvas like everything
  // else the board draws on its own background.
  const asOfStyle = appearanceOf(dashboard.data).filter_color
    ? { color: appearanceOf(dashboard.data).filter_color, opacity: 0.8 }
    : undefined

  // The board's comments under the reading being looked at, fetched once for
  // every widget rather than once each. A shared link has no reader to attribute
  // a comment to, so it neither shows nor collects them.
  const comments = useComments(id, openedView.id, Boolean(dashboard.data) && !isPublic)
  const commentsFor = (widgetId: string): WidgetComment[] =>
    (comments.data ?? []).filter((comment) => comment.widget_id === widgetId)

  const saveLayout = useMutation({
    mutationFn: (widgets: Widget[]) =>
      api.patch(`/dashboards/${id}`, {
        widgets: widgets.map((widget) => ({
          id: widget.id,
          title: widget.title,
          widget_type: widget.widget_type,
          chart_id: widget.chart_id,
          indicator_id: widget.indicator_id,
          dataset_id: widget.dataset_id,
          config: widget.config,
          layout: widget.layout,
          position: widget.position,
          page: widget.page ?? 0,
          // Sent back with the rest of it. This PATCH replaces the whole
          // widget list, so a field left out is a field cleared - and leaving
          // this one out emptied every group the moment anything was dragged.
          group_id: widget.group_id ?? '',
        })),
      }),
    onSuccess: () => {
      toast.push('Layout saved', 'success')
      queryClient.invalidateQueries({ queryKey: ['dashboard', id] })
    },
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  const share = useMutation({
    mutationFn: (enable: boolean) =>
      api.post<Dashboard>(`/dashboards/${id}/share?enable=${enable}`),
    onSuccess: (updated) => {
      queryClient.invalidateQueries({ queryKey: ['dashboard', id] })
      if (updated.public_token) {
        const url = `${location.origin}/shared/${updated.public_token}`
        // Told after the attempt rather than before it: on a plain HTTP
        // deployment the browser has no clipboard object at all, and saying
        // "copied" when nothing was is worse than saying nothing.
        copyText(url).then((copied) =>
          toast.push(
            copied ? 'Public link copied to your clipboard' : 'This dashboard is now shared',
            'success',
          ),
        )
      } else {
        toast.push('Public sharing turned off', 'info')
      }
    },
  })

  const saveTheme = useMutation({
    mutationFn: (theme: string) => api.patch(`/dashboards/${id}`, { theme }),
    onSuccess: () => {
      toast.push('Palette changed', 'success')
      queryClient.invalidateQueries({ queryKey: ['dashboard', id] })
    },
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  const savePages = useMutation({
    mutationFn: (pages: { name: string }[]) => api.patch(`/dashboards/${id}`, { pages }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['dashboard', id] }),
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  const saveGroups = useMutation({
    mutationFn: (groups: WidgetGroup[]) => api.patch(`/dashboards/${id}`, { groups }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['dashboard', id] }),
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  const groupWidget = useMutation({
    mutationFn: ({
      widgetId,
      groupId,
      layout,
    }: {
      widgetId: string
      groupId: string
      layout?: Widget['layout']
    }) =>
      api.patch(`/dashboards/${id}/widgets/${widgetId}`, {
        group_id: groupId,
        ...(layout ? { layout } : {}),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['dashboard', id] }),
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  const movePage = useMutation({
    mutationFn: ({ from, to }: { from: number; to: number }) =>
      api.post(`/dashboards/${id}/pages/move`, { from, to }),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: ['dashboard', id] })
      // Stay on the page that moved rather than on the position it left.
      setActivePage(variables.to)
    },
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  const removePage = useMutation({
    mutationFn: (index: number) => api.delete(`/dashboards/${id}/pages/${index}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['dashboard', id] }),
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  const moveWidget = useMutation({
    mutationFn: ({ widgetId, page }: { widgetId: string; page: number }) =>
      api.patch(`/dashboards/${id}/widgets/${widgetId}`, { page }),
    onSuccess: (_data, variables) => {
      toast.push('Widget moved', 'success')
      queryClient.invalidateQueries({ queryKey: ['dashboard', id] })
      // Follow it, so the move can be seen rather than just reported.
      setActivePage(variables.page)
    },
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  /** The last save sent from a widget's menu, so the next one waits for it. */
  const saving = useRef<Promise<unknown>>(Promise.resolve())

  // One saved setting on a widget, changed from the widget's own menu rather
  // than through the edit dialog. The config is sent whole, because that is
  // what the endpoint stores, so the patch is merged onto what the widget is
  // already carrying at the call.
  const reconfigureWidget = useMutation({
    mutationFn: ({
      widgetId,
      config,
    }: {
      widgetId: string
      config: Record<string, unknown>
    }) => {
      // One at a time, in the order they were asked for. The endpoint stores
      // the config whole, so two of these in flight together are two writes of
      // the same field and whichever lands last decides it - which, sent in
      // parallel, need not be the one clicked last. Reopening the menu and
      // picking again before the first save returns is quick enough to do by
      // hand, and it would have left the panel showing the earlier choice.
      const next = saving.current
        .catch(() => {})
        .then(() => api.patch(`/dashboards/${id}/widgets/${widgetId}`, { config }))
      saving.current = next
      return next
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['dashboard', id] })
      // And the data behind it, because what a panel is showing decides what
      // the server sends: a quality panel asked for a trend is sent a month of
      // stored runs, and one asked for its findings is not.
      queryClient.invalidateQueries({ queryKey: ['dashboard-data', id] })
    },
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  const removeWidget = useMutation({
    mutationFn: (widgetId: string) => api.delete(`/dashboards/${id}/widgets/${widgetId}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['dashboard', id] })
      queryClient.invalidateQueries({ queryKey: ['dashboard-data', id] })
    },
  })

  const allGroups = useMemo(
    () => (dashboard.data?.groups ?? []) as WidgetGroup[],
    [dashboard.data],
  )
  /**
   * Groups a reader has folded here, which is not the same as the saved state.
   *
   * Whoever builds the board decides what it opens as, and that is saved. A
   * reader folding a group away to see past it is not editing anything and
   * usually cannot: on a share link the save comes back 403, so the group
   * would spring open again under an error message. Folding happens here
   * first and is written down only by somebody who may write it down.
   */
  const [foldedHere, setFoldedHere] = useState<Record<string, boolean>>({})

  /** Whether this reader may write the board, rather than only read it. */
  const canEditBoard = !isPublic && can('analyst')

  const groups = useMemo(
    () =>
      allGroups
        .filter((group) => (group.page ?? 0) === page)
        .map((group) => ({
          ...group,
          collapsed: foldedHere[group.id] ?? Boolean(group.collapsed),
        })),
    [allGroups, page, foldedHere],
  )
  const folded = useMemo(
    () => new Set(groups.filter((group) => group.collapsed).map((group) => group.id)),
    [groups],
  )

  const allWidgets = dashboard.data?.widgets ?? []
  const onThisPage = useMemo(
    () => allWidgets.filter((widget) => (widget.page ?? 0) === page),
    [allWidgets, page],
  )
  // A folded group's widgets are left out of the board entirely rather than
  // hidden in place: the point of folding one is the room it gives back, and a
  // hidden widget still holding its rows gives none.
  const widgets = useMemo(
    () => onThisPage.filter((widget) => !folded.has(widget.group_id || '')),
    [onThisPage, folded],
  )

  const appearance = appearanceOf(dashboard.data)
  const backgroundUrl = useBackgroundImage(basePath, appearance)
  const logoUrl = useBackgroundImage(basePath, appearance, 'logo')
  const canvas = canvasStyle(appearance, backgroundUrl)
  const onDarkGround = Boolean(canvas) && isDark(appearance.background_color)
  // The masthead, and the ground the page is mounted on. A gradient is judged
  // light or dark by the colour it starts from, which is the corner the title
  // sits in.
  const masthead = bandStyle(
    appearance.header_background,
    appearance.header_background_2,
    appearance.header_angle,
  )
  const onMasthead = isDark(appearance.header_background)
  const onDarkPage = isDark(appearance.page_background)
  const ground = bandStyle(
    appearance.page_background,
    appearance.page_background_2,
    appearance.page_angle,
    false,
  )
  usePageGround(ground?.backgroundImage as string)
  // The tabs sit on their own band when one is set, so what they have to stay
  // readable against is that band rather than the dashboard's background.
  const tabsOnDark = appearance.tab_background
    ? isDark(appearance.tab_background)
    : onDarkGround

  const layout: Layout[] = useMemo(
    () => [
      ...widgets.map((widget, index) => ({
        i: widget.id,
        x: Number(widget.layout?.x ?? (index % 2) * 6),
        y: Number(widget.layout?.y ?? Math.floor(index / 2) * 4),
        w: Number(widget.layout?.w ?? 6),
        h: Number(widget.layout?.h ?? 4),
        minW: 2,
        minH: 2,
      })),
      // A group's title bar is a grid item like any other. That is what makes
      // it draggable, resizable and something the widgets collide with,
      // without any of those being written a second time here.
      ...groups.map((group) => ({
        i: groupItemId(group),
        x: Number(group.x ?? 0),
        y: Number(group.y ?? 0),
        w: Number(group.w ?? 6),
        h: GROUP_BAR_ROWS,
        minW: 2,
        minH: GROUP_BAR_ROWS,
        maxH: GROUP_BAR_ROWS,
      })),
    ],
    [widgets, groups],
  )

  /**
   * Where everything was when a drag began, so a group can be shifted by a delta.
   *
   * Up here with the other hooks rather than beside the handler that uses it:
   * below this point the component has already returned early for a board that
   * is still loading, and a hook after a return is a hook React counts on one
   * render and not the next. It cost a white screen and "rendered more hooks
   * than during the previous render", which neither the typecheck nor the
   * build has any way to see.
   */
  const before = useRef<Map<string, Layout>>(new Map())

  /**
   * Where the grid actually put things, which is not where they are stored.
   *
   * react-grid-layout packs its items upwards, so a widget saved at row 8 with
   * nothing above it is drawn at row 6. A frame computed from the stored rows
   * is then drawn below the bar it belongs to - which is exactly what it did
   * until this was here. Only the frames use it; what is saved is still
   * decided by a drag or a resize, so tracking this changes nothing about
   * when the board is written.
   */
  const [placed, setPlaced] = useState<Layout[]>([])

  const membersOf = useCallback(
    (groupId: string) =>
      onThisPage.filter((widget) => widget.group_id === groupId).map((w) => w.id),
    [onThisPage],
  )

  if (dashboard.isLoading) return <Loading />
  // A link with a password answers 401 until it is given. That is a door, not
  // a fault, so it gets a door rather than an error banner.
  if (locked)
    return (
      <SharePasswordPrompt
        token={publicToken!}
        onUnlocked={() => {
          queryClient.invalidateQueries()
          dashboard.refetch()
        }}
      />
    )
  if (dashboard.error) return <ErrorNote error={dashboard.error} retry={dashboard.refetch} />

  const onLayoutChange = (next: Layout[], shifts?: Map<string, Layout>) => {
    if (!editing) return
    // Every widget goes back, not just this page's: the PATCH replaces the whole
    // list, so omitting the other pages would delete them.
    const updated = allWidgets.map((widget) => {
      const position = shifts?.get(widget.id) ?? next.find((item) => item.i === widget.id)
      return position
        ? { ...widget, layout: { x: position.x, y: position.y, w: position.w, h: position.h } }
        : widget
    })
    saveLayout.mutate(updated)
  }

  const rememberPositions = (current: Layout[]) => {
    before.current = new Map(current.map((item) => [item.i, { ...item }]))
  }

  /**
   * A bar and its widgets move as one.
   *
   * The grid moved the bar; every member is shifted by the same amount, from
   * where it was when the drag started rather than from where the grid has
   * just put it. Taking the live positions would add the bar's own shove to
   * the shift and send the members twice as far.
   */
  const onItemDragStop = (next: Layout[], from: Layout, to: Layout) => {
    if (!editing) return
    if (!isGroupItem(to.i)) {
      onLayoutChange(next)
      return
    }
    const group = groups.find((one) => one.id === groupIdOf(to.i))
    if (!group) return
    const dx = to.x - from.x
    const dy = to.y - from.y
    const shifts = new Map<string, Layout>()
    if (dx || dy) {
      for (const memberId of membersOf(group.id)) {
        const was = before.current.get(memberId)
        if (!was) continue
        shifts.set(memberId, {
          ...was,
          // Off the left edge or past the right one is a position the grid
          // would silently correct on the next render, leaving what is stored
          // and what is drawn disagreeing.
          x: Math.max(0, Math.min(columns - was.w, was.x + dx)),
          y: Math.max(0, was.y + dy),
        })
      }
    }
    saveGroups.mutate(
      allGroups.map((one) =>
        one.id === group.id ? { ...one, x: to.x, y: to.y, w: to.w } : one,
      ),
    )
    onLayoutChange(next, shifts)
  }

  /** Resizing a bar sets how wide the frame is drawn; the widgets are its own. */
  const onItemResizeStop = (next: Layout[], _from: Layout, to: Layout) => {
    if (!editing) return
    if (!isGroupItem(to.i)) {
      onLayoutChange(next)
      return
    }
    saveGroups.mutate(
      allGroups.map((one) =>
        one.id === groupIdOf(to.i) ? { ...one, x: to.x, y: to.y, w: to.w } : one,
      ),
    )
  }

  const addGroup = () => {
    const name = prompt('Name this group')?.trim()
    if (!name) return
    // Below everything already on the page, so a new group never lands on top
    // of a widget and pushes the board around as it arrives.
    const below = layout.reduce((lowest, item) => Math.max(lowest, item.y + item.h), 0)
    saveGroups.mutate([
      ...allGroups,
      { id: `g${Date.now().toString(36)}`, name, page, x: 0, y: below, w: Math.min(6, columns) },
    ])
  }

  /**
   * Where a widget goes when it joins a group.
   *
   * Membership on its own is only a label: the frame is the box around the bar
   * and its members, so a widget that joins from the far side of the page
   * stretches that box across everything in between and swallows widgets that
   * are not in the group at all. Joining moves it under the bar, beside the
   * last member if there is room inside the group's width and on a new row if
   * there is not.
   */
  const spotInGroup = (group: WidgetGroup, widget: Widget) => {
    const size = {
      w: Number(widget.layout?.w ?? 6),
      h: Number(widget.layout?.h ?? 4),
    }
    const top = Number(group.y ?? 0) + GROUP_BAR_ROWS
    const members = onThisPage
      .filter((one) => one.group_id === group.id && one.id !== widget.id)
      .map((one) => boxOf(one, { x: group.x ?? 0, y: top, w: 6, h: 4 }))
    if (!members.length) return { x: group.x ?? 0, y: top, ...size }

    const bottom = Math.max(...members.map((one) => one.y + one.h))
    const lastRow = members.filter((one) => one.y + one.h === bottom)
    const right = Math.max(...lastRow.map((one) => one.x + one.w))
    const rowTop = Math.min(...lastRow.map((one) => one.y))
    return right + size.w <= (group.x ?? 0) + (group.w ?? 6)
      ? { x: right, y: rowTop, ...size }
      : { x: group.x ?? 0, y: bottom, ...size }
  }

  const putInGroup = (widget: Widget, groupId: string) => {
    const group = groups.find((one) => one.id === groupId)
    groupWidget.mutate({
      widgetId: widget.id,
      groupId,
      // Leaving a group is only losing the label; the widget stays put.
      layout: group ? spotInGroup(group, widget) : undefined,
    })
  }

  const changeGroup = (groupId: string, change: Partial<WidgetGroup>) =>
    saveGroups.mutate(
      allGroups.map((one) => (one.id === groupId ? { ...one, ...change } : one)),
    )

  const toggleGroup = (group: WidgetGroup) => {
    const next = !group.collapsed
    setFoldedHere((current) => ({ ...current, [group.id]: next }))
    // Saved by whoever may save it, so the board opens this way next time.
    if (canEditBoard) changeGroup(group.id, { collapsed: next })
  }

  const removeGroup = (group: WidgetGroup) => {
    if (!confirm(`Remove the group "${group.name}"? Its widgets stay on the page.`)) return
    saveGroups.mutate(allGroups.filter((one) => one.id !== group.id))
  }

  return (
    <div>
      <PageHeader
        title={dashboard.data!.name}
        description={appearance.hide_subtitle ? undefined : dashboard.data!.description}
        logo={
          logoUrl ? (
            <img
              src={logoUrl}
              alt=""
              style={{ height: appearance.logo_height ?? 32 }}
              className="w-auto shrink-0 object-contain"
            />
          ) : undefined
        }
        titleStyle={{
          fontSize: appearance.title_size ? `${appearance.title_size}px` : undefined,
          fontFamily: titleFontStack(appearance.title_font),
          color: appearance.title_color || undefined,
          lineHeight: 1.15,
        }}
        align={appearance.title_align ?? 'left'}
        rule={Boolean(appearance.header_rule)}
        onTitleClick={
          !isPublic && can('analyst') ? () => setEditingStyle(true) : undefined
        }
        band={masthead}
        onBand={onMasthead}
        onDarkGround={onDarkPage}
        actions={
          !isPublic && (
            <>
              <AssignProject
                kind="dashboard"
                id={dashboard.data!.id}
                projectId={dashboard.data!.project_id}
                canMove={can('manager')}
              />
              {can('analyst') && (
                <>
                  <select
                    className="input w-44"
                    title="Chart colours for this dashboard"
                    value={dashboard.data!.theme ?? 'default'}
                    onChange={(event) => saveTheme.mutate(event.target.value)}
                  >
                    {Object.entries(CHART_THEMES).map(([key, theme]) => (
                      <option key={key} value={key}>
                        {theme.label}
                      </option>
                    ))}
                  </select>
                  <button className="btn-secondary" onClick={() => setEditingFilters(true)}>
                    Filters
                  </button>
                  <button className="btn-secondary" onClick={() => setEditingDrill(true)}>
                    Drill-down
                  </button>
                  <button className="btn-secondary" onClick={() => setEditingStyle(true)}>
                    Appearance
                  </button>
                  <button className="btn-secondary" onClick={() => setAdding(true)}>
                    Add widget
                  </button>
                  {editing && (
                    <button className="btn-secondary" onClick={addGroup}>
                      Add group
                    </button>
                  )}
                  <button
                    className={editing ? 'btn-primary' : 'btn-secondary'}
                    onClick={() => setEditing(!editing)}
                  >
                    {editing ? 'Done' : 'Move & resize'}
                  </button>
                  <button
                    className="btn-secondary"
                    onClick={() => {
                      // Publishing and managing the addresses are the same
                      // button now: a board that is not shared yet becomes
                      // shared by being given its first link.
                      if (!dashboard.data!.is_public) share.mutate(true)
                      setSharing(true)
                    }}
                  >
                    Share
                  </button>
                </>
              )}
            </>
          )
        }
      />

      {dashboard.data!.is_public && !isPublic && (
        <PublicLinkBar dashboard={dashboard.data!} canEdit={can('analyst')} />
      )}

      {sharing && !isPublic && (
        <ShareLinks dashboard={dashboard.data!} onClose={() => setSharing(false)} />
      )}

      {/* Everything the dashboard is read for sits on the canvas: the filters
          in use, the pages, and the widgets. The page header stays off it, so
          the toolbar's buttons keep the contrast they were designed with. */}
      <div
        className={canvas ? 'rounded-card p-4' : ''}
        style={canvas}
        data-testid="dashboard-canvas"
      >
      {/* When these numbers were fetched. The first question in any meeting
          the board is opened in, and a page that cannot answer it invites the
          assumption that it is live when it may be an hour old. */}
      <p className="mb-2 text-xs text-ink-500" style={asOfStyle}>
        {rendered.isFetching && !rendered.data
          ? 'Loading...'
          : `Data as of ${fetchedAt ? relativeTime(fetchedAt) : 'just now'}`}
        {dashboard.data!.refresh_interval_seconds
          ? `, refreshing every ${Math.round(
              dashboard.data!.refresh_interval_seconds / 60,
            )} min`
          : ''}
      </p>

      <SavedViews
        basePath={basePath}
        dashboardId={id}
        isPublic={isPublic}
        canPublish={!isPublic && can('analyst')}
        current={{ page, filters: filterValues, drill: path }}
        activeId={openedView.id}
        labelColor={appearance.filter_color}
        onApply={(view) => {
          setOpenedView({ id: view.id, name: view.name })
          setActivePage(view.state.page ?? 0)
          // After the page, because changing pages clears both of these.
          setTimeout(() => {
            setFilterValues(view.state.filters ?? {})
            setPath(view.state.drill ?? [])
            setPicked(null)
          }, 0)
        }}
      />

      {hierarchy.length > 0 && (
        <DrillTrail
          levels={hierarchy}
          path={path}
          background={appearance.filter_background}
          labelColor={appearance.filter_color}
          onGoTo={(depth) => {
            setPath((current) => current.slice(0, depth))
            setPicked(null)
          }}
        />
      )}

      {picked && (
        <div className="mb-3 flex flex-wrap items-center gap-2 rounded-card border border-brand-300 bg-brand-50 px-3 py-2 text-sm text-brand-900">
          <Badge tone="info" icon="⊙">
            Filtered by a click
          </Badge>
          <span>
            <span className="font-mono text-xs">{picked.variable}</span> is{' '}
            <strong>{picked.value}</strong>
          </span>
          <span className="text-xs text-brand-800/70">
            - every widget on this page except &ldquo;{picked.label}&rdquo;
          </span>
          <button className="btn-ghost btn-sm ml-auto" onClick={() => setPicked(null)}>
            Clear
          </button>
        </div>
      )}

      <DashboardFilters
        basePath={basePath}
        labelColor={appearance.filter_color}
        background={appearance.filter_background}
        controls={pageControls}
        value={filterValues}
        onChange={setFilterValues}
      />

      <PageTabs
        pages={pages}
        active={page}
        count={pageCount}
        canEdit={!isPublic && can('analyst')}
        widgetsOnPage={widgets.length}
        onDark={tabsOnDark}
        band={appearance.tab_background}
        color={appearance.tab_color}
        onSelect={setActivePage}
        onChange={(next) => savePages.mutate(next)}
        onMove={(from, to) => movePage.mutate({ from, to })}
        onRemove={(index) => removePage.mutate(index)}
      />

      {/* `widgets` leaves out a folded group's members, so it is empty on a
          page whose every widget is folded away - and the empty state would
          then replace the grid holding the bars, taking with it the only
          control that opens them again. What makes a page empty is having
          nothing on it, not having nothing showing. */}
      {!onThisPage.length && !groups.length ? (
        <Card>
          <EmptyState
            icon="▦"
            title="This dashboard is empty"
            description="Add saved charts or indicators to build your monitoring view."
            action={
              !isPublic &&
              can('analyst') && (
                <button className="btn-primary btn-sm" onClick={() => setAdding(true)}>
                  Add your first widget
                </button>
              )
            }
          />
        </Card>
      ) : (
        <div
          ref={measureGrid}
          // Dimmed a little while the numbers on screen belong to the previous
          // selection, so a click is acknowledged without the board being torn
          // down. isPlaceholderData rather than isFetching on purpose: the
          // latter is also true on the timed refresh, which would make a
          // dashboard left up on a wall blink every minute for no reason.
          className={`${fixedWidth > width ? 'overflow-x-auto' : ''} transition-opacity duration-200 ${
            rendered.isPlaceholderData ? 'opacity-60' : 'opacity-100'
          }`}
        >
        <div className="relative">
        <GroupFrames
          groups={groups}
          layout={placed.length ? placed : layout}
          membersOf={membersOf}
          grid={{
            columns,
            rowHeight,
            canvasWidth,
            margin: 16,
            padding: CANVAS_PADDING,
          }}
          tone={onDarkGround ? 'rgb(226 232 240 / 0.6)' : undefined}
        />
        <GridLayout
          className="layout"
          layout={layout}
          cols={columns}
          rowHeight={rowHeight}
          width={canvasWidth}
          // Without an explicit width the container stays as wide as the
          // window while the widgets inside it are laid out for the wider
          // canvas, so there is nothing for the scroller to scroll.
          style={fixedWidth ? { width: canvasWidth } : undefined}
          margin={[16, 16]}
          containerPadding={[CANVAS_PADDING, CANVAS_PADDING]}
          isDraggable={editing && !isPublic}
          isResizable={editing && !isPublic}
          // Tracked for the frames only; saving is still a drag or a resize.
          onLayoutChange={setPlaced}
          onDragStart={rememberPositions}
          onDragStop={onItemDragStop}
          onResizeStop={onItemResizeStop}
          draggableHandle=".widget-handle"
        >
          {groups.map((group) => (
            <div
              key={groupItemId(group)}
              className="overflow-hidden rounded-control border border-dashed"
              style={{
                borderColor: group.color || 'rgb(148 163 184 / 0.8)',
                backgroundColor: 'rgb(148 163 184 / 0.12)',
              }}
            >
              <GroupBar
                group={group}
                count={membersOf(group.id).length}
                editing={editing && !isPublic}
                onRename={(name) => changeGroup(group.id, { name })}
                onToggle={() => toggleGroup(group)}
                onRemove={() => removeGroup(group)}
              />
            </div>
          ))}
          {widgets.map((widget) => (
            <div
              key={widget.id}
              className={`card overflow-hidden ${widgetTone(styleOf(widget))}`}
              // A widget's own colour if it has one, the dashboard's paper if
              // not - and either way the dashboard's transparency, so the
              // background shows through both the same amount. The charts
              // inside draw on a transparent canvas, so they come with it.
              style={cardStyle(widget, widgetOpacity)}
            >
              <ErrorBoundary what={`"${widget.title || 'this widget'}"`}>
              <WidgetFrame
                widget={widget}
                card={cardStyle(widget, widgetOpacity)}
                ground={canvas}
                payload={rendered.data?.widgets[widget.id]}
                loading={rendered.isLoading}
                editing={editing && !isPublic}
                canEdit={!isPublic && can('analyst')}
                theme={dashboard.data!.theme ?? 'default'}
                drilledTo={drilledLevel(
                  hierarchy,
                  path,
                  rendered.data?.widgets[widget.id]?.grouped_on,
                )}
                openComments={openThreads(commentsFor(widget.id))}
                onComment={isPublic ? undefined : () => setCommenting(widget)}
                pageNames={pageNames}
                basePath={basePath}
                groups={groups}
                onGroup={(groupId) => putInGroup(widget, groupId)}
                onConfigure={(patch) =>
                  reconfigureWidget.mutate({
                    widgetId: widget.id,
                    config: { ...((widget.config as Record<string, unknown>) ?? {}), ...patch },
                  })
                }
                onMove={(toPage) => moveWidget.mutate({ widgetId: widget.id, page: toPage })}
                onEdit={() => setEditingWidget(widget)}
                onRemove={() => {
                  if (confirm(`Remove "${widget.title || 'this widget'}" from the dashboard?`))
                    removeWidget.mutate(widget.id)
                }}
                onSelect={(variable, value) => {
                  // A click on the level the board is currently showing goes
                  // one step deeper, taking every chart with it. A click on
                  // anything else filters the page the way it always has.
                  if (canDescend(hierarchy, path, variable)) {
                    setPicked(null)
                    setPath((current) => [
                      ...current,
                      { variable, value, label: levelLabel(hierarchy, variable) },
                    ])
                    return
                  }
                  setPicked((current) =>
                    // Clicking the same mark again is how you undo it, which is
                    // where the hand goes before it finds the chip.
                    current && current.variable === variable && current.value === value
                      ? null
                      : { variable, value, label: widget.title || variable, from: widget.id },
                  )
                }}
              />
              </ErrorBoundary>
            </div>
          ))}
        </GridLayout>
        </div>
        </div>
      )}
      </div>

      {adding && (
        <AddWidgetModal
          dashboardId={id}
          projectId={dashboard.data!.project_id}
          page={page}
          onClose={() => setAdding(false)}
        />
      )}
      {commenting && !isPublic && (
        <WidgetComments
          dashboardId={id}
          widgetId={commenting.id}
          widgetTitle={commenting.title || 'this widget'}
          viewId={openedView.id}
          viewName={openedView.name || 'this view'}
          comments={commentsFor(commenting.id)}
          onClose={() => setCommenting(null)}
        />
      )}
      {editingDrill && !isPublic && (
        <DrillDownModal
          dashboardId={id}
          widgets={allWidgets}
          levels={hierarchy}
          onClose={() => setEditingDrill(false)}
        />
      )}
      {editingWidget && (
        <EditWidgetModal
          dashboardId={id}
          projectId={dashboard.data!.project_id}
          widget={editingWidget}
          pageNames={pageNames}
          dashboardOpacity={widgetOpacity}
          onClose={() => setEditingWidget(null)}
        />
      )}
      {editingStyle && (
        <AppearanceModal
          dashboardId={id}
          name={dashboard.data!.name}
          description={dashboard.data!.description ?? ''}
          appearance={appearance}
          widgets={allWidgets}
          onClose={() => setEditingStyle(false)}
        />
      )}
      {editingFilters && (
        <FilterControlsModal
          dashboardId={id}
          page={page}
          pageName={pageNames[page]}
          widgets={widgets}
          controls={filterControls}
          onClose={() => setEditingFilters(false)}
        />
      )}
    </div>
  )
}