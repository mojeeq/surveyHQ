/*
 * A chart, drawn with only the parts of ECharts this platform registers.
 *
 * The same component `echarts-for-react` exports, built on its core entry
 * instead of the default one, which imports the whole library. See
 * lib/echarts.ts for what is registered and why.
 */

import ReactEChartsCore from 'echarts-for-react/lib/core'
import type { EChartsReactProps } from 'echarts-for-react/lib/types'
import { forwardRef } from 'react'

import { echarts } from '@/lib/echarts'

const ReactECharts = forwardRef<ReactEChartsCore, Omit<EChartsReactProps, 'echarts'>>(
  (props, ref) => <ReactEChartsCore ref={ref} echarts={echarts} {...props} />,
)
ReactECharts.displayName = 'ReactECharts'

export default ReactECharts
