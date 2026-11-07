/**
 * The Storage card on Administration -> Background jobs.
 *
 * It reports what the storage check found before anything is removed, so the
 * words matter: "could be removed" is not "removed", newer unused files are
 * said to be left alone, and nothing claims to run automatically when it doesn't.
 */
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { StorageBody, type StorageReport } from '@/components/admin/StorageCard'

const MB = 1024 * 1024

const checked: StorageReport = {
  checked_at: new Date().toISOString(),
  deleted: false,
  keep_versions: 10,
  grace_hours: 24,
  removable_files: 6,
  removable_bytes: 300 * MB,
  removed_files: 0,
  removed_bytes: 0,
  pruned_versions: 3,
  recent_unused_files: 1,
  recent_unused_bytes: 40 * MB,
  skipped_changed: [],
  by_reason: {
    'restore point past the limit': { files: 6, bytes: 300 * MB },
  },
  usage: {
    datasets_bytes: 2048 * MB,
    current_bytes: 1024 * MB,
    restore_point_bytes: 700 * MB,
    other_bytes: 324 * MB,
  },
  disk: { total_bytes: 100 * 1024 * MB, free_bytes: 60 * 1024 * MB, free_percent: 60, low: false },
  cleanup_enabled: false,
}

const html = (report: StorageReport) => renderToStaticMarkup(<StorageBody report={report} />)

describe('the Storage card', () => {
  it('reports what a check found without claiming it was removed', () => {
    const page = html(checked)
    expect(page).toContain('Could be removed')
    expect(page).toContain('300.0 MB')
    expect(page).toContain('6 file(s), 300.0 MB: restore point past the limit')
    expect(page).toContain('Up to 10 kept per dataset')
    expect(page).not.toContain('Removed')
  })

  it('says newer unused files are left alone, and why', () => {
    expect(html(checked)).toContain(
      'are left alone until they are 24 hours old, in case an import is\n          still writing them'.replace(/\n\s+/, ' '),
    )
  })

  it('says nothing is removed automatically until that is turned on', () => {
    expect(html(checked)).toContain('Nothing is removed automatically.')
    expect(html({ ...checked, cleanup_enabled: true })).toContain(
      'Unused files are removed every night.',
    )
  })

  it('reports a clean-up that ran as removed', () => {
    const page = html({ ...checked, deleted: true, removed_files: 6, removed_bytes: 300 * MB })
    expect(page).toContain('Removed')
    expect(page).toContain('Cleaned up')
  })

  it('warns when the disk is nearly full', () => {
    const page = html({ ...checked, disk: { ...checked.disk, free_percent: 4, low: true } })
    expect(page).toContain('The disk is nearly full: 4% free.')
  })

  it('says when every version is kept', () => {
    expect(html({ ...checked, keep_versions: 0 })).toContain('Every version is kept')
  })
})
