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
import { formatNumber } from '@/lib/format'

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

export interface MapPoint {
  lat: number
  lon: number
  /** The aggregated value: how many interviews, or the sum asked for. */
  value: number
  /** How many rows are behind the pin, which is not the value when it is a sum. */
  rows: number
  /** Set when the map is checking a recorded area against where the point is. */
  area_status?: AreaStatus
  area_expected?: string | null
  recorded_area_label?: unknown
  [detail: string]: unknown
}

export type AreaStatus = 'match' | 'mismatch' | 'outside' | 'unrecorded'

/**
 * How each verdict is drawn, in the order the legend lists them.
 *
 * The mismatch is red and the largest because it is the finding: a record
 * whose enumeration area disagrees with the ground under it is a code typed
 * wrong, an interviewer in the wrong area, or a boundary the field reads
 * differently from the office. Agreement is the quiet majority and is drawn
 * as such, so a screen of green with four red dots reads correctly at a
 * glance rather than needing to be counted.
 */
export const VERDICTS: Record<AreaStatus, { label: string; color: string; radius: number }> = {
  mismatch: { label: 'Area does not match the GPS', color: '#d7301f', radius: 7 },
  outside: { label: 'Outside every area in the layer', color: '#f0a202', radius: 6 },
  unrecorded: { label: 'No area recorded', color: '#6a51a3', radius: 6 },
  match: { label: 'Area agrees with the GPS', color: '#2c9e4b', radius: 4 },
}

export const VERDICT_ORDER: AreaStatus[] = ['mismatch', 'outside', 'unrecorded', 'match']

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
export const DEFAULT_POINT_FILL = '#3b82f6'
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
function escape(value: unknown): string {
  return String(value ?? '-').replace(
    /[&<>"']/g,
    (character) =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[character]!,
  )
}

export default function MapWidget({
  points,
  detail = [],
  measure,
  basemap,
  tiles,
  truncated = false,
  boundary,
  areas,
  areaVariable,
  icon,
  pointColor,
  pointSize,
  pointOpacity,
  sizeByValue = true,
}: {
  points: MapPoint[]
  detail?: string[]
  measure?: { agg: string; variable: string }
  /** Which ground to start on. A custom tile URL overrides it. */
  basemap?: string
  tiles?: string
  truncated?: boolean
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
}) {
  const container = useRef<HTMLDivElement>(null)
  const map = useRef<L.Map | null>(null)
  const layer = useRef<L.LayerGroup | null>(null)
  const outlines = useRef<L.GeoJSON | null>(null)
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
    // rebuilt map did, leaving every pin in one dot in the Pacific.
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
          { position: 'topright' },
        )
        .addTo(instance)
      switcherIsOurs.current = false
    }

    layer.current = L.layerGroup().addTo(instance)

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
    }
    // Built once per tile source. Switching between the named grounds is the
    // effect below, which does not tear the map down and lose the reader's
    // pan and zoom.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [custom])

  // The widget's chosen ground, changed in its settings after the map was
  // built. A ground the reader picked from the switcher is left alone.
  useEffect(() => {
    const instance = map.current
    const next = grounds.current[chosen]
    if (!instance || !next || instance.hasLayer(next)) return
    for (const ground of Object.values(grounds.current)) instance.removeLayer(ground)
    instance.addLayer(next)
  }, [chosen])

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
          drawnLayer.bindTooltip(String(name), {
            direction: 'center',
            className: 'boundary-label',
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
    if (!switcher.current) {
      // A custom tile URL means no choice of ground and so no switcher; one
      // is made here, holding nothing but this tick-box.
      switcher.current = L.control
        .layers({}, {}, { position: 'topright' })
        .addTo(instance)
      switcherIsOurs.current = true
    }
    switcher.current.addOverlay(drawn, boundary?.name || 'Boundaries')
    const ours = switcherIsOurs.current

    // Ticked back on, the outlines have to sink again. Every vector here
    // shares one canvas and is painted in the order it was added, so a layer
    // put back last is painted last: the frame came back over the pins rather
    // than under them, and a boundary drawn on top of the records inside it is
    // exactly what bringToBack is here to prevent.
    const sink = (event: { layer: L.Layer }) => {
      if (event.layer === drawn) drawn.bringToBack()
    }
    instance.on('overlayadd', sink)

    return () => {
      instance.off('overlayadd', sink)
      instance.removeLayer(drawn)
      if (outlines.current === drawn) outlines.current = null
      // Only while the map is still standing: its own teardown takes the
      // control with it and clears the ref.
      if (switcher.current) {
        switcher.current.removeLayer(drawn)
        if (ours) {
          switcher.current.remove()
          switcher.current = null
          switcherIsOurs.current = false
        }
      }
    }
  }, [areas, boundary?.label, boundary?.name])

  useEffect(() => {
    if (!map.current || !layer.current) return
    layer.current.clearLayers()
    if (!points.length) return

    for (const point of points) {
      const value = Number(point.value) || 0
      const verdict = point.area_status ? VERDICTS[point.area_status] : undefined
      // Two different maps in one component. Asked "where is the work", the
      // pin's area can carry the value, because that is the question. Asked
      // "does the recorded area agree with the GPS", size would be a second
      // variable competing with the colour that carries the answer, so every
      // pin is the size its verdict says and only the colour speaks.
      const base = pointSize && pointSize > 0 ? pointSize : DEFAULT_POINT_SIZE
      const scaled = sizeByValue
        ? // Area, not radius, carries the value: doubling the radius of a
          // circle quadruples what the eye reads off it.
          base * 0.45 + base * Math.sqrt(Math.abs(value) / largest)
        : base
      const fill = pointColor || DEFAULT_POINT_FILL
      const pin = marker(
        map.current,
        shape,
        [point.lat, point.lon],
        verdict ? verdict.radius : scaled,
        {
          color: verdict ? verdict.color : shade(fill),
          weight: 1,
          fillColor: verdict ? verdict.color : fill,
          fillOpacity: verdict ? 0.85 : (pointOpacity ?? DEFAULT_POINT_OPACITY),
        },
      )
      // Built when the popup opens, not when the marker is made: the string is
      // the expensive part, and at fifty thousand points all but one of them
      // is work for a popup nobody opens.
      pin.bindPopup(() => {
        const details = detail
          .map(
            (name) =>
              `<div><span style="color:#64748b">${escape(name)}:</span> ${escape(
                point[name],
              )}</div>`,
          )
          .join('')
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
              `<div><span style="color:#64748b">${escape(areaVariable || 'Recorded')}:</span> ` +
              `${escape(point.recorded_area_label ?? point.recorded_area ?? '-')}</div>` +
              `<div><span style="color:#64748b">Falls in:</span> ${escape(
                point.area_expected ?? 'no area in this layer',
              )}</div></div>`
            : '') +
          details +
          `<div style="color:#94a3b8;margin-top:4px">${point.lat.toFixed(5)}, ${point.lon.toFixed(
            5,
          )}</div>` +
          `</div>`
        )
      })
      pin.addTo(layer.current)
    }

    // Framed on the boundary layer when there is one, on the pins otherwise.
    // A frame is the area the fieldwork covers, and one coordinate recorded in
    // the wrong hemisphere would otherwise squeeze the whole survey into a
    // thumbnail to keep that mistake on screen. The legend still counts the
    // strays, which is how you know to zoom out and look for them.
    const frame = boundary?.bbox
    const bounds =
      frame && frame.length === 4
        ? L.latLngBounds([frame[1], frame[0]], [frame[3], frame[2]])
        : L.latLngBounds(points.map((point) => [point.lat, point.lon] as [number, number]))

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
    map.current.fitBounds(bounds, { padding: [24, 24], maxZoom: 14 })
  }, [points, detail, largest, measureLabel, areaVariable, boundary?.bbox, shape, redraws])



  // Leaflet measures its container once; inside a resizable widget it has to be
  // told when that changed, or half the map stays grey.
  useEffect(() => {
    if (!container.current || !map.current) return
    const observer = new ResizeObserver(() => map.current?.invalidateSize())
    observer.observe(container.current)
    return () => observer.disconnect()
  }, [])

  // Only the verdicts actually present, in severity order. A legend listing
  // four outcomes when three of them have no pins is four things to read and
  // one fact.
  const present = VERDICT_ORDER.filter((status) =>
    points.some((point) => point.area_status === status),
  )

  return (
    <div className="flex h-full min-h-[200px] flex-col">
      <div ref={container} className="min-h-0 flex-1 rounded" />
      {present.length > 0 && (
        <div className="mt-1 flex shrink-0 flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-ink-500 dark:text-dark-500">
          {present.map((status) => (
            <span key={status} className="flex items-center gap-1">
              <span
                className="inline-block h-2 w-2 rounded-full"
                style={{ backgroundColor: VERDICTS[status].color }}
              />
              {VERDICTS[status].label}
              <span className="text-ink-400">
                ({formatNumber(points.filter((point) => point.area_status === status).length)})
              </span>
            </span>
          ))}
        </div>
      )}
      <p className="mt-1 shrink-0 text-[11px] text-ink-400">
        {points.length ? `${formatNumber(points.length)} location(s)` : 'No located interviews'}
        {truncated && ' - showing the busiest only'}
        {tilesFailed && ' - no map tiles: this server cannot reach the tile host'}
      </p>
    </div>
  )
}
