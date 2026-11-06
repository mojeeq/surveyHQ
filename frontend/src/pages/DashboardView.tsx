import {
keepPreviousData,
useMutation,
useQuery,
useQueryClient,
} from '@tanstack/react-query'

import { useCallback,useEffect,useMemo,useRef,useState } from 'react'


import { useNavigate, useParams } from 'react-router-dom'

import GridLayout,{ type Layout } from 'react-grid-layout'

import 'react-grid-layout/css/styles.css'

import 'react-resizable/css/styles.css'

import { PHONE_WIDTH, stackForPhone } from '@/lib/phone-layout'
import { api,ApiError } from '@/lib/api'


import { useBreadcrumbs } from '@/hooks/useBreadcrumbs'
import { useAuth } from '@/hooks/useAuth'

import { useDialog } from '@/hooks/useDialog'
import { useToast } from '@/hooks/useToast'

import { CHART_THEMES } from '@/lib/charts'


import { boardFreshness } from '@/lib/activity'

import type {
Dashboard,
DrillLevel,
DrillStep,
Widget,
WidgetComment,
WidgetGroup
} from '@/lib/types'

import MoreMenu from '@/components/MoreMenu'
import AssignProject from '@/components/AssignProject'




import ShareLinks from '@/components/ShareLinks'
import Snapshots from '@/components/dashboard/Snapshots'

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
  barsAbove,
  barStyles,
  groupAt,
  insetPadding,
  insets,
  spotBelow,
  type PlacedGroup,
  groupItemId,
  isGroupItem,
  groupIdOf,
} from '@/components/dashboard/WidgetGroups'
import { PublicLinkBar,SharePasswordPrompt } from '@/components/dashboard/sharing'
import { AddWidgetModal,EditWidgetModal } from '@/components/dashboard/WidgetEditor'
import { WidgetFrame } from '@/components/dashboard/WidgetFrame'
import {
Card,
EmptyState,
ErrorNote,
Loading,
PageHeader
} from '@/components/ui'


export default function DashboardView({ publicToken }: { publicToken?: string }) {
  const { id = '' } = useParams()
  const navigate = useNavigate()
  const { can } = useAuth()
  const toast = useToast()
  const ask = useDialog()
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
  const [keeping, setKeeping] = useState(false)

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
  // page ("show me Coastal"), not of the one chart that was clicked.
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
  // A phone gets the board stacked into one column (lib/phone-layout), at
  // the width it has: a fixed canvas width is for a wall, not a pocket.
  const phone = width < PHONE_WIDTH && !editing
  const canvasWidth = Math.max((phone ? 0 : fixedWidth) || width, 320)

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
      api.post<{
        widgets: Record<string, any>
        freshness?: { imported_at: string | null; next_import_at: string | null }
      }>(
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

  const duplicate = useMutation({
    mutationFn: () => api.post<Dashboard>(`/dashboards/${id}/duplicate`),
    onSuccess: (made) => {
      queryClient.invalidateQueries({ queryKey: ['dashboards'] })
      toast.push(`Copied to "${made.name}"`, 'success')
      // Straight onto the copy, because the reason for making one is to start
      // changing it, and leaving somebody on the original is an invitation to
      // edit the wrong board.
      navigate(`/dashboards/${made.id}`)
    },
    onError: (error: Error) => toast.push(error.message, 'error'),
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
  const logoRightUrl = useBackgroundImage(basePath, appearance, 'logo_right')
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

  const layout: Layout[] = useMemo(() => {
    const items = widgets.map((widget, index) => ({
      i: widget.id,
      x: Number(widget.layout?.x ?? (index % 2) * 6),
      y: Number(widget.layout?.y ?? Math.floor(index / 2) * 4),
      w: Number(widget.layout?.w ?? 6),
      h: Number(widget.layout?.h ?? 4),
      minW: 2,
      minH: 2,
    }))
    // Every bar above its own members, whatever its stored row says - see
    // barsAbove for how a stored row came to put the heading underneath.
    const here = new Set(groups.map((group) => group.id))
    const { bars, push } = barsAbove(
      groups,
      widgets.flatMap((widget, index) =>
        widget.group_id && here.has(widget.group_id)
          ? [{ groupId: widget.group_id, y: items[index].y }]
          : [],
      ),
    )
    widgets.forEach((widget, index) => {
      items[index].y += push.get(widget.group_id ?? '') ?? 0
    })
    return [
      ...items,
      // A group's title bar is a grid item like any other. That is what makes
      // it draggable, resizable and something the widgets collide with,
      // without any of those being written a second time here.
      ...groups.map((group) => ({
        i: groupItemId(group),
        x: Number(group.x ?? 0),
        y: bars.get(group.id) ?? Number(group.y ?? 0),
        w: Number(group.w ?? 6),
        h: GROUP_BAR_ROWS,
        minW: 2,
        minH: GROUP_BAR_ROWS,
        maxH: GROUP_BAR_ROWS,
      })),
    ]
  }, [widgets, groups])

  // What is drawn: the board's own layout, or on a phone the same widgets one
  // under the other. Never saved - dragging is off while it is stacked.
  const groupHeadingOf = useMemo(() => {
    const here = new Map(groups.map((group) => [group.id, groupItemId(group)]))
    const of = new Map<string, string>()
    for (const widget of widgets) {
      const heading = widget.group_id ? here.get(widget.group_id) : undefined
      if (heading) of.set(widget.id, heading)
    }
    return of
  }, [widgets, groups])
  const shown: Layout[] = useMemo(
    () => (phone ? stackForPhone(layout, columns, (id) => groupHeadingOf.get(id)) : layout),
    [phone, layout, columns, groupHeadingOf],
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

  useBreadcrumbs(dashboard.data && !isPublic ? [{ label: dashboard.data.name }] : null)
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

  // The board's ink for a group that chose no colour, and which sides of each
  // grouped widget lie on its frame - both read where the frames are drawn.
  const groupTone = onDarkGround ? 'rgb(226 232 240 / 0.6)' : undefined
  const inGroup = insets(groups, placed.length ? placed : shown, membersOf)

  /**
   * The groups as the grid has packed them, for working out where a widget
   * belongs. `leaving` is left out of its group's members, so a widget is
   * judged against the rest of its group. A folded group has nothing to drop
   * into and is left out.
   */
  const placedGroups = (items: Layout[], leaving?: string): PlacedGroup[] => {
    const at = new Map(items.map((item) => [item.i, item]))
    return groups.flatMap((group) => {
      const bar = at.get(groupItemId(group))
      if (!bar || group.collapsed) return []
      const members = membersOf(group.id)
        .filter((memberId) => memberId !== leaving)
        .map((memberId) => at.get(memberId))
        .filter((item): item is Layout => Boolean(item))
        .map(({ x, y, w, h }) => ({ x, y, w, h }))
      return [{ id: group.id, bar: { x: bar.x, y: bar.y, w: bar.w, h: bar.h }, members }]
    })
  }

  /** Where everything is drawn: the grid's packing once it has run, else the stored layout. */
  const live = () => (placed.length ? placed : layout)

  const onLayoutChange = (
    next: Layout[],
    shifts?: Map<string, Layout>,
    /** Widgets whose group changes with this save, by id; "" for none. */
    membership?: Map<string, string>,
  ) => {
    if (!editing) return
    // Every widget goes back, not just this page's: the PATCH replaces the whole
    // list, so omitting the other pages would delete them.
    const updated = allWidgets.map((widget) => {
      const position = shifts?.get(widget.id) ?? next.find((item) => item.i === widget.id)
      const moved = position
        ? { ...widget, layout: { x: position.x, y: position.y, w: position.w, h: position.h } }
        : widget
      return membership?.has(widget.id)
        ? { ...moved, group_id: membership.get(widget.id) ?? '' }
        : moved
    })
    saveLayout.mutate(updated)
    // And every bar, where the grid put it. Saving the widgets' packed rows
    // and not the bars' is what left a bar's stored row below its members,
    // and its heading drawn at the foot of the group on the next load.
    const moved = allGroups.map((group) => {
      const bar = next.find((item) => item.i === groupItemId(group))
      return bar && (bar.x !== group.x || bar.y !== group.y || bar.w !== group.w)
        ? { ...group, x: bar.x, y: bar.y, w: bar.w }
        : group
    })
    if (moved.some((group, index) => group !== allGroups[index])) saveGroups.mutate(moved)
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
      // A widget belongs to the group whose box it was dropped in, and to
      // none once it is dragged out of its own. See groupAt.
      const widget = onThisPage.find((one) => one.id === to.i)
      const landed = next.find((item) => item.i === to.i)
      const joins = landed ? groupAt(landed, placedGroups(next, to.i)) : ''
      if (widget && landed && joins !== (widget.group_id || '')) {
        onLayoutChange(next, undefined, new Map([[to.i, joins]]))
        const named = groups.find((one) => one.id === joins)?.name
        toast.push(
          named
            ? `"${widget.title || 'Widget'}" is now in "${named}"`
            : `"${widget.title || 'Widget'}" is out of its group`,
          'info',
        )
        return
      }
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
    // The bars, the dragged one included, are saved from where the grid put
    // them, with the widgets, in onLayoutChange.
    onLayoutChange(next, shifts)
  }

  /** A widget or a bar resized. A wider bar can push widgets down as much as a
   *  wider widget can, so the whole layout is saved either way - the bar's new
   *  width with it. */
  const onItemResizeStop = (next: Layout[]) => {
    if (!editing) return
    onLayoutChange(next)
  }

  const addGroup = async () => {
    const name = await ask.prompt({
      title: 'Add a group',
      label: 'Name this group',
      placeholder: 'Response rates',
      confirmLabel: 'Add group',
      validate: (entered) => (entered ? null : 'Give the group a name, or cancel.'),
    })
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
    // Where the group is drawn, not where it is stored: a bar's stored row can
    // be well below where the grid packed it, and a widget sent to the stored
    // row landed under everything else on the page.
    const drawn = placedGroups(live(), widget.id).find((one) => one.id === group.id)
    if (drawn) group = { ...group, x: drawn.bar.x, y: drawn.bar.y, w: drawn.bar.w }
    const top = Number(group.y ?? 0) + GROUP_BAR_ROWS
    const members = drawn
      ? drawn.members
      : onThisPage
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
    if (!groupId) {
      // Out of the group, and out of its box: just below it. Left where it
      // stood, a widget taken out was still inside the box drawn round the
      // rest of the group, and taking it out looked like nothing at all.
      const leaving = placedGroups(live(), widget.id).find((one) => one.id === widget.group_id)
      groupWidget.mutate({
        widgetId: widget.id,
        groupId: '',
        layout: leaving
          ? spotBelow(
              { w: Number(widget.layout?.w ?? 6), h: Number(widget.layout?.h ?? 4) },
              leaving,
              columns,
            )
          : undefined,
      })
      return
    }
    const group = groups.find((one) => one.id === groupId)
    groupWidget.mutate({
      widgetId: widget.id,
      groupId,
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

  const removeGroup = async (group: WidgetGroup) => {
    const sure = await ask.confirm({
      title: `Remove the group \u201C${group.name}\u201D?`,
      message: 'Its widgets stay on the page.',
      confirmLabel: 'Remove group',
      tone: 'danger',
    })
    if (!sure) return
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
        logoRight={
          logoRightUrl ? (
            <img
              src={logoRightUrl}
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
            // Two toolbars rather than one of ten buttons. Reading the board
            // needs Edit, Share and a menu; the tools for changing it appear
            // once Edit is pressed, with Done to put them away. They used to
            // sit in one row that wrapped onto two, viewing and editing mixed,
            // and on a phone the first screen was all buttons and no data.
            editing && can('analyst') ? (
              <>
                <AssignProject
                  kind="dashboard"
                  id={dashboard.data!.id}
                  projectId={dashboard.data!.project_id}
                  canMove={can('manager')}
                />
                <select
                  className="input w-44"
                  title="Chart colours for this dashboard"
                  aria-label="Chart colours for this dashboard"
                  value={dashboard.data!.theme ?? 'default'}
                  onChange={(event) => saveTheme.mutate(event.target.value)}
                >
                  {/* The general palettes first, then one per Pacific
                      country in a group of their own: twenty-two flags in
                      one run with "Default" would bury it. */}
                  {Object.entries(CHART_THEMES)
                    .filter(([, theme]) => !('group' in theme))
                    .map(([key, theme]) => (
                      <option key={key} value={key}>
                        {theme.label}
                      </option>
                    ))}
                  <optgroup label="Pacific Island countries and territories">
                    {Object.entries(CHART_THEMES)
                      .filter(([, theme]) => 'group' in theme)
                      .map(([key, theme]) => (
                        <option key={key} value={key}>
                          {theme.label}
                        </option>
                      ))}
                  </optgroup>
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
                <button className="btn-secondary" onClick={addGroup}>
                  Add group
                </button>
                <button className="btn-primary" onClick={() => setEditing(false)}>
                  Done
                </button>
              </>
            ) : (
              <>
                {can('analyst') && (
                  // Not on a phone: arranging a grid of widgets is a job for
                  // a screen wide enough to show it, and the button was most
                  // of the first screen there.
                  <span className="hidden sm:contents">
                    <button
                      className="btn-secondary"
                      onClick={() => setEditing(true)}
                      title="Add, arrange and style widgets, pages and filters"
                    >
                      Edit
                    </button>
                  </span>
                )}
                {can('analyst') && (
                  <button
                    className="btn-secondary"
                    // Opens the choices and nothing else. It used to publish
                    // the board on the spot, so looking at how to share it -
                    // or at downloading a copy - left an open link behind.
                    // An address is now made by asking for one, in the dialog.
                    onClick={() => setSharing(true)}
                    title={
                      dashboard.data!.is_public
                        ? 'This dashboard has an open link - anyone holding it can read it'
                        : 'Links, downloads and publishing'
                    }
                  >
                    {dashboard.data!.is_public ? 'Shared' : 'Share'}
                  </button>
                )}
                {can('analyst') && (
                  <MoreMenu
                    label="this dashboard"
                    items={[
                      { label: 'Snapshots', onClick: () => setKeeping(true) },
                      {
                        label: duplicate.isPending ? 'Duplicating…' : 'Duplicate',
                        onClick: () => duplicate.mutate(),
                      },
                    ]}
                  />
                )}
                {!can('analyst') && (
                  <AssignProject
                    kind="dashboard"
                    id={dashboard.data!.id}
                    projectId={dashboard.data!.project_id}
                    canMove={false}
                  />
                )}
              </>
            )
          )
        }
      />

      {/* While editing only. Read-only, it was a second toolbar between the
          title and the data; the Share button says "Shared" instead, and the
          dialog has every address. */}
      {editing && dashboard.data!.is_public && !isPublic && (
        <PublicLinkBar dashboard={dashboard.data!} canEdit={can('analyst')} />
      )}

      {sharing && !isPublic && (
        <ShareLinks dashboard={dashboard.data!} onClose={() => setSharing(false)} />
      )}

      {keeping && !isPublic && (
        <Snapshots
          dashboard={dashboard.data!}
          canEdit={can('analyst')}
          onClose={() => setKeeping(false)}
        />
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
          : boardFreshness(rendered.data?.freshness, fetchedAt)}
        {dashboard.data!.refresh_interval_seconds
          ? ` · page refreshes every ${Math.round(
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
        onOpenSnapshots={() => setKeeping(true)}
        onApply={(view) => {
          // null is "Everything": the same path, with the empty state, so
          // leaving a view goes through exactly the code that enters one
          // rather than a second way of clearing that can drift from it.
          setOpenedView(view ? { id: view.id, name: view.name } : { id: '', name: '' })
          setActivePage(view?.state.page ?? 0)
          // After the page, because changing pages clears both of these.
          setTimeout(() => {
            setFilterValues(view?.state.filters ?? {})
            setPath(view?.state.drill ?? [])
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

      {/*
        A click on a mark narrows the rest of the page, which is a state the
        reader did not ask for in words and has to be able to see at a glance
        and leave in one. So it is a band rather than a line of badges: a mark
        on the left saying what kind of thing this is, the selection itself in
        the reading size, what it reaches in the small grey of an aside, and
        the way out held at the far end where it is always in the same place.
      */}
      {picked && (
        <div className="mb-3 flex items-center gap-3 rounded-card border border-brand-100 bg-white px-4 py-3 shadow-sm dark:border-brand-500/25 dark:bg-dark-50">
          <span
            aria-hidden
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-brand-50 text-brand-600 dark:bg-brand-500/15 dark:text-brand-300"
          >
            <svg
              viewBox="0 0 24 24"
              className="h-4 w-4"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M4 5h16l-6.2 7.3V19l-3.6-2v-4.7z" />
            </svg>
          </span>

          <div className="min-w-0">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-brand-600 dark:text-brand-300">
              Filtered by a click
            </p>
            <p className="mt-0.5 truncate text-sm text-ink-800 dark:text-dark-700">
              {picked.operator === 'selected' ? (
                /* A ticked option has no value to read out: the answer is the
                   column. So the chip names the option and says it was
                   ticked, rather than printing "toilet__2 is 1". */
                <>
                  <strong className="font-semibold text-brand-700 dark:text-brand-300">
                    {picked.valueLabel || picked.variable}
                  </strong>{' '}
                  was ticked
                </>
              ) : (
                <>
                  {picked.variable} is{' '}
                  <strong className="font-semibold text-brand-700 dark:text-brand-300">
                    {/* "is -" says nothing; the slice was the records with no answer. */}
                    {picked.operator === 'missing' ? 'missing' : picked.value}
                  </strong>
                </>
              )}
              <span className="ml-2 text-xs text-ink-500 dark:text-dark-500">
                - every widget on this page except &ldquo;{picked.label}&rdquo;
              </span>
            </p>
          </div>

          <button
            className="btn-ghost btn-sm ml-auto shrink-0 gap-1.5"
            onClick={() => setPicked(null)}
          >
            <svg
              viewBox="0 0 24 24"
              className="h-3.5 w-3.5"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
            >
              <path d="M6 6l12 12M18 6L6 18" />
            </svg>
            Clear
          </button>
        </div>
      )}

      {/* The tabs sit above the filter bar, not below it. The controls belong
          to the page they are on, so their number changes from page to page -
          and with the bar above, the tab strip moved up and down under the
          pointer as somebody clicked along it, which is a row of buttons that
          will not hold still. Above the bar, the tabs are in the same place on
          every page, and the exported file is laid out this way too. */}
      <PageTabs
        pages={pages}
        active={page}
        count={pageCount}
        // Adding, renaming, moving and deleting pages are editing.
        canEdit={editing && !isPublic && can('analyst')}
        widgetsOnPage={widgets.length}
        onDark={tabsOnDark}
        band={appearance.tab_background}
        color={appearance.tab_color}
        onSelect={setActivePage}
        onChange={(next) => savePages.mutate(next)}
        onMove={(from, to) => movePage.mutate({ from, to })}
        onRemove={(index) => removePage.mutate(index)}
      />

      <DashboardFilters
        basePath={basePath}
        labelColor={appearance.filter_color}
        background={appearance.filter_background}
        controls={pageControls}
        value={filterValues}
        onChange={setFilterValues}
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
          className={`${!phone && fixedWidth > width ? 'overflow-x-auto' : ''} transition-opacity duration-200 ${
            rendered.isPlaceholderData ? 'opacity-60' : 'opacity-100'
          }`}
        >
        <div className="relative">
        <GroupFrames
          groups={groups}
          layout={placed.length ? placed : shown}
          membersOf={membersOf}
          grid={{
            columns,
            rowHeight,
            canvasWidth,
            margin: 16,
            padding: CANVAS_PADDING,
          }}
          tone={groupTone}
        />
        <GridLayout
          className="layout"
          layout={shown}
          cols={columns}
          rowHeight={rowHeight}
          width={canvasWidth}
          // Without an explicit width the container stays as wide as the
          // window while the widgets inside it are laid out for the wider
          // canvas, so there is nothing for the scroller to scroll.
          style={fixedWidth && !phone ? { width: canvasWidth } : undefined}
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
          {groups.map((group) => {
            const bar = barStyles(group, groupTone)
            return (
              <div key={groupItemId(group)} style={bar.cell}>
                <div className="h-full overflow-hidden rounded-control" style={bar.strip}>
                  <GroupBar
                    group={group}
                    count={membersOf(group.id).length}
                    editing={editing && !isPublic}
                    onRename={(name) => changeGroup(group.id, { name })}
                    onStyle={(change) => changeGroup(group.id, change)}
                    onToggle={() => toggleGroup(group)}
                    onRemove={() => removeGroup(group)}
                  />
                </div>
              </div>
            )
          })}
          {widgets.map((widget) => (
            // The cell the grid places, and the card in it. They are one box
            // except in a group, where the card is moved in from the frame on
            // the sides that lie on it.
            <div key={widget.id} style={insetPadding(inGroup.get(widget.id))}>
            <div
              className={`card h-full overflow-hidden ${widgetTone(styleOf(widget))}`}
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
                onRemove={async () => {
                  const sure = await ask.confirm({
                    title: `Remove \u201C${widget.title || 'this widget'}\u201D?`,
                    message: 'It goes from this dashboard. The chart it draws stays.',
                    confirmLabel: 'Remove widget',
                    tone: 'danger',
                  })
                  if (sure) removeWidget.mutate(widget.id)
                }}
                onSelect={(variable, value, how) => {
                  // A click on the level the board is currently showing goes
                  // one step deeper, taking every chart with it. A click on
                  // anything else filters the page the way it always has.
                  //
                  // A ticked option is never a level: a hierarchy is nested
                  // places, and an option column is one box on a form. Asked
                  // first so a column that happened to share a level's name
                  // could not send the board down a level it is not showing.
                  if (!how && canDescend(hierarchy, path, variable)) {
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
                      : {
                          variable,
                          value,
                          label: widget.title || variable,
                          from: widget.id,
                          ...(how ?? {}),
                        },
                  )
                }}
              />
              </ErrorBoundary>
            </div>
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