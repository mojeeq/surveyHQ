/**
 * What a new widget is made of: its title, its config and the room it takes.
 *
 * Lifted out of the add-widget dialog, where it was a nested ternary inside a
 * mutation and so could only be exercised by filling in the form and pressing
 * the button. It is the last thing that happens before a widget is written, and
 * the part where a mistake is silent: a key missing from the config draws a
 * widget that is simply blank, and a widget saved a size too small for what is
 * in it is a chart nobody can read.
 *
 * The dialog still decides what the answers are; this decides what they become.
 */

import type { WidgetType } from './types'

/** Everything the dialog has collected, by the time the widget is written. */
export interface WidgetAnswers {
  // Names already looked up, so this stays a function of its arguments.
  chartName?: string
  datasetName?: string
  indicatorName?: string

  latitude?: string
  longitude?: string
  measureAgg?: string
  measureVariable?: string
  detail?: string[]
  tiles?: string
  basemap?: string

  freshnessDatasets?: string[]
  html?: string

  qualityView?: string
  qualityChart?: string
  qualityLimit?: number

  showBreakdown?: boolean
  showTrend?: boolean
  /** Whether the chosen indicator has a breakdown to draw, which decides the size. */
  hasBreakdownVariable?: boolean

  content?: string
  deadline?: string
  deadlineLabel?: string

  caption?: string
}

/**
 * What to call a widget nobody has named.
 *
 * Every rung can come back empty - an indicator that is no longer in the list,
 * a dataset still loading - so the ladder ends on something rather than letting
 * a widget be written with no title at all.
 */
export function widgetTitle(
  kind: WidgetType,
  given: string,
  answers: WidgetAnswers = {},
): string {
  if (given) return given
  const ladder: Partial<Record<WidgetType, string | undefined>> = {
    chart: answers.chartName,
    quality: `Data quality: ${answers.datasetName ?? ''}`,
    map: 'Interview locations',
    html: 'Embedded content',
    freshness: 'Data freshness',
    countdown: answers.deadlineLabel || 'Countdown',
    indicator: answers.indicatorName,
  }
  return ladder[kind] || 'Widget'
}

/**
 * The config a widget of this kind is written with.
 *
 * Only the keys that kind uses: a map's columns are meaningless on a text note,
 * and writing them anyway leaves a widget carrying settings that nothing reads
 * and that the next person to open it has to work out the irrelevance of.
 *
 * The optional ones are left out rather than written empty, so that "no tiles
 * chosen" is the absence of a key and not a URL of "".
 */
export function widgetConfig(
  kind: WidgetType,
  answers: WidgetAnswers = {},
): Record<string, unknown> {
  const caption = (answers.caption ?? '').trim()
  const withCaption = (config: Record<string, unknown>) => ({
    ...config,
    ...(caption ? { caption } : {}),
  })

  switch (kind) {
    case 'map':
      return withCaption({
        latitude: answers.latitude,
        longitude: answers.longitude,
        measure_agg: answers.measureAgg,
        // A count needs no column to count, and carrying the last one chosen
        // would have the widget sum a variable the dialog no longer shows.
        measure_variable:
          answers.measureAgg === 'count' ? '' : answers.measureVariable,
        detail: answers.detail,
        ...((answers.tiles ?? '').trim() ? { tiles: (answers.tiles ?? '').trim() } : {}),
        ...(answers.basemap !== 'streets' ? { basemap: answers.basemap } : {}),
      })
    case 'freshness':
      return withCaption({
        dataset_ids: answers.freshnessDatasets,
        warn_hours: 24,
        critical_hours: 72,
      })
    case 'html':
      return withCaption({ html: answers.html })
    case 'quality':
      return withCaption({
        quality_view: answers.qualityView,
        ...(answers.qualityChart ? { quality_chart: answers.qualityChart } : {}),
        ...(answers.qualityLimit ? { quality_limit: answers.qualityLimit } : {}),
      })
    case 'indicator':
      return withCaption({
        show_breakdown: answers.showBreakdown,
        show_trend: answers.showTrend,
      })
    case 'text':
      return withCaption({ content: answers.content })
    case 'countdown':
      // A local datetime from the browser, sent as an instant so the count
      // reads the same wherever the dashboard is opened.
      return withCaption({
        target: new Date(answers.deadline ?? '').toISOString(),
        label: answers.deadlineLabel,
      })
    default:
      return withCaption({})
  }
}

/** How much of the grid a new widget takes, before anybody resizes it. */
export function widgetLayout(
  kind: WidgetType,
  answers: WidgetAnswers = {},
): { w: number; h: number } {
  switch (kind) {
    case 'map':
      return { w: 6, h: 6 }
    case 'freshness':
      return { w: 4, h: 4 }
    case 'countdown':
      return { w: 3, h: 3 }
    case 'indicator':
      // A tile with a chart under it needs the room for one.
      return answers.showBreakdown && answers.hasBreakdownVariable
        ? { w: 4, h: 5 }
        : { w: 3, h: 3 }
    default:
      return { w: 6, h: 4 }
  }
}

/**
 * Whether a dataset looks like it holds GPS that was never split into columns.
 *
 * A map needs a latitude and a longitude, and an ODK export often carries both
 * in one text field - so a dataset with a column called "gps" and no numeric
 * latitude beside it is one where the map will offer nothing to plot. Saying so
 * is more use than an empty pair of dropdowns.
 *
 * A numeric latitude anywhere settles it: the split has happened, whatever else
 * the dataset is carrying.
 */
export function looksLikeAnUnsplitGps(
  variables: { name: string; var_type: string }[],
): boolean {
  const words = (name: string) => name.toLowerCase().split(/[^a-z0-9]+/)
  const hasCoordinate = variables.some(
    (v) =>
      v.var_type === 'numeric' &&
      words(v.name).some((w) => w === 'latitude' || w === 'lat'),
  )
  if (hasCoordinate) return false
  return variables.some(
    (v) =>
      v.var_type !== 'numeric' &&
      words(v.name).some((w) =>
        ['gps', 'geopoint', 'gpspoint', 'location', 'coordinates', 'latlon'].includes(w),
      ),
  )
}
