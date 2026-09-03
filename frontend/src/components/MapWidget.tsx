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

export const DEFAULT_TILES = 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png'
const ATTRIBUTION = '© OpenStreetMap contributors'

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
  return String(value ?? '–').replace(
    /[&<>"']/g,
    (character) =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[character]!,
  )
}

export default function MapWidget({
  points,
  detail = [],
  measure,
  tiles = DEFAULT_TILES,
  truncated = false,
}: {
  points: MapPoint[]
  detail?: string[]
  measure?: { agg: string; variable: string }
  tiles?: string
  truncated?: boolean
}) {
  const container = useRef<HTMLDivElement>(null)
  const map = useRef<L.Map | null>(null)
  const layer = useRef<L.LayerGroup | null>(null)
  const [tilesFailed, setTilesFailed] = useState(false)

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
    map.current = L.map(container.current, { attributionControl: true }).setView([0, 0], 2)
    setTilesFailed(false)
    const basemap = L.tileLayer(tiles, { attribution: ATTRIBUTION, maxZoom: 19 })
    // A server with no route to the tile host is a normal deployment, not a
    // fault: the pins are the data and they still draw. Saying so beats a grey
    // rectangle that looks like a bug.
    basemap.on('tileerror', () => setTilesFailed(true))
    basemap.addTo(map.current)
    layer.current = L.layerGroup().addTo(map.current)
    return () => {
      map.current?.remove()
      map.current = null
    }
  }, [tiles])

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
      const details = detail
        .map(
          (name) =>
            `<div><span style="color:#64748b">${escape(name)}:</span> ${escape(point[name])}</div>`,
        )
        .join('')
      marker.bindPopup(
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
          `</div>`,
      )
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
        {truncated && ' — showing the busiest only'}
        {tilesFailed && ' — no map tiles: this server cannot reach the tile host'}
      </p>
    </div>
  )
}
