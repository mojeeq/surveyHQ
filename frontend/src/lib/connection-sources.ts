import type { Connection } from './types'

export const CONNECTION_SOURCES: Record<Connection['source_kind'], {
  label: string
  placeholder: string
  hint: string
}> = {
  survey_solutions: {
    label: 'Survey Solutions',
    placeholder: 'https://your-server.mysurvey.solutions',
    hint: 'The headquarters server root.',
  },
  folder: {
    label: 'Folder on this server', placeholder: '', hint: '',
  },
  odk_central: {
    label: 'ODK Central',
    placeholder: 'https://central.example.org',
    hint: 'Paste your Central server, project or form link.',
  },
  surveycto: {
    label: 'SurveyCTO',
    placeholder: 'https://your-server.surveycto.com',
    hint: 'Paste your SurveyCTO server or form link.',
  },
  cspro_csweb: {
    label: 'CSPro / CSWeb',
    placeholder: 'https://your-server.example.org/csweb',
    hint: 'Paste the web address of your CSWeb server.',
  },
  google_sheets: {
    label: 'Google Sheets',
    placeholder: 'https://docs.google.com/spreadsheets/d/...',
    hint: 'Paste the spreadsheet link. Use restricted sharing for private data.',
  },
  kobotoolbox: {
    label: 'KoboToolbox',
    placeholder: 'https://kf.kobotoolbox.org/#/forms/...',
    hint: 'Paste your KoboToolbox project or server link.',
  },
  sharepoint: {
    label: 'SharePoint',
    placeholder: 'https://your-org.sharepoint.com/sites/...',
    hint: 'Paste a SharePoint folder or document-library link. Prefer a link for people with existing access.',
  },
}

export function isLinkConnection(kind: Connection['source_kind']): boolean {
  return kind !== 'survey_solutions' && kind !== 'folder'
}

/** Defence in depth for links read from older databases. */
export function externalConnectionUrl(value: string): string | undefined {
  try {
    const url = new URL(value)
    if (url.protocol === 'https:' && !url.username && !url.password) return url.href
  } catch { /* No clickable link for invalid URLs. */ }
  return undefined
}
