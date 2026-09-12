import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import type { Questionnaire } from '@/lib/types'
import { EmptyState, ErrorNote, Loading } from '@/components/ui'

export interface QuestionnaireGroup {
  id: string
  title: string
  variable: string
  versions: Questionnaire[]
}

export function groupQuestionnaires(list: Questionnaire[] | undefined): QuestionnaireGroup[] {
  const byQuestionnaire = new Map<string, QuestionnaireGroup>()
  for (const questionnaire of list ?? []) {
    const existing = byQuestionnaire.get(questionnaire.id)
    if (existing) existing.versions.push(questionnaire)
    else
      byQuestionnaire.set(questionnaire.id, {
        id: questionnaire.id,
        title: questionnaire.title,
        variable: questionnaire.variable,
        versions: [questionnaire],
      })
  }
  const groups = [...byQuestionnaire.values()]
  for (const group of groups) group.versions.sort((a, b) => a.version - b.version)
  return groups.sort((a, b) => a.title.localeCompare(b.title))
}

export function describeSelection(selected: string[]): string {
  const questionnaires = new Set(selected.map((choice) => choice.split('$')[0]))
  const surveys = `${questionnaires.size} questionnaire${questionnaires.size === 1 ? '' : 's'}`
  const pinned = selected.filter((choice) => choice.includes('$'))
  if (!pinned.length) return surveys
  return pinned.length === selected.length && selected.length > questionnaires.size
    ? `${surveys} (${pinned.length} versions)`
    : surveys
}

type SourceResource = Questionnaire & { kind?: string }

/**
 * Pick importable resources from any connection.
 *
 * Survey Solutions gets its richer questionnaire/version treatment. Other
 * sources expose a flat list of forms, CSPro dictionaries or configured SDMX
 * data queries and therefore only need one checkbox per resource.
 */
export default function QuestionnairePicker({
  connectionId,
  value,
  onChange,
  provider = 'survey_solutions',
}: {
  connectionId: string
  value: string[]
  onChange: (value: string[]) => void
  provider?: string
}) {
  const resources = useQuery({
    queryKey: ['source-resources', connectionId],
    queryFn: () =>
      api.get<SourceResource[]>(`/connections/${connectionId}/resources`),
  })
  const grouped = useMemo(
    () => groupQuestionnaires(resources.data),
    [resources.data],
  )

  if (resources.isLoading)
    return <Loading label="Fetching available data from the source" />
  if (resources.error)
    return <ErrorNote error={resources.error} retry={resources.refetch} />
  if (!resources.data?.length)
    return (
      <EmptyState
        icon="◌"
        title="No importable resources"
        description={
          provider === 'sdmx'
            ? 'Add one or more SDMX data query paths to this connection first.'
            : 'The account may not have access to any forms or data resources on this source.'
        }
      />
    )

  if (provider !== 'survey_solutions') {
    return (
      <div className="max-h-80 space-y-2 overflow-y-auto">
        {resources.data.map((resource) => {
          const checked = value.includes(resource.identity)
          return (
            <label
              key={resource.identity}
              className="flex cursor-pointer items-center gap-3 rounded-card border border-ink-200 px-3 py-2.5 hover:bg-ink-50"
            >
              <input
                type="checkbox"
                checked={checked}
                onChange={(event) =>
                  onChange(
                    event.target.checked
                      ? [...value, resource.identity]
                      : value.filter((item) => item !== resource.identity),
                  )
                }
              />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-ink-800">
                  {resource.title}
                </p>
                <p className="truncate text-xs text-ink-500">
                  {resource.kind || 'resource'} · {resource.id}
                </p>
              </div>
            </label>
          )
        })}
      </div>
    )
  }

  /** Replace one questionnaire's entries, leaving every other one alone. */
  const put = (group: QuestionnaireGroup, choices: string[]) => {
    const mine = new Set([group.id, ...group.versions.map((v) => v.identity)])
    onChange([...value.filter((choice) => !mine.has(choice)), ...choices])
  }

  return (
    <div className="max-h-80 space-y-2 overflow-y-auto">
      {grouped.map((group) => {
        const everyVersion = value.includes(group.id)
        const pinned = group.versions.filter((v) => value.includes(v.identity))
        const included = everyVersion || pinned.length > 0
        const latest = group.versions[group.versions.length - 1]
        return (
          <div key={group.id} className="rounded-card border border-ink-200">
            <label className="flex cursor-pointer items-center gap-3 px-3 py-2.5 hover:bg-ink-50">
              <input
                type="checkbox"
                checked={included}
                ref={(el) => {
                  if (el) el.indeterminate = !everyVersion && pinned.length > 0
                }}
                onChange={(event) => put(group, event.target.checked ? [group.id] : [])}
              />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-ink-800">{group.title}</p>
                <p className="text-xs text-ink-500">
                  {group.versions.length === 1
                    ? `Version ${group.versions[0].version}`
                    : `${group.versions.length} versions · v${group.versions[0].version}-v${latest.version}`}
                  {group.variable && ` · ${group.variable}`}
                </p>
              </div>
            </label>

            {included && group.versions.length > 1 && (
              <div className="space-y-1.5 border-t border-ink-100 px-3 py-2">
                <p className="text-xs text-ink-500">
                  A questionnaire revised during fieldwork has its interviews spread across
                  its versions. They are imported oldest first into <strong>one</strong>{' '}
                  dataset, with a <code>questionnaire_version</code> column saying which
                  version each row came from.
                </p>
                <label className="flex cursor-pointer items-center gap-2 text-xs text-ink-700">
                  <input
                    type="radio"
                    name={`versions-${group.id}`}
                    checked={everyVersion}
                    onChange={() => put(group, [group.id])}
                  />
                  Every version, including any published later
                </label>
                <label className="flex cursor-pointer items-center gap-2 text-xs text-ink-700">
                  <input
                    type="radio"
                    name={`versions-${group.id}`}
                    checked={!everyVersion}
                    onChange={() => put(group, [latest.identity])}
                  />
                  Only the versions ticked below
                </label>
                {!everyVersion && (
                  <div className="flex flex-wrap gap-x-4 gap-y-1 pl-5">
                    {group.versions.map((version) => (
                      <label
                        key={version.identity}
                        className="flex cursor-pointer items-center gap-1.5 text-xs text-ink-700"
                      >
                        <input
                          type="checkbox"
                          checked={value.includes(version.identity)}
                          onChange={(event) =>
                            put(
                              group,
                              event.target.checked
                                ? [...pinned.map((v) => v.identity), version.identity]
                                : pinned
                                    .filter((v) => v.identity !== version.identity)
                                    .map((v) => v.identity),
                            )
                          }
                        />
                        v{version.version}
                      </label>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
