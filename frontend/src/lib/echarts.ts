/*
 * The parts of ECharts this platform draws with, and nothing else.
 *
 * `echarts-for-react` on its own brings in the whole library - every chart
 * type, every component, both renderers - about a megabyte, 350 KB on the
 * wire, and the Overview page loads it the moment anybody signs in. On a field
 * office's connection that is the wait before the first page.
 *
 * So the chart types and components the builders in lib/charts.ts actually
 * use are registered here, and every chart is drawn through this instance. A
 * chart type or component added to a builder without being added here draws
 * nothing - `echarts-registry.test.ts` renders every chart the builder can
 * make through exactly this registration and fails on that.
 */

import { BarChart, BoxplotChart, FunnelChart, HeatmapChart, LineChart, PieChart, ScatterChart } from 'echarts/charts'
import {
  AxisPointerComponent,
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  TitleComponent,
  TooltipComponent,
  VisualMapComponent,
} from 'echarts/components'
import * as echarts from 'echarts/core'
import { LabelLayout } from 'echarts/features'
import { CanvasRenderer } from 'echarts/renderers'

/** What the builders use. Exported so the test can check it is enough. */
export const PARTS = [
  BarChart,
  BoxplotChart,
  FunnelChart,
  HeatmapChart,
  LineChart,
  PieChart,
  ScatterChart,
  AxisPointerComponent,
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  TitleComponent,
  TooltipComponent,
  VisualMapComponent,
  LabelLayout,
]

echarts.use([...PARTS, CanvasRenderer])

export { echarts }
