import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import type { Questionnaire } from '@/lib/types'
import { EmptyState, ErrorNote, Loading } from '@/components/ui'

/**
 * A questionnaire and every version of it the server holds.
 *
 * Survey Solutions lists each version as its own entry, so a questionnaire
 * revised twice arrives as three unrelated-looking rows. They are one survey.
 */
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

/**
 * What a selection says, in words.
 *
 * Three versions of one questionnaire is one survey, not three surveys, and
 * counting the entries made it read as though three separate datasets were
 * about to appear.
 */
export function describeSelection(selected: string[]): string {
  const questionnaires = new Set(selected.map((choice) => choice.split('$')[0]))
  const surveys = `${questionnaires.size} questionnaire${questionnaires.size === 1 ? '' : 's'}`
  const pinned = selected.filter((choice) => choice.includes('$'))
  if (!pinned.length) return surveys
  return pinned.length === selected.length && selected.length > questionnaires.size
    ? `${surveys} (${pinned.length} versions)`
    : surveys
}

/**
 * Choose which questionnaires - and which of their versions - to import.
 *
 * A choice is stored either as a bare questionnaire id, meaning every version
 * of it, or as the ``guid$version`` identity of one particular version. The
 * difference matters for anything that runs more than once: a questionnaire
 * revised again next month publishes a version a pinned list has never heard
 * of, and a scheduled import would go on pulling the versions it was set up
 * with while the fieldwork moved on without it.
 */
export default function QuestionnairePicker({
  connectionId,
  value,
  onChange,
}: {
  connectionId: string
  value: string[]
  onChange: (value: string[]) => void
}) {
  const questionnaires = useQuery({
    queryKey: ['questionnaires', connectionId],
    queryFn: () => api.get<Questionnaire[]>(`/connections/${connectionId}/questionnaires`),
  })
  const grouped = useMemo(() => groupQuestionnaires(questionnaires.data), [questionnaires.data])

  if (questionnaires.isLoading)
    return <Loading label="Fetching questionnaires from the server" />
  if (questionnaires.error)
    return <ErrorNote error={questionnaires.error} retry={questionnaires.refetch} />
  if (!questionnaires.data?.length)
    return (
      <EmptyState
        icon="◌"
        title="No questionnaires visible"
        description="The API user may not have access to any questionnaires in this workspace."
      />
    )

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
                  // Part-selected reads as neither on nor off, which is what
                  // it is: some versions of this questionnaire.
                  if (el) el.indeterminate = !everyVersion && pinned.length > 0
                }}
                // Ticking a questionnaire takes all of its versions, which is
                // nearly always what is wanted: the interviews are spread
                // across them and they are one survey.
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
                    // Falling back to the newest rather than to nothing: an
                    // empty choice would clear the questionnaire, and the
                    // reader has just said they want it.
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
