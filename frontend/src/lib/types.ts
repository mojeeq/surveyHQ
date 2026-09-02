// Mirrors the backend's pydantic schemas.

export type Role = 'admin' | 'manager' | 'analyst' | 'viewer'

export interface User {
  id: string
  email: string
  full_name: string
  role: Role
  is_active: boolean
  // Confines this user to the projects they belong to, shutting off the
  // shared area every other user can see.
  restricted_to_projects: boolean
  /** Someone else chose this password, so the holder has to set their own. */
  must_change_password: boolean
  created_at: string
  last_login_at: string | null
}

export type ProjectStatus = 'active' | 'paused' | 'closed'

export interface ProjectMember {
  id: string
  user_id: string
  role: Role
  email: string
  full_name: string
}

export interface Project {
  id: string
  name: string
  slug: string
  description: string
  status: ProjectStatus
  starts_on: string | null
  ends_on: string | null
  created_at: string
  updated_at: string
  dataset_count: number
  dashboard_count: number
  member_count: number
  // This caller's role over the project, so the UI can hide what they cannot do
  your_role: Role | null
  members?: ProjectMember[]
}

export type VariableType = 'numeric' | 'categorical' | 'text' | 'datetime' | 'boolean'

export interface Variable {
  id: string
  name: string
  label: string
  var_type: VariableType
  storage_type: string
  position: number
  n_missing: number
  n_unique: number
  min_value: number | null
  max_value: number | null
  mean_value: number | null
  value_labels: Record<string, string>
}

export type DatasetStatus = 'pending' | 'processing' | 'ready' | 'failed'

export interface Dataset {
  id: string
  name: string
  slug: string
  description: string
  source: 'upload' | 'survey_solutions'
  source_ref: string
  connection_id: string | null
  // Null means the shared area, visible to everyone
  project_id: string | null
  status: DatasetStatus
  error: string
  row_count: number
  column_count: number
  file_size: number
  tags: string[]
  meta: {
    monitoring_fields?: Record<string, string>
    warnings?: string[]
    /** Which file inside an export archive this dataset holds, and so which
     *  file a later archive's rows get appended to. */
    archive_member?: string
  }
  version: number
  refreshed_at: string | null
  created_at: string
  updated_at: string
  variables?: Variable[]
}

export type Aggregation =
  | 'count' | 'count_distinct' | 'sum' | 'mean' | 'median'
  | 'min' | 'max' | 'stddev' | 'p25' | 'p75' | 'p90' | 'share'

export type DateGrain = 'day' | 'week' | 'month' | 'quarter' | 'year'

export interface Dimension {
  variable: string
  alias?: string | null
  grain?: DateGrain | null
  bin_width?: number | null
  limit?: number | null
}

export interface Measure {
  agg: Aggregation
  variable?: string | null
  alias?: string | null
  weight?: string | null
}

export type FilterOperator =
  | 'eq' | 'ne' | 'gt' | 'gte' | 'lt' | 'lte' | 'in' | 'not_in'
  | 'contains' | 'not_contains' | 'starts_with' | 'ends_with'
  | 'between' | 'is_null' | 'is_not_null'

export interface Condition {
  variable: string
  operator: FilterOperator
  value: unknown
  use_label?: boolean
}

export interface FilterGroup {
  op: 'and' | 'or'
  conditions: Condition[]
  groups: FilterGroup[]
}

export interface SortSpec {
  field: string
  direction: 'asc' | 'desc'
}

export interface QuerySpec {
  dimensions: Dimension[]
  measures: Measure[]
  filters: FilterGroup
  sort: SortSpec[]
  limit: number
  offset?: number
  use_labels?: boolean
  drop_missing?: boolean
}

export interface QueryColumn {
  name: string
  label: string
  type: 'dimension' | 'measure'
  data_type: string
}

export interface QueryResult {
  columns: QueryColumn[]
  rows: unknown[][]
  row_count: number
  truncated: boolean
  sql: string
  duration_ms: number
}

export interface FrequencyRow {
  value: unknown
  label: string
  count: number
  percent: number
  valid_percent: number
  cumulative_percent: number
}

export interface FrequencyResult {
  variable: string
  label: string
  rows: FrequencyRow[]
  total: number
  missing: number
  distinct: number
}

export interface CrosstabRequest {
  row_variable: string
  column_variable: string
  measure: Measure
  filters: FilterGroup
  percentages: 'none' | 'row' | 'column' | 'total'
  include_totals: boolean
  use_labels: boolean
}

export interface CrosstabResult {
  row_variable: string
  column_variable: string
  row_labels: string[]
  column_labels: string[]
  values: (number | null)[][]
  row_totals: number[]
  column_totals: number[]
  grand_total: number
  percentages: string
  chi_square: { statistic: number; dof: number; cramers_v: number } | null
}

export interface SummaryStats {
  variable: string
  label: string
  count: number
  missing: number
  mean: number | null
  std: number | null
  min: number | null
  p25: number | null
  median: number | null
  p75: number | null
  max: number | null
  sum: number | null
}

export interface Connection {
  id: string
  name: string
  base_url: string
  workspace: string
  username: string
  verify_ssl: boolean
  is_active: boolean
  sync_enabled: boolean
  sync_interval_minutes: number
  export_format: 'STATA' | 'Tabular' | 'SPSS'
  questionnaires: string[]
  interview_status: string
  last_sync_at: string | null
  last_sync_status: 'never' | 'running' | 'success' | 'failed'
  last_sync_error: string
  server_info: Record<string, unknown>
  created_at: string
  has_password: boolean
}

export interface Questionnaire {
  id: string
  version: number
  title: string
  variable: string
  identity: string
  last_entry_date: string | null
}

export interface SyncRun {
  id: string
  connection_id: string
  questionnaire: string
  status: 'never' | 'running' | 'success' | 'failed'
  started_at: string
  finished_at: string | null
  rows_imported: number
  datasets_created: number
  message: string
  log: string[]
}

export type ChartType =
  | 'bar' | 'horizontal_bar' | 'stacked_bar' | 'line' | 'area' | 'pie'
  | 'donut' | 'scatter' | 'table' | 'kpi' | 'heatmap' | 'crosstab' | 'map'
  | 'gauge' | 'funnel'

export interface Chart {
  id: string
  name: string
  description: string
  dataset_id: string
  chart_type: ChartType
  // A cross-tab is saved with a crosstab request in place of a query; the
  // server branches on which one is present when rendering it.
  spec: {
    query?: QuerySpec
    crosstab?: CrosstabRequest
    encoding?: Record<string, string>
    options?: Record<string, unknown>
  }
  created_at: string
  updated_at: string
}

export interface ArchiveImport {
  datasets: Dataset[]
  /** "R_demographics.dta -> R_demographics (401 rows)" */
  created: string[]
  /** "R_demographics.dta -> R_demographics (401 + 381 = 782 rows)" */
  appended: string[]
  skipped: string[]
  warnings: string[]
  rows: number
}

export type WidgetType = 'chart' | 'table' | 'kpi' | 'indicator' | 'text' | 'crosstab'

export interface Widget {
  id: string
  dashboard_id: string
  title: string
  widget_type: WidgetType
  chart_id: string | null
  indicator_id: string | null
  dataset_id: string | null
  config: Record<string, unknown>
  layout: { x?: number; y?: number; w?: number; h?: number }
  position: number
}

export interface Dashboard {
  id: string
  name: string
  slug: string
  description: string
  filters: Record<string, unknown>[]
  project_id: string | null
  is_public: boolean
  public_token: string | null
  refresh_interval_seconds: number
  created_at: string
  updated_at: string
  widgets?: Widget[]
}

export type Direction = 'higher_is_better' | 'lower_is_better' | 'neutral'
export type Severity = 'info' | 'warning' | 'critical'
export type IndicatorState = 'ok' | 'warning' | 'critical' | 'unknown'

export interface Indicator {
  id: string
  name: string
  description: string
  dataset_id: string
  spec: QuerySpec
  unit: string
  value_format: string
  target_value: number | null
  warning_threshold: number | null
  critical_threshold: number | null
  direction: Direction
  breakdown_variable: string
  is_active: boolean
  display_order: number
  last_value: number | null
  last_computed_at: string | null
  created_at: string
}

export interface IndicatorValue {
  indicator_id: string
  name: string
  value: number | null
  unit: string
  value_format: string
  target_value: number | null
  progress_percent: number | null
  status: IndicatorState
  direction: Direction
  breakdown: Record<string, number>
  computed_at: string | null
  error: string | null
  trend: { t: string; v: number | null }[]
}

export interface AlertRule {
  id: string
  name: string
  description: string
  indicator_id: string | null
  dataset_id: string | null
  condition: { operator: string; value: number }
  severity: Severity
  channels: string[]
  recipients: string[]
  cooldown_minutes: number
  is_active: boolean
  last_triggered_at: string | null
  created_at: string
}

export interface Alert {
  id: string
  rule_id: string | null
  title: string
  message: string
  severity: Severity
  status: 'open' | 'acknowledged' | 'resolved'
  payload: Record<string, unknown>
  created_at: string
  acknowledged_at: string | null
  resolved_at: string | null
}

export type CheckType =
  | 'missing_rate' | 'value_range' | 'duplicates' | 'outliers'
  | 'consistency' | 'interview_duration' | 'gps_missing' | 'constant_value'

export interface QualityResult {
  id: string
  rule_id: string
  run_at: string
  passed: boolean
  failed_rows: number
  total_rows: number
  failure_rate: number
  details: Record<string, unknown>
  message: string
}

export interface QualityRule {
  id: string
  name: string
  dataset_id: string
  check_type: CheckType
  config: Record<string, unknown>
  severity: Severity
  threshold: number
  is_active: boolean
  created_at: string
  latest_result: QualityResult | null
}

export interface Job {
  id: string
  job_type: string
  status: 'queued' | 'running' | 'success' | 'failed' | 'cancelled'
  title: string
  progress: number
  params: Record<string, unknown>
  result: Record<string, unknown>
  error: string
  started_at: string | null
  finished_at: string | null
  created_at: string
}

export interface Notification {
  id: string
  title: string
  body: string
  level: string
  link: string
  created_at: string
  read_at: string | null
}

export interface FieldProgress {
  dataset_id: string
  dataset_name: string
  total_records: number
  detected_fields: Record<string, string>
  available_views: string[]
  status_breakdown: { status: string; count: number }[]
  submissions_over_time: { period: string; count: number; cumulative: number }[]
  by_interviewer: Record<string, unknown>[]
  by_supervisor: Record<string, unknown>[]
  coverage_by_area: { area: string; interviews: number }[]
  geo_points: Record<string, unknown>[]
  completed_records: number
  completion_rate: number | null
}

export interface MonitoringSummary {
  datasets: number
  total_records: number
  indicators: number
  indicators_ok: number
  indicators_warning: number
  indicators_critical: number
  open_alerts: number
  critical_alerts: number
  failing_quality_checks: number
  recently_refreshed: number
}

export interface Page<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

export interface ApiKeyOut {
  id: string
  name: string
  prefix: string
  created_at: string
  last_used_at: string | null
  revoked: boolean
}
