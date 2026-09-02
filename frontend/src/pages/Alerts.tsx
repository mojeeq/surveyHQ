import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '@/lib/api'
import { useAuth } from '@/hooks/useAuth'
import { useToast } from '@/hooks/useToast'
import { formatNumber, relativeTime } from '@/lib/format'
import type { Alert, AlertRule, Indicator, Severity } from '@/lib/types'
import {
  Badge,
  Card,
  EmptyState,
  ErrorNote,
  Field,
  Loading,
  Modal,
  PageHeader,
  Tabs,
} from '@/components/ui'

const SEVERITY = {
  info: { tone: 'info', icon: 'ℹ' },
  warning: { tone: 'warning', icon: '▲' },
  critical: { tone: 'danger', icon: '■' },
} as const

export default function Alerts() {
  const { can } = useAuth()
  const toast = useToast()
  const queryClient = useQueryClient()
  const [tab, setTab] = useState<'alerts' | 'rules'>('alerts')
  const [statusFilter, setStatusFilter] = useState('open')
  const [creating, setCreating] = useState(false)

  const alerts = useQuery({
    queryKey: ['alerts', statusFilter],
    queryFn: () =>
      api.get<Alert[]>(
        `/monitoring/alerts?limit=200${statusFilter ? `&status=${statusFilter}` : ''}`,
      ),
    refetchInterval: 60_000,
  })
  const rules = useQuery({
    queryKey: ['alert-rules'],
    queryFn: () => api.get<AlertRule[]>('/monitoring/alert-rules'),
  })

  const act = useMutation({
    mutationFn: ({ id, action }: { id: string; action: 'acknowledge' | 'resolve' }) =>
      api.post(`/monitoring/alerts/${id}/${action}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['alerts'] }),
  })

  const testRule = useMutation({
    mutationFn: (id: string) =>
      api.post<{ triggered: boolean; message: string }>(`/monitoring/alert-rules/${id}/test`),
    onSuccess: (result) => {
      toast.push(result.message, result.triggered ? 'error' : 'success')
      queryClient.invalidateQueries({ queryKey: ['alerts'] })
    },
  })

  const removeRule = useMutation({
    mutationFn: (id: string) => api.delete(`/monitoring/alert-rules/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['alert-rules'] }),
  })

  return (
    <>
      <PageHeader
        title="Alerts"
        description="Rules watch your indicators and raise an alert when a threshold is crossed."
        actions={
          can('manager') && (
            <button className="btn-primary" onClick={() => setCreating(true)}>
              New alert rule
            </button>
          )
        }
      />

      <Tabs
        tabs={[
          { id: 'alerts', label: 'Alerts', count: alerts.data?.length },
          { id: 'rules', label: 'Rules', count: rules.data?.length },
        ]}
        active={tab}
        onChange={(id) => setTab(id as 'alerts' | 'rules')}
      />

      <div className="mt-4">
        {tab === 'alerts' && (
          <>
            <div className="mb-4 flex gap-1">
              {[
                { value: 'open', label: 'Open' },
                { value: 'acknowledged', label: 'Acknowledged' },
                { value: 'resolved', label: 'Resolved' },
                { value: '', label: 'All' },
              ].map((option) => (
                <button
                  key={option.value}
                  onClick={() => setStatusFilter(option.value)}
                  className={`rounded-lg px-3 py-1.5 text-xs font-medium ${
                    statusFilter === option.value
                      ? 'bg-ink-800 text-white'
                      : 'bg-white text-ink-600 hover:bg-ink-100'
                  }`}
                >
                  {option.label}
                </button>
              ))}
            </div>

            {alerts.isLoading ? (
              <Loading />
            ) : alerts.error ? (
              <ErrorNote error={alerts.error} />
            ) : !alerts.data?.length ? (
              <Card>
                <EmptyState
                  icon="✓"
                  title="Nothing to worry about"
                  description={
                    statusFilter === 'open'
                      ? 'No open alerts. Everything is within its thresholds.'
                      : 'No alerts match this filter.'
                  }
                />
              </Card>
            ) : (
              <div className="space-y-2">
                {alerts.data.map((alert) => (
                  <Card key={alert.id} bodyClassName="p-4">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <Badge
                            tone={SEVERITY[alert.severity].tone}
                            icon={SEVERITY[alert.severity].icon}
                          >
                            {alert.severity}
                          </Badge>
                          <h3 className="text-sm font-semibold text-ink-800">{alert.title}</h3>
                          <Badge
                            tone={
                              alert.status === 'open'
                                ? 'danger'
                                : alert.status === 'acknowledged'
                                  ? 'warning'
                                  : 'success'
                            }
                          >
                            {alert.status}
                          </Badge>
                        </div>
                        <p className="mt-1.5 text-sm text-ink-600">{alert.message}</p>
                        <p className="mt-1 text-xs text-ink-400">
                          Raised {relativeTime(alert.created_at)}
                        </p>
                      </div>
                      {alert.status !== 'resolved' && (
                        <div className="flex gap-1">
                          {alert.status === 'open' && (
                            <button
                              className="btn-secondary btn-sm"
                              onClick={() =>
                                act.mutate({ id: alert.id, action: 'acknowledge' })
                              }
                            >
                              Acknowledge
                            </button>
                          )}
                          <button
                            className="btn-secondary btn-sm"
                            onClick={() => act.mutate({ id: alert.id, action: 'resolve' })}
                          >
                            Resolve
                          </button>
                        </div>
                      )}
                    </div>
                  </Card>
                ))}
              </div>
            )}
          </>
        )}

        {tab === 'rules' &&
          (rules.isLoading ? (
            <Loading />
          ) : !rules.data?.length ? (
            <Card>
              <EmptyState
                icon="!"
                title="No alert rules"
                description="A rule watches one indicator and raises an alert when its value crosses the threshold you set."
                action={
                  can('manager') && (
                    <button className="btn-primary btn-sm" onClick={() => setCreating(true)}>
                      Create a rule
                    </button>
                  )
                }
              />
            </Card>
          ) : (
            <div className="space-y-2">
              {rules.data.map((rule) => (
                <Card key={rule.id} bodyClassName="p-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <h3 className="text-sm font-semibold text-ink-800">{rule.name}</h3>
                        <Badge
                          tone={SEVERITY[rule.severity].tone}
                          icon={SEVERITY[rule.severity].icon}
                        >
                          {rule.severity}
                        </Badge>
                        {!rule.is_active && <Badge>paused</Badge>}
                      </div>
                      <p className="mt-1 text-sm text-ink-500">
                        Alerts when the indicator value is{' '}
                        <strong>{describeOperator(rule.condition.operator)}</strong>{' '}
                        {formatNumber(rule.condition.value)} · cooldown {rule.cooldown_minutes} min
                        · via {rule.channels.join(', ')}
                      </p>
                      <p className="mt-1 text-xs text-ink-400">
                        Last triggered {relativeTime(rule.last_triggered_at)}
                      </p>
                    </div>
                    <div className="flex gap-1">
                      <button
                        className="btn-secondary btn-sm"
                        onClick={() => testRule.mutate(rule.id)}
                        disabled={testRule.isPending}
                      >
                        Test now
                      </button>
                      {can('manager') && (
                        <button
                          className="btn-ghost btn-sm text-red-600"
                          onClick={() => {
                            if (confirm(`Delete the rule "${rule.name}"?`))
                              removeRule.mutate(rule.id)
                          }}
                        >
                          Delete
                        </button>
                      )}
                    </div>
                  </div>
                </Card>
              ))}
            </div>
          ))}
      </div>

      {creating && <RuleModal onClose={() => setCreating(false)} />}
    </>
  )
}

function describeOperator(operator: string): string {
  return (
    {
      lt: 'below',
      lte: 'at or below',
      gt: 'above',
      gte: 'at or above',
      eq: 'exactly',
      ne: 'not',
    }[operator] ?? operator
  )
}

function RuleModal({ onClose }: { onClose: () => void }) {
  const toast = useToast()
  const queryClient = useQueryClient()
  const [name, setName] = useState('')
  const [indicatorId, setIndicatorId] = useState('')
  const [operator, setOperator] = useState('lt')
  const [value, setValue] = useState('')
  const [severity, setSeverity] = useState<Severity>('warning')
  const [cooldown, setCooldown] = useState('60')
  const [email, setEmail] = useState(false)
  const [recipients, setRecipients] = useState('')

  const indicators = useQuery({
    queryKey: ['indicators'],
    queryFn: () => api.get<Indicator[]>('/monitoring/indicators'),
  })

  const create = useMutation({
    mutationFn: () =>
      api.post('/monitoring/alert-rules', {
        name,
        indicator_id: indicatorId,
        condition: { operator, value: Number(value) },
        severity,
        cooldown_minutes: Number(cooldown),
        channels: email ? ['in_app', 'email'] : ['in_app'],
        recipients: recipients
          .split(',')
          .map((item) => item.trim())
          .filter(Boolean),
      }),
    onSuccess: () => {
      toast.push('Alert rule created', 'success')
      queryClient.invalidateQueries({ queryKey: ['alert-rules'] })
      onClose()
    },
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  return (
    <Modal
      open
      onClose={onClose}
      title="New alert rule"
      footer={
        <>
          <button className="btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button
            className="btn-primary"
            onClick={() => create.mutate()}
            disabled={!name || !indicatorId || value === ''}
          >
            Create rule
          </button>
        </>
      }
    >
      <Field label="Rule name">
        <input
          className="input"
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="Completion falling behind"
        />
      </Field>
      <Field label="Watch this indicator">
        <select
          className="input"
          value={indicatorId}
          onChange={(event) => setIndicatorId(event.target.value)}
        >
          <option value="">Choose an indicator…</option>
          {indicators.data?.map((indicator) => (
            <option key={indicator.id} value={indicator.id}>
              {indicator.name}
              {indicator.last_value !== null ? ` (now ${formatNumber(indicator.last_value)})` : ''}
            </option>
          ))}
        </select>
      </Field>
      <div className="grid grid-cols-2 gap-4">
        <Field label="Raise an alert when the value is">
          <select
            className="input"
            value={operator}
            onChange={(event) => setOperator(event.target.value)}
          >
            <option value="lt">below</option>
            <option value="lte">at or below</option>
            <option value="gt">above</option>
            <option value="gte">at or above</option>
            <option value="eq">exactly</option>
          </select>
        </Field>
        <Field label="Threshold">
          <input
            className="input"
            type="number"
            value={value}
            onChange={(event) => setValue(event.target.value)}
          />
        </Field>
        <Field label="Severity">
          <select
            className="input"
            value={severity}
            onChange={(event) => setSeverity(event.target.value as Severity)}
          >
            <option value="info">Info</option>
            <option value="warning">Warning</option>
            <option value="critical">Critical</option>
          </select>
        </Field>
        <Field label="Cooldown (minutes)" hint="Stops repeat alerts for the same problem">
          <input
            className="input"
            type="number"
            value={cooldown}
            onChange={(event) => setCooldown(event.target.value)}
          />
        </Field>
      </div>
      <label className="mb-3 flex items-center gap-2 text-sm">
        <input type="checkbox" checked={email} onChange={(e) => setEmail(e.target.checked)} />
        Also send an email (requires SMTP settings in your .env)
      </label>
      {email && (
        <Field
          label="Email recipients"
          hint="Comma separated. Leave blank to notify all managers and administrators."
        >
          <input
            className="input"
            value={recipients}
            onChange={(event) => setRecipients(event.target.value)}
          />
        </Field>
      )}
    </Modal>
  )
}
