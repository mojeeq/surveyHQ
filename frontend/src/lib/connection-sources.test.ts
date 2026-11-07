import { describe, expect, it } from 'vitest'
import { externalConnectionUrl, isLinkConnection } from './connection-sources'

describe('external connection links', () => {
  it('preserves SharePoint query paths and Kobo fragments', () => {
    for (const url of [
      'https://tenant.sharepoint.com/sites/a/Forms/AllItems.aspx?id=%2Ffolder&view=1',
      'https://kf.kobotoolbox.org/#/forms/abc/summary',
    ]) expect(externalConnectionUrl(url)).toBe(url)
  })

  it.each([
    'javascript:alert(1)', 'data:text/html,test', 'http://example.org',
    'https://user:password@example.org', 'not a URL', '//example.org',
  ])('does not make unsafe links clickable: %s', (url) => {
    expect(externalConnectionUrl(url)).toBeUndefined()
  })

  it('keeps automatic import controls limited to supported sources', () => {
    expect(isLinkConnection('survey_solutions')).toBe(false)
    expect(isLinkConnection('folder')).toBe(false)
    expect(isLinkConnection('sharepoint')).toBe(true)
    expect(isLinkConnection('google_sheets')).toBe(true)
  })
})
