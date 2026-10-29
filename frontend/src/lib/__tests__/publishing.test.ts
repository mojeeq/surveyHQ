/**
 * The small rules behind publishing a board to a website: what its address
 * is called by default, which addresses the server will take, and where the
 * page will be once it is there.
 */
import { describe, expect, it } from 'vitest'

import { pageUrl, pathProblem, suggestPath, whereTo } from '@/lib/publishing'

describe('the address a board is given by default', () => {
  it('is its name, as a folder', () => {
    expect(suggestPath('Fiji Census 2017')).toBe('fiji-census-2017')
  })

  it('carries its view after it', () => {
    expect(suggestPath('Fiji Census 2017', 'Northern only')).toBe('fiji-census-2017-northern-only')
  })

  it('keeps the letters of a name with accents, and drops what cannot go in a link', () => {
    expect(suggestPath('Enquête ménages: été 2026!')).toBe('enquete-menages-ete-2026')
  })

  it('is never empty', () => {
    expect(suggestPath('***')).toBe('dashboard')
  })

  it('is always an address the server accepts', () => {
    for (const name of ['Fiji Census 2017', 'Enquête ménages', '  ', 'a/b\\c']) {
      expect(pathProblem(suggestPath(name))).toBeNull()
    }
  })
})

describe('which addresses are refused', () => {
  it('takes folders within folders', () => {
    expect(pathProblem('census/2017')).toBeNull()
  })

  it('refuses climbing out of the folder', () => {
    expect(pathProblem('../outside')).toMatch(/'\.\.'/)
  })

  it('refuses spaces and letters a link mangles', () => {
    expect(pathProblem('with space')).toMatch(/letters, digits/)
    expect(pathProblem('ünïcode')).toMatch(/letters, digits/)
  })

  it('takes the front of the folder', () => {
    expect(pathProblem('')).toBeNull()
  })
})

describe('where a page will be', () => {
  it('is the folder and the address', () => {
    expect(pageUrl({ folder_url: 'https://office.github.io/dashboards/' }, 'census')).toBe(
      'https://office.github.io/dashboards/census/',
    )
  })

  it('is the folder itself for the front page', () => {
    expect(pageUrl({ folder_url: 'https://stats.example.org/boards' }, '')).toBe(
      'https://stats.example.org/boards/',
    )
  })

  it('is unknown where the folder’s address is', () => {
    expect(pageUrl({ folder_url: '' }, 'census')).toBe('')
  })
})

describe('where a destination puts pages, in a line', () => {
  it('names the repository and branch for GitHub', () => {
    expect(
      whereTo({ kind: 'github', settings: { owner: 'office', repo: 'boards', branch: 'gh-pages' } }),
    ).toBe('office/boards · gh-pages')
  })

  it('names the account, server and folder for SFTP, with an unusual port', () => {
    expect(
      whereTo({
        kind: 'sftp',
        settings: { username: 'web', host: 'stats.example.org', port: 2222, folder: '/var/www' },
      }),
    ).toBe('web@stats.example.org:2222:/var/www')
  })
})
