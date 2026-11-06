import { describe, expect, it } from 'vitest'

import { asField, changesIn, provenance, type PlatformSetting } from '@/components/admin/Settings'

const upload: PlatformSetting = {
  name: 'max_upload_mb',
  group: 'Files and uploads',
  label: 'Largest upload',
  about: '',
  warning: '',
  kind: 'int',
  unit: 'MB',
  minimum: 1,
  maximum: 1000000,
  value: 20480,
  default: 20480,
  overridden: false,
}

const cache: PlatformSetting = {
  ...upload,
  name: 'analytics_cache_enabled',
  kind: 'bool',
  unit: '',
  value: true,
  default: true,
}

const password: PlatformSetting = {
  ...upload,
  name: 'smtp_password',
  kind: 'secret',
  unit: '',
  value: false,
  default: false,
}

describe('what the settings page sends back', () => {
  it('sends nothing when nothing was touched', () => {
    const edited = { max_upload_mb: '20480', analytics_cache_enabled: 'true' }
    expect(changesIn([upload, cache], edited)).toEqual({})
  })

  it('sends a number as a number and a switch as a boolean', () => {
    const edited = { max_upload_mb: '512', analytics_cache_enabled: 'false' }
    expect(changesIn([upload, cache], edited)).toEqual({
      max_upload_mb: 512,
      analytics_cache_enabled: false,
    })
  })

  it('leaves a password alone when the box is empty', () => {
    // The server never sends one back, so empty means "keep it" rather than
    // "clear it" - a page that cleared the mail password on every save would
    // be a page nobody could use twice.
    expect(changesIn([password], { smtp_password: '' })).toEqual({})
    expect(changesIn([password], { smtp_password: 'new one' })).toEqual({
      smtp_password: 'new one',
    })
  })

  it('reads a value out of a setting the way the form holds it', () => {
    expect(asField(upload)).toBe('20480')
    expect(asField(cache)).toBe('true')
    expect(asField({ ...cache, value: false })).toBe('false')
    // Never the secret itself, which the page does not have.
    expect(asField({ ...password, value: true })).toBe('')
  })
})

describe('where a value came from', () => {
  it('names .env while nobody has moved it', () => {
    expect(provenance(upload)).toBe('From .env: 20480 MB')
    expect(provenance(cache)).toBe('From .env: on')
  })

  it('says what putting it back would give you', () => {
    expect(provenance({ ...upload, value: 512, overridden: true })).toBe(
      'Set here. Without it: 20480 MB',
    )
    expect(provenance({ ...cache, value: false, overridden: true })).toBe(
      'Set here. Without it: on',
    )
  })

  it('says only whether a password is set', () => {
    expect(provenance(password)).toBe('Not set')
    expect(provenance({ ...password, value: true, overridden: true })).toBe('Set here')
  })
})
