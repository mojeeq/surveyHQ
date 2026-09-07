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
  [detail: string]: unknown
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
}: {
  points: MapPoint[]
  detail?: string[]
  measure?: { agg: string; variable: string }
  /** Which ground to start on. A custom tile URL overrides it. */
  basemap?: string
  tiles?: string
  truncated?: boolean
}) {
  const container = useRef<HTMLDivElement>(null)
  const map = useRef<L.Map | null>(null)
  const layer = useRef<L.LayerGroup | null>(null)
  const grounds = useRef<Partial<Record<BasemapName, L.Layer>>>({})
  const [tilesFailed, setTilesFailed] = useState(false)
  const custom = tiles?.trim()
  const chosen = basemapOf(basemap)

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
      L.control
        .layers(
          Object.fromEntries(
            BASEMAP_NAMES.map((name) => [BASEMAPS[name].label, grounds.current[name]!]),
          ),
          {},
          { position: 'topright' },
        )
        .addTo(instance)
    }

    layer.current = L.layerGroup().addTo(instance)
    return () => {
      instance.remove()
      map.current = null
      grounds.current = {}
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

  useEffect(() => {
    if (!map.current || !layer.current) return
    layer.current.clearLayers()
    if (!points.length) return

    for (const point of points) {
      const value = Number(point.value) || 0
      const marker = L.circleMarker([point.lat, point.lon], {
        // Area, not radius, carries the value: doubling the radius of a circle
        // quadruples what the eye reads off it.
        radius: 5 + 11 * Math.sqrt(Math.abs(value) / largest),
        color: '#1d4ed8',
        weight: 1,
        fillColor: '#3b82f6',
        fillOpacity: 0.6,
      })
      // Built when the popup opens, not when the marker is made: the string is
      // the expensive part, and at fifty thousand points all but one of them
      // is work for a popup nobody opens.
      marker.bindPopup(() => {
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
          details +
          `<div style="color:#94a3b8;margin-top:4px">${point.lat.toFixed(5)}, ${point.lon.toFixed(
            5,
          )}</div>` +
          `</div>`
        )
      })
      marker.addTo(layer.current)
    }

    const bounds = L.latLngBounds(points.map((point) => [point.lat, point.lon] as [number, number]))
    map.current.fitBounds(bounds, { padding: [24, 24], maxZoom: 14 })
  }, [points, detail, largest, measureLabel])

  // Leaflet measures its container once; inside a resizable widget it has to be
  // told when that changed, or half the map stays grey.
  useEffect(() => {
    if (!container.current || !map.current) return
    const observer = new ResizeObserver(() => map.current?.invalidateSize())
    observer.observe(container.current)
    return () => observer.disconnect()
  }, [])

  return (
    <div className="flex h-full min-h-[200px] flex-col">
      <div ref={container} className="min-h-0 flex-1 rounded" />
      <p className="mt-1 shrink-0 text-[11px] text-ink-400">
        {points.length ? `${formatNumber(points.length)} location(s)` : 'No located interviews'}
        {truncated && ' - showing the busiest only'}
        {tilesFailed && ' - no map tiles: this server cannot reach the tile host'}
      </p>
    </div>
  )
}
