/**
 * Interview locations on a map.
 *
 * The pins are places, not rows: the server groups by coordinate, so several
 * interviews at one household are one pin carrying a number. Clicking it says
 * what that number is and shows the details the widget was told to carry -
 * which interviewer, which region, how many people.
 *
 * Tiles come from OpenStreetMap by default and are the one part of this that
 * needs the internet. When they cannot be fetched the pins still draw, on a
 * plain ground, which is degraded rather than broken - and a deployment with
 * its own tile server can point the widget at it.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { escapeHtml, formatNumber, mapSummary, verdictMix } from '@/lib/format'
import {
  COVERAGE_COLOR,
  DEFAULT_POINT_FILL,
  DUPLICATE_COLOR,
  MANUAL_COLORS,
  VERDICT_LABELS,
  VERDICTS,
  categoryLabel,
  formatMetres,
  manualVerdictLabel,
  mapCategories,
  type LineLayer,
  type ManualLayer,
  type MapPoint,
  type AreaStatus,
} from '@/lib/map-layers'

export {
  DEFAULT_POINT_FILL,
  VERDICT_ORDER,
  VERDICTS,
  type AreaStatus,
  type MapPoint,
} from '@/lib/map-layers'

/**
 * The grounds the pins can be drawn on, in the order they are offered.
 *
 * Each carries its own attribution because each is somebody else's imagery,
 * and Leaflet credits whichever is showing rather than whichever was first.
 */
export const BASEMAPS = {
  streets: {
    label: 'Streets',
    url: 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
    attribution: '© OpenStreetMap contributors',
    maxZoom: 19,
  },
  satellite: {
    label: 'Satellite',
    url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    attribution: 'Imagery © Esri, Maxar, Earthstar Geographics',
    maxZoom: 19,
    /**
     * Place names over the imagery.
     *
     * Photography alone has no writing on it, and someone checking whether a
     * cluster of interviews is the village it should be needs the name of the
     * village. Esri publishes the boundaries and labels as a transparent layer
     * meant to sit on top of the imagery, so the two travel together here and
     * switch as one.
     */
    labels:
      'https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}',
  },
  terrain: {
    label: 'Terrain',
    url: 'https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png',
    attribution: '© OpenStreetMap contributors, SRTM | © OpenTopoMap (CC-BY-SA)',
    maxZoom: 17,
  },
} as const

export type BasemapName = keyof typeof BASEMAPS
export const BASEMAP_NAMES = Object.keys(BASEMAPS) as BasemapName[]

export const DEFAULT_TILES = BASEMAPS.streets.url
const ATTRIBUTION = BASEMAPS.streets.attribution

/** The named ground to start on, ignoring a name no longer offered. */
export function basemapOf(name: string | undefined): BasemapName {
  return name && name in BASEMAPS ? (name as BasemapName) : 'streets'
}

/**
 * The shapes a point can be drawn as.
 *
 * A circle is right for "how much is here", because a circle's area reads as a
 * quantity. It is the wrong shape for "what happened here": a square and a
 * triangle are told apart at a glance and in a photocopy, which a light circle
 * beside a dark one is not. So the shape is the author's to choose, and the
 * ones offered are the ones that stay distinct at the size a pin actually is.
 */
export const POINT_ICONS = {
  circle: { label: 'Circle', sides: 0 },
  square: { label: 'Square', sides: 4 },
  triangle: { label: 'Triangle', sides: 3 },
  diamond: { label: 'Diamond', sides: 4, turn: Math.PI / 4 },
  pentagon: { label: 'Pentagon', sides: 5 },
} as const

/** What a pin looks like before anybody chooses otherwise. */
export const DEFAULT_POINT_SIZE = 16
export const DEFAULT_POINT_OPACITY = 0.6

/**
 * A darker edge for a filled pin.
 *
 * A shape needs an outline or a cluster of them reads as one blob, and the
 * outline has to come from the fill rather than be chosen separately: a second
 * colour to pick is a second thing to get wrong, and nobody wants a green pin
 * with a red edge.
 */
function shade(fill: string): string {
  const hex = fill.replace('#', '')
  if (hex.length !== 6) return fill
  const darker = [0, 2, 4]
    .map((at) => Math.round(parseInt(hex.slice(at, at + 2), 16) * 0.7))
    .map((channel) => channel.toString(16).padStart(2, '0'))
    .join('')
  return `#${darker}`
}

export type PointIcon = keyof typeof POINT_ICONS
export const POINT_ICON_NAMES = Object.keys(POINT_ICONS) as PointIcon[]

export function pointIconOf(name: string | undefined): PointIcon {
  return name && name in POINT_ICONS ? (name as PointIcon) : 'circle'
}

/**
 * A marker of one of the shapes above, at a radius in pixels.
 *
 * Leaflet draws circles natively and nothing else, so anything with corners is
 * a polygon whose vertices are worked out in screen space through the map's
 * own projection. That is also why the pins are redrawn on every zoom: a shape
 * laid out in pixels at one zoom is the wrong size at the next.
 */
function marker(
  map: L.Map,
  icon: PointIcon,
  at: [number, number],
  radius: number,
  options: L.PathOptions,
): L.Path {
  const shape = POINT_ICONS[icon]
  const sides = 'sides' in shape ? shape.sides : 0
  if (!sides) return L.circleMarker(at, { ...options, radius })

  const centre = map.latLngToLayerPoint(at)
  // Point-up rather than flat-topped: a triangle standing on a point is the
  // one everybody draws, and the same quarter turn keeps a square square.
  const turn = ('turn' in shape ? shape.turn : 0) - Math.PI / 2
  const corners = Array.from({ length: sides }, (_, index) => {
    const angle = turn + (index * 2 * Math.PI) / sides
    return map.layerPointToLatLng(
      L.point(centre.x + radius * Math.cos(angle), centre.y + radius * Math.sin(angle)),
    )
  })
  return L.polygon(corners, options)
}

/** One area from a boundary layer, as it comes back from the server. */
export interface BoundaryFeature {
  type: 'Feature'
  geometry: { type: string; coordinates: unknown }
  properties: Record<string, unknown>
}

/** The outlines a map draws under its pins, and what to write on them. */
export interface BoundaryOverlay {
  id: string
  name: string
  /** Which property of each area is its name on the map. Blank draws none. */
  label?: string
  bbox?: number[]
}

/** Escapes text going into a popup: the values are survey data, not markup. */
/** A popup field: escaped, and a dash where the record has nothing. */
function escape(value: unknown): string {
  return escapeHtml(value ?? '-')
}

export default function MapWidget({
  points,
  detail = [],
  measure,
  basemap,
  tiles,
  truncated = false,
  grouped,
  areaCounts,
  boundary,
  areas,
  areaVariable,
  icon,
  pointColor,
  pointSize,
  pointOpacity,
  sizeByValue = true,
  duplicates,
  manual,
  lines,
  coverage,
  labelsAlways = false,
  manualName = 'Manual',
}: {
  points: MapPoint[]
  detail?: string[]
  measure?: { agg: string; variable: string }
  /** Which ground to start on. A custom tile URL overrides it. */
  basemap?: string
  tiles?: string
  truncated?: boolean
  /** Set when the coordinates were rounded to fit the map, and by how much. */
  grouped?: { records: number; decimals?: number; metres?: number | null } | null
  /** The verdicts over every location checked, counted before the pins were
      grouped. The legend is the finding, so it is not a count of pins. */
  areaCounts?: Partial<Record<AreaStatus, number>>
  /** The outlines to draw under the pins, when the widget names a layer. */
  boundary?: BoundaryOverlay
  /** That layer's areas, fetched separately: a national frame is large. */
  areas?: { type: string; features: BoundaryFeature[] }
  /** The variable holding the area each record says it was in. */
  areaVariable?: string
  /** The shape each point is drawn as. */
  icon?: string
  /** The colour of a pin, when its colour is not carrying an answer. */
  pointColor?: string
  /** How big a pin is, in pixels. Sizing by value scales around it. */
  pointSize?: number
  /** 0 to 1. Low values let a dense cluster be read as density. */
  pointOpacity?: number
  /**
   * Whether a pin's size carries the value.
   *
   * On by default, because "how many interviews here" is what a map is usually
   * asked. Off draws every place the same size, which is what you want when the
   * question is where the work reached rather than how much of it there was.
   */
  sizeByValue?: boolean
  /** Set when the widget flags readings near another record's, and how near. */
  duplicates?: { metres: number; places: number } | null
  /** The location entered by hand beside the GPS, when the widget has one. */
  manual?: ManualLayer | null
  /** Records whose two locations are far apart, drawn as lines between them. */
  lines?: LineLayer | null
  /** Records in each area of the boundary layer, by its place in the layer. */
  coverage?: Record<string, number> | null
  /** Write each area's name on the map, rather than on hover. */
  labelsAlways?: boolean
  /** What the hand-entered location is called: "Manual", "Reported". */
  manualName?: string
}) {
  const container = useRef<HTMLDivElement>(null)
  const map = useRef<L.Map | null>(null)
  const outlines = useRef<L.GeoJSON | null>(null)
  const shaded = useRef<L.GeoJSON | null>(null)
  const coverageOff = useRef(false)
  // One group of pins per layer the reader can tick, kept from one drawing to
  // the next so a layer somebody unticked stays unticked through a zoom, a
  // filter change and the timed refresh.
  const overlays = useRef(new Map<string, L.FeatureGroup>())
  const ticked = useRef(new Set<string>())
  const listed = useRef('')
  // Bumped when the map is built again, so everything drawn on the last one
  // is drawn on this one too.
  const [generation, setGeneration] = useState(0)
  // The box in the corner that switches grounds and, when the widget has
  // one, shows or hides the boundary layer. Held here because the two are
  // added by different effects: the grounds when the map is built, the
  // outlines when their areas arrive.
  const switcher = useRef<L.Control.Layers | null>(null)
  /** Set when the switcher exists only to carry the boundary tick-box. */
  const switcherIsOurs = useRef(false)
  const grounds = useRef<Partial<Record<BasemapName, L.Layer>>>({})
  const [tilesFailed, setTilesFailed] = useState(false)
  const custom = tiles?.trim()
  const chosen = basemapOf(basemap)
  const shape = pointIconOf(icon)
  // Bumped on zoom to rebuild the pins, for the shapes that need it.
  const [redraws, setRedraws] = useState(0)
  // The extent the map was last framed on, so a rebuild does not move the view.
  const framed = useRef('')

  // The biggest pin sets the scale, so one busy cluster does not turn every
  // other point into a dot too small to click.
  const largest = useMemo(
    () => Math.max(1, ...points.map((point) => Math.abs(Number(point.value) || 0))),
    [points],
  )

  // A map with layers to tick keeps its list open, as a key: which colour is
  // which finding is the first thing it is read for. A plain map keeps the
  // list folded into its corner.
  const expanded = Boolean(areaVariable || manual || duplicates || coverage || lines)

  const categories = useMemo(
    () => mapCategories({ points, areaCounts, duplicates, manual, lines, manualName, pointColor }),
    [points, areaCounts, duplicates, manual, lines, manualName, pointColor],
  )

  const measureLabel = measure
    ? measure.agg === 'count'
      ? 'Interviews here'
      : `${measure.agg} of ${measure.variable}`
    : 'Interviews here'

  useEffect(() => {
    if (!container.current || map.current) return
    // Canvas rather than one SVG node per point: a census enumerates every
    // household at its own reading, so this is tens of thousands of circles,
    // and the DOM is where that stops being a map and becomes a freeze.
    const instance = L.map(container.current, {
      attributionControl: true,
      preferCanvas: true,
    }).setView([0, 0], 2)
    map.current = instance
    // This one has never been framed, whatever the last one was showing. The
    // record of that has to be cleared with the map it belonged to: a fresh
    // instance opens on the whole planet, and if it still counted as framed
    // nothing would ever move it to the survey - which is what a torn-down and
    // rebuilt map did, leaving every pin in one dot on a world map.
    framed.current = ''
    setTilesFailed(false)

    // A server with no route to the tile host is a normal deployment, not a
    // fault: the pins are the data and they still draw. Saying so beats a grey
    // rectangle that looks like a bug.
    const watch = (tile: L.TileLayer) => {
      tile.on('tileerror', () => setTilesFailed(true))
      return tile
    }

    if (custom) {
      // Somebody else's tile service, usually because this deployment has no
      // route to the public ones. Offering it a choice of hosts it cannot
      // reach would be a switcher between three grey rectangles, so the named
      // grounds are left out entirely here.
      grounds.current = {}
      watch(L.tileLayer(custom, { attribution: ATTRIBUTION, maxZoom: 19 })).addTo(instance)
    } else {
      grounds.current = Object.fromEntries(
        BASEMAP_NAMES.map((name) => {
          const ground = BASEMAPS[name]
          const tile = watch(
            L.tileLayer(ground.url, {
              attribution: ground.attribution,
              maxZoom: ground.maxZoom,
            }),
          )
          // Imagery and its place names are one choice, so they are grouped
          // and the switcher moves them together.
          const labels = 'labels' in ground ? ground.labels : undefined
          return [
            name,
            labels
              ? L.layerGroup([tile, watch(L.tileLayer(labels, { maxZoom: ground.maxZoom }))])
              : tile,
          ]
        }),
      ) as Partial<Record<BasemapName, L.Layer>>
      grounds.current[chosen]?.addTo(instance)
      // The switcher belongs on the map rather than in the widget's settings:
      // "show me that on the satellite" is something a reader does while
      // looking, and only the person who built the board can open the settings.
      switcher.current = L.control
        .layers(
          Object.fromEntries(
            BASEMAP_NAMES.map((name) => [BASEMAPS[name].label, grounds.current[name]!]),
          ),
          {},
          { position: 'topright', collapsed: !expanded },
        )
        .addTo(instance)
      switcherIsOurs.current = false
    }

    // How far is 300 m: a reader judging whether two readings are the same
    // doorstep needs the ground's own scale, and a zoom level is not one.
    L.control.scale({ position: 'bottomleft', maxWidth: 120 }).addTo(instance)
    setGeneration((count) => count + 1)

    // A shape with corners is laid out in pixels through the projection, so it
    // is the wrong size at any other zoom and has to be rebuilt. Registered
    // here, with the map itself, rather than in an effect of its own: the
    // first draw happens at the world view and is immediately followed by the
    // fit to the data, and a listener attached after that first zoom would
    // miss it and leave every pin sized for a map of the whole planet.
    instance.on('zoomend', () => setRedraws((count) => count + 1))

    return () => {
      instance.remove()
      map.current = null
      grounds.current = {}
      switcher.current = null
      switcherIsOurs.current = false
      overlays.current.clear()
      ticked.current.clear()
      listed.current = ''
      outlines.current = null
      shaded.current = null
    }
    // Built once per tile source, and again when the list of layers starts or
    // stops being a key - Leaflet decides whether it folds when it is made.
    // Switching between the named grounds is the effect below, which does not
    // tear the map down and lose the reader's pan and zoom.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [custom, expanded])

  // The widget's chosen ground, changed in its settings after the map was
  // built. A ground the reader picked from the switcher is left alone.
  useEffect(() => {
    const instance = map.current
    const next = grounds.current[chosen]
    if (!instance || !next || instance.hasLayer(next)) return
    for (const ground of Object.values(grounds.current)) instance.removeLayer(ground)
    instance.addLayer(next)
  }, [chosen])

  /** The box of tick-boxes, made here when no choice of ground made one. */
  const ensureSwitcher = (instance: L.Map): L.Control.Layers => {
    if (!switcher.current) {
      // A custom tile URL means no choice of ground and so no switcher; one
      // is made for the layers' tick-boxes.
      switcher.current = L.control
        .layers({}, {}, { position: 'topright', collapsed: !expanded })
        .addTo(instance)
      switcherIsOurs.current = true
    }
    return switcher.current
  }

  // The outlines, under the pins. Drawn as their own layer rather than with
  // the points so a filter change redraws the pins without redrawing a
  // national frame, which is the expensive half by a wide margin.
  useEffect(() => {
    const instance = map.current
    if (!instance) return
    if (outlines.current) {
      instance.removeLayer(outlines.current)
      outlines.current = null
    }
    const features = areas?.features ?? []
    if (!features.length) return

    const drawn = L.geoJSON(
      { type: 'FeatureCollection', features } as never,
      {
        style: {
          // An outline, not a fill: what is being read is the pins inside it,
          // and a filled area over satellite imagery hides the ground the
          // reader came to the satellite view for.
          color: '#e07b39',
          weight: 2,
          fillOpacity: 0.04,
          fillColor: '#e07b39',
        },
        onEachFeature: (feature, drawnLayer) => {
          const properties = (feature.properties ?? {}) as Record<string, unknown>
          const name = boundary?.label ? properties[boundary.label] : undefined
          if (name === undefined || name === null || !String(name).trim()) return
          // Named on hover, and nothing on click.
          //
          // An area covers the whole map, so a polygon that answers clicks
          // answers every click: the pin under the cursor never gets one, and
          // the pins are what the map is about. Hovering says where you are;
          // clicking interrogates the record standing there.
          // Escaped: a string handed to bindTooltip is set as innerHTML, and
          // this name is a property of an uploaded boundary file.
          //
          // Or written on the map for good, when the widget says so: a field
          // supervisor reads "0403" off the satellite view the way they read
          // it off a printed EA map, without hovering over every area.
          drawnLayer.bindTooltip(escape(name), {
            direction: 'center',
            className: labelsAlways ? 'boundary-label boundary-label-written' : 'boundary-label',
            permanent: labelsAlways,
          })
        },
      },
    )
    drawn.addTo(instance)
    // Behind the pins, whatever order the layers were added in.
    drawn.bringToBack()
    outlines.current = drawn

    // A tick-box for the outlines, beside the choice of ground.
    //
    // Boundaries are drawn to be read against, and there are maps where they
    // are the thing in the way: a cluster of households inside one enumeration
    // area is a handful of pins under a heavy orange line, and the question
    // "which of these is on the wrong side of it" is asked by taking the line
    // off and putting it back. That is a reader's gesture, not a setting, so
    // it belongs on the map rather than in a dialog only the board's author
    // can open.
    ensureSwitcher(instance).addOverlay(drawn, boundary?.name || 'Boundaries')
    const ours = switcherIsOurs.current

    // Ticked back on, the outlines have to sink again. Every vector here
    // shares one canvas and is painted in the order it was added, so a layer
    // put back last is painted last: the frame came back over the pins rather
    // than under them, and a boundary drawn on top of the records inside it is
    // exactly what bringToBack is here to prevent.
    // The shading of the areas reached sinks below the outlines, for the same
    // reason.
    const sink = (event: { layer: L.Layer }) => {
      if (event.layer !== drawn && event.layer !== shaded.current) return
      drawn.bringToBack()
      shaded.current?.bringToBack()
    }
    instance.on('overlayadd', sink)

    return () => {
      // A map already taken down took its layers with it. Removing one from
      // it again asks a canvas that no longer exists to repaint, which is a
      // TypeError on the next frame - and what React's development mode, which
      // mounts every component twice, did on every page load.
      if (map.current !== instance) return
      instance.off('overlayadd', sink)
      instance.removeLayer(drawn)
      if (outlines.current === drawn) outlines.current = null
      // Only while the map is still standing: its own teardown takes the
      // control with it and clears the ref.
      if (switcher.current) {
        switcher.current.removeLayer(drawn)
        // Unless the layers' tick-boxes still need it.
        if (ours && !listed.current && !shaded.current) {
          switcher.current.remove()
          switcher.current = null
          switcherIsOurs.current = false
        }
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [areas, boundary?.label, boundary?.name, labelsAlways, generation])

  // The areas the fieldwork has reached, shaded under their outlines.
  useEffect(() => {
    const instance = map.current
    const features = areas?.features ?? []
    if (!instance || !coverage || !features.length) return
    const reached = features.filter((_, index) => (coverage[String(index)] ?? 0) > 0)
    const drawn = L.geoJSON({ type: 'FeatureCollection', features: reached } as never, {
      // Nothing to click: the outlines name an area on hover, and a click is
      // for the pin under the cursor.
      interactive: false,
      style: { stroke: false, fillColor: COVERAGE_COLOR, fillOpacity: 0.35 },
    })
    shaded.current = drawn
    if (!coverageOff.current) drawn.addTo(instance)
    drawn.bringToBack()
    ensureSwitcher(instance).addOverlay(
      drawn,
      categoryLabel({
        key: 'coverage',
        text: 'Areas with interviews',
        color: COVERAGE_COLOR,
        kind: 'area',
        count: reached.length,
        of: features.length,
      }),
    )
    return () => {
      if (map.current !== instance) return
      // Whether the reader had it ticked, for the next drawing to keep.
      coverageOff.current = !instance.hasLayer(drawn)
      switcher.current?.removeLayer(drawn)
      instance.removeLayer(drawn)
      if (shaded.current === drawn) shaded.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [areas, coverage, generation])

  useEffect(() => {
    const instance = map.current
    if (!instance) return
    const name = manualName || 'Manual'
    const base = pointSize && pointSize > 0 ? pointSize : DEFAULT_POINT_SIZE
    const fill = pointColor || DEFAULT_POINT_FILL
    const near = duplicates ? formatMetres(duplicates.metres) : ''

    // Each layer's pins, by the key the map's list knows it by.
    const draw = new Map<string, (group: L.FeatureGroup) => void>()

    const gpsPin = (point: MapPoint, group: L.FeatureGroup) => {
      const value = Number(point.value) || 0
      const verdict = point.area_status ? VERDICTS[point.area_status] : undefined
      // Two different maps in one component. Asked "where is the work", the
      // pin's area can carry the value, because that is the question. Asked
      // "does the recorded area agree with the GPS", size would be a second
      // variable competing with the colour that carries the answer, so every
      // pin is the size its verdict says and only the colour speaks.
      const scaled = sizeByValue
        ? // Area, not radius, carries the value: doubling the radius of a
          // circle quadruples what the eye reads off it.
          base * 0.45 + base * Math.sqrt(Math.abs(value) / largest)
        : base
      const pin = marker(instance, shape, [point.lat, point.lon], verdict ? verdict.radius : scaled, {
        color: verdict ? verdict.color : shade(fill),
        weight: 1,
        fillColor: verdict ? verdict.color : fill,
        fillOpacity: verdict ? 0.85 : (pointOpacity ?? DEFAULT_POINT_OPACITY),
      })
      const mix = verdictMix(Number(point.places) || 0, point.area_verdicts, VERDICT_LABELS)
      // Built when the popup opens, not when the marker is made: the string is
      // the expensive part, and at fifty thousand points all but one of them
      // is work for a popup nobody opens.
      pin.bindPopup(() => {
        const twins = Number(point.duplicates) || 0
        const twinPlaces = Number(point.duplicate_places) || 0
        return (
          `<div style="font:13px system-ui;min-width:150px">` +
          `<div style="font-weight:600;margin-bottom:4px">${escape(measureLabel)}: ${escape(
            formatNumber(value),
          )}</div>` +
          (point.rows !== value
            ? `<div style="color:#64748b">from ${escape(formatNumber(point.rows))} record(s)</div>`
            : '') +
          (verdict
            ? `<div style="margin:4px 0;padding-top:4px;border-top:1px solid #e5e7eb">` +
              `<div style="color:${verdict.color};font-weight:600">${escape(verdict.label)}</div>` +
              (mix ? `<div style="color:#64748b">${escape(mix)}</div>` : '') +
              `<div><span style="color:#64748b">${escape(areaVariable || 'Recorded')}:</span> ` +
              `${escape(point.recorded_area_label ?? point.recorded_area ?? '-')}</div>` +
              `<div><span style="color:#64748b">Falls in:</span> ${escape(
                point.area_expected ?? 'no area in this layer',
              )}</div></div>`
            : '') +
          (twins
            ? `<div style="margin:4px 0;font-weight:600;color:${DUPLICATE_COLOR}">${escape(
                `${twins >= 99 ? '99+' : formatNumber(twins)} other record${twins === 1 ? '' : 's'} within ${near}`,
              )}</div>`
            : '') +
          (twinPlaces
            ? `<div style="margin:4px 0;font-weight:600;color:${DUPLICATE_COLOR}">${escape(
                `${formatNumber(twinPlaces)} of the locations here have another record within ${near}`,
              )}</div>`
            : '') +
          detailLines(point) +
          `<div style="color:#94a3b8;margin-top:4px">${point.lat.toFixed(5)}, ${point.lon.toFixed(5)}</div>` +
          `</div>`
        )
      })
      pin.addTo(group)
    }

    const detailLines = (point: MapPoint) =>
      detail
        .map(
          (field) =>
            `<div><span style="color:#64748b">${escape(field)}:</span> ${escape(point[field])}</div>`,
        )
        .join('')

    const manualPin = (point: MapPoint, group: L.FeatureGroup) => {
      const status = point.area_status
      const colour = status ? MANUAL_COLORS[status] : MANUAL_COLORS.match
      // A circle with a white rim, whatever shape the GPS pins are: the two
      // kinds of location have to be told apart where they overlap.
      const pin = L.circleMarker([point.lat, point.lon], {
        radius: status === 'mismatch' ? 6 : 5,
        color: '#ffffff',
        weight: 1.5,
        fillColor: colour,
        fillOpacity: 0.95,
      })
      pin.bindPopup(() => {
        const gaps = Array.isArray(point.gps) ? point.gps : null
        return (
          `<div style="font:13px system-ui;min-width:150px">` +
          `<div style="font-weight:600;margin-bottom:4px">${escape(`${name} location`)}</div>` +
          (Number(point.rows) > 1
            ? `<div style="color:#64748b">${escape(formatNumber(point.rows))} records</div>`
            : '') +
          (status
            ? `<div style="margin:4px 0;padding-top:4px;border-top:1px solid #e5e7eb">` +
              `<div style="color:${status === 'mismatch' ? '#a16207' : colour};font-weight:600">${escape(
                manualVerdictLabel(status, name),
              )}</div>` +
              `<div><span style="color:#64748b">${escape(areaVariable || 'Recorded')}:</span> ` +
              `${escape(point.recorded_area_label ?? point.recorded_area ?? '-')}</div>` +
              `<div><span style="color:#64748b">Falls in:</span> ${escape(
                point.area_expected ?? 'no area in this layer',
              )}</div></div>`
            : '') +
          (gaps
            ? gaps.length
              ? `<div>${escape(
                  `GPS reading ${gaps.map((gap) => formatMetres(gap)).join(', ')} away`,
                )}</div>`
              : `<div style="color:#64748b">No GPS reading</div>`
            : '') +
          detailLines(point) +
          `<div style="color:#94a3b8;margin-top:4px">${point.lat.toFixed(5)}, ${point.lon.toFixed(5)}</div>` +
          `</div>`
        )
      })
      pin.addTo(group)
    }

    for (const category of categories) {
      const [kind, status] = category.key.split(':')
      if (kind === 'gps') {
        const mine = status === 'all' ? points : points.filter((point) => point.area_status === status)
        draw.set(category.key, (group) => mine.forEach((point) => gpsPin(point, group)))
      } else if (kind === 'manual' && manual) {
        const mine =
          status === 'all' ? manual.points : manual.points.filter((point) => point.area_status === status)
        draw.set(category.key, (group) => mine.forEach((point) => manualPin(point, group)))
      } else if (kind === 'duplicates') {
        const flagged = points.filter(
          (point) => (Number(point.duplicates) || 0) > 0 || (Number(point.duplicate_places) || 0) > 0,
        )
        // A ring round the pin, so the pin keeps the colour of its own finding
        // and the ring adds this one. Not clickable: the pin under it is, and
        // its popup says how many others are near.
        draw.set(category.key, (group) =>
          flagged.forEach((point) =>
            L.circleMarker([point.lat, point.lon], {
              radius: (point.area_status ? VERDICTS[point.area_status].radius : base / 2) + 4,
              color: DUPLICATE_COLOR,
              weight: 2,
              fill: false,
              interactive: false,
            }).addTo(group),
          ),
        )
      } else if (kind === 'lines' && lines) {
        draw.set(category.key, (group) =>
          lines.lines.forEach((line) => {
            // A dark edge under a white line reads on the satellite and on the
            // street map alike.
            L.polyline([line.gps, line.manual], {
              color: '#0f172a',
              weight: 4,
              opacity: 0.55,
              interactive: false,
            }).addTo(group)
            const drawn = L.polyline([line.gps, line.manual], {
              color: '#ffffff',
              weight: 2,
              dashArray: '6 4',
            })
            drawn.bindPopup(
              `<div style="font:13px system-ui;min-width:150px">` +
                `<div style="font-weight:600">${escape(
                  `GPS and ${name.toLowerCase()} location ${formatMetres(line.metres)} apart`,
                )}</div>` +
                (line.recorded_area_label !== undefined && line.recorded_area_label !== null
                  ? `<div><span style="color:#64748b">${escape(areaVariable || 'Recorded')}:</span> ${escape(
                      line.recorded_area_label,
                    )}</div>`
                  : '') +
                (line.rows > 1 ? `<div style="color:#64748b">${escape(formatNumber(line.rows))} records</div>` : '') +
                `</div>`,
            )
            drawn.addTo(group)
          }),
        )
      }
    }

    // The groups: refilled, kept ticked or unticked as the reader left them.
    const wanted = new Set(draw.keys())
    for (const [key, group] of overlays.current) {
      if (wanted.has(key)) continue
      switcher.current?.removeLayer(group)
      instance.removeLayer(group)
      overlays.current.delete(key)
      ticked.current.delete(key)
    }
    for (const [key, fillGroup] of draw) {
      let group = overlays.current.get(key)
      // Listed and not on the map is unticked, which is the reader's say.
      const off = group !== undefined && ticked.current.has(key) && !instance.hasLayer(group)
      if (!group) {
        group = L.featureGroup()
        overlays.current.set(key, group)
      }
      group.clearLayers()
      fillGroup(group)
      if (off) instance.removeLayer(group)
      else group.addTo(instance)
    }

    // The tick-boxes, as a key. A plain map of locations has one layer and so
    // no list; anything with findings on it lists each of them with its count.
    const listing = expanded && categories.length ? categories : []
    const signature = listing.map((category) => categoryLabel(category)).join('\n')
    if (signature !== listed.current) {
      for (const key of ticked.current) {
        const group = overlays.current.get(key)
        if (group) switcher.current?.removeLayer(group)
      }
      ticked.current.clear()
      if (listing.length) {
        const control = ensureSwitcher(instance)
        for (const category of listing) {
          const group = overlays.current.get(category.key)
          if (!group) continue
          control.addOverlay(group, categoryLabel(category))
          ticked.current.add(category.key)
        }
      }
      listed.current = signature
    }
    arrange()

    // Framed on the boundary layer when there is one, on the pins otherwise.
    // A frame is the area the fieldwork covers, and one coordinate recorded in
    // the wrong hemisphere would otherwise squeeze the whole survey into a
    // thumbnail to keep that mistake on screen. The legend still counts the
    // strays, which is how you know to zoom out and look for them.
    const located = [...points, ...(manual?.points ?? [])]
    if (!located.length) return
    const frame = boundary?.bbox
    const bounds =
      frame && frame.length === 4
        ? L.latLngBounds([frame[1], frame[0]], [frame[3], frame[2]])
        : L.latLngBounds(located.map((point) => [point.lat, point.lon] as [number, number]))

    // Only when the ground to show has actually changed.
    //
    // This effect also re-runs to rebuild pins that are laid out in pixels,
    // which happens on every zoom - so fitting the bounds unconditionally
    // meant zooming in immediately undid itself, and the map could not be
    // zoomed at all. Comparing the extent rather than counting the rebuilds
    // also leaves the reader's view alone through the timed refresh, which
    // returns the same places and used to snap the map back every minute.
    const extent = bounds.isValid()
      ? [bounds.getSouth(), bounds.getWest(), bounds.getNorth(), bounds.getEast()]
          .map((value) => value.toFixed(5))
          .join(',')
      : ''
    if (!extent || extent === framed.current) return
    framed.current = extent
    instance.fitBounds(bounds, { padding: [24, 24], maxZoom: 14 })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [categories, points, manual, lines, detail, largest, measureLabel, areaVariable, boundary?.bbox, shape, redraws, generation, expanded])

  /**
   * Which layer is painted over which. Every vector shares one canvas and is
   * painted in the order it was added, so a layer ticked back on would come
   * back over everything: the lines go under the pins, the hand-entered pins
   * over the GPS ones they are compared with, and the duplicate rings on top.
   */
  function arrange() {
    overlays.current.get('lines')?.bringToFront()
    for (const [key, group] of overlays.current) if (key.startsWith('gps:')) group.bringToFront()
    for (const [key, group] of overlays.current) if (key.startsWith('manual:')) group.bringToFront()
    overlays.current.get('duplicates')?.bringToFront()
  }

  // Ticked back on, a layer takes its place in that order again.
  useEffect(() => {
    const instance = map.current
    if (!instance) return
    const settle = () => arrange()
    instance.on('overlayadd', settle)
    return () => {
      instance.off('overlayadd', settle)
    }
  }, [generation])



  // Leaflet measures its container once; inside a resizable widget it has to be
  // told when that changed, or half the map stays grey.
  useEffect(() => {
    if (!container.current || !map.current) return
    const observer = new ResizeObserver(() => map.current?.invalidateSize())
    observer.observe(container.current)
    return () => observer.disconnect()
  }, [])

  // The key is the list of layers on the map itself, each with its swatch and
  // its count: one list to read and tick, rather than a legend under the map
  // and the same names again in its corner.
  return (
    <div className="flex h-full min-h-[200px] flex-col">
      <div ref={container} className="min-h-0 flex-1 rounded" />
      <p className="mt-1 shrink-0 text-[11px] text-ink-500">
        {mapSummary(points.length, grouped)}
        {truncated && ' - showing the busiest only'}
        {tilesFailed && ' - no map tiles: this server cannot reach the tile host'}
      </p>
    </div>
  )
}
