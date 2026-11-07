// Disk use by datasets, and what the storage check would remove: the Storage
// card on Administration -> Background jobs. Removal is the administrator's
// call, made after reading what a check found.

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { formatBytes, relativeTime } from '@/lib/format'
import { Card, Loading } from '@/components/ui'
import { PanelError } from '@/components/overview/OverviewPanels'
import { useDialog } from '@/hooks/useDialog'
import { useToast } from '@/hooks/useToast'

export interface StorageReport {
  checked_at: string
  deleted: boolean
  keep_versions: number
  grace_hours: number
  removable_files: number
  removable_bytes: number
  removed_files: number
  removed_bytes: number
  pruned_versions: number
  recent_unused_files: number
  recent_unused_bytes: number
  skipped_changed: string[]
  by_reason: Record<string, { files: number; bytes: number }>
  usage: {
    datasets_bytes: number
    current_bytes: number
    restore_point_bytes: number
    other_bytes: number
  }
  disk: { total_bytes?: number; free_bytes?: number; free_percent?: number; low?: boolean }
  cleanup_enabled: boolean
}

function Figure({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-md border border-ink-200 px-3 py-2 dark:border-dark-200">
      <div className="text-xs font-medium uppercase tracking-wide text-ink-500">{label}</div>
      <div className="mt-1 text-sm font-semibold text-ink-800 dark:text-dark-800">{value}</div>
      {hint && <div className="text-xs text-ink-500">{hint}</div>}
    </div>
  )
}

export function StorageBody({ report }: { report: StorageReport }) {
  const disk = report.disk
  const reasons = Object.entries(report.by_reason ?? {})
  return (
    <>
      {disk.low && (
        <p role="alert" className="mb-3 text-sm font-medium text-red-800 dark:text-red-300">
          ⚠ The disk is nearly full: {disk.free_percent}% free.
        </p>
      )}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Figure
          label="Disk free"
          value={disk.free_bytes !== undefined ? formatBytes(disk.free_bytes) : 'Unknown'}
          hint={
            disk.total_bytes ? `${disk.free_percent}% of ${formatBytes(disk.total_bytes)}` : undefined
          }
        />
        <Figure label="Datasets in use" value={formatBytes(report.usage.current_bytes)} />
        <Figure
          label="Restore points"
          value={formatBytes(report.usage.restore_point_bytes)}
          hint={
            report.keep_versions
              ? `Up to ${report.keep_versions} kept per dataset`
              : 'Every version is kept'
          }
        />
        <Figure
          label={report.deleted ? 'Removed' : 'Could be removed'}
          value={
            report.deleted
              ? formatBytes(report.removed_bytes)
              : formatBytes(report.removable_bytes)
          }
          hint={`${report.deleted ? report.removed_files : report.removable_files} file(s)`}
        />
      </div>

      {reasons.length > 0 && (
        <ul className="mt-3 space-y-1 text-sm text-ink-700 dark:text-dark-700">
          {reasons.map(([reason, count]) => (
            <li key={reason}>
              {count.files} file(s), {formatBytes(count.bytes)}: {reason}
            </li>
          ))}
        </ul>
      )}
      {report.recent_unused_files > 0 && (
        <p className="mt-2 text-xs text-ink-500">
          {report.recent_unused_files} newer unused file(s) ({formatBytes(report.recent_unused_bytes)})
          are left alone until they are {report.grace_hours} hours old, in case an import is
          still writing them.
        </p>
      )}
      {report.skipped_changed.length > 0 && (
        <p className="mt-2 text-xs text-ink-500">
          {report.skipped_changed.length} dataset(s) changed during the clean-up and were skipped.
          They are checked again next time.
        </p>
      )}
      <p className="mt-2 text-xs text-ink-500">
        {report.deleted ? 'Cleaned up' : 'Checked'} {relativeTime(report.checked_at)}.{' '}
        {report.cleanup_enabled ? (
          'Unused files are removed every night.'
        ) : (
          <>
            Nothing is removed automatically. Turn on <strong>Remove unused files every night</strong>{' '}
            in the Settings tab once this report looks right.
          </>
        )}
      </p>
    </>
  )
}

export default function StorageCard() {
  const queryClient = useQueryClient()
  const ask = useDialog()
  const toast = useToast()
  const report = useQuery({
    queryKey: ['storage-report'],
    queryFn: () => api.get<StorageReport>('/system/storage'),
  })
  const check = useMutation({
    mutationFn: () => api.post<StorageReport>('/system/storage/check'),
    onSuccess: (data) => queryClient.setQueryData(['storage-report'], data),
    onError: (error: Error) => toast.push(error.message, 'error'),
  })
  const clean = useMutation({
    mutationFn: () => api.post<StorageReport>('/system/storage/cleanup'),
    onSuccess: (data) => {
      queryClient.setQueryData(['storage-report'], data)
      toast.push(`Removed ${data.removed_files} file(s), ${formatBytes(data.removed_bytes)}.`, 'success')
    },
    onError: (error: Error) => toast.push(error.message, 'error'),
  })
  const busy = check.isPending || clean.isPending
  const data = report.data

  return (
    <Card
      title="Storage"
      subtitle="Dataset files, restore points and what is no longer needed"
      actions={
        <div className="flex gap-2">
          <button
            type="button"
            className="btn-secondary btn-sm"
            disabled={busy}
            onClick={() => check.mutate()}
          >
            {check.isPending ? 'Checking…' : 'Check now'}
          </button>
          <button
            type="button"
            className="btn-secondary btn-sm"
            disabled={busy || !data || data.deleted || data.removable_files === 0}
            onClick={async () => {
              if (!data) return
              const sure = await ask.confirm({
                title: `Remove ${data.removable_files} unused file(s)?`,
                message: `This frees ${formatBytes(data.removable_bytes)}. Files are checked again just before removal, and anything that has become needed is kept. Removed files can only be recovered from a backup.`,
                confirmLabel: 'Remove files',
                tone: 'danger',
              })
              if (sure) clean.mutate()
            }}
          >
            {clean.isPending ? 'Removing…' : 'Remove unused files'}
          </button>
        </div>
      }
    >
      {data ? (
        <StorageBody report={data} />
      ) : report.error ? (
        <PanelError
          title="Couldn't load the storage report."
          error={report.error}
          retry={() => void report.refetch()}
        />
      ) : (
        <Loading />
      )}
    </Card>
  )
}
