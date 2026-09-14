/**
 * The project's R workspace.
 *
 * R belongs to the project rather than to one dataset: a script that prepares
 * survey data reads the household file and writes the person file, and pinning
 * it to either was always a fiction. Every dataset in the project is readable
 * here, whatever the script writes becomes a dataset here, and the working
 * directory survives between runs - so a saved object, a lookup table or a
 * package installed into the project's own library is still there next time.
 */

import { useState, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { waitForJob } from '@/lib/jobs'
import type { Job } from '@/lib/types'
import { relativeTime } from '@/lib/format'
import { useToast } from '@/hooks/useToast'
import CodeEditor, { CodeSnippet } from '@/components/CodeEditor'
import { Card, Field, Loading, Modal } from '@/components/ui'

interface ProjectScript {
  id: string
  project_id: string
  name: string
  description: string
  code: string
  run_on_import: boolean
  display_order: number
  last_run_at: string | null
  last_ok: boolean
  last_output: string
  created_at: string
  updated_at: string
}

/** One object a run left in R's global environment. */
interface REnvironmentObject {
  name: string
  kind: 'data' | 'value' | 'function'
  type: string
  shape: string
  preview: string
  bytes: number
}

interface RunResult {
  message: string
  output: string
  written: { name: string; id: string; rows: number }[]
  files: string[]
  environment: REnvironmentObject[]
}

/**
 * The working directory as it stands: the datasets the platform puts there for
 * a script to read, the files anyone left, and what the last run had in memory.
 */
interface Workspace {
  files: { path: string; bytes: number; dataset: boolean }[]
  datasets: { name: string; slug: string; rows: number; path: string }[]
  environment: REnvironmentObject[]
}

interface Tools {
  r: { enabled: boolean; reason: string }
  datasets: { name: string; slug: string; rows: number }[]
}

/** Lines worth having one click away when the console is empty. */
const EXAMPLES = [
  'h <- read_dataset("household")',
  'str(h)',
  'h$adult <- ifelse(h$age >= 18, 1, 0)',
  'both <- merge(read_dataset("household"), read_dataset("person"), by = "interview__key")',
  'write_dataset(h, "Household prepared")',
  'write.csv(h, "household-prepared.csv", row.names = FALSE)',
  'saveRDS(h, "household.rds")',
  'install.packages("dplyr", repos = "https://cloud.r-project.org")',
]

export default function ProjectRWorkspace({
  projectId,
  canManage,
}: {
  projectId: string
  canManage: boolean
}) {
  const toast = useToast()
  const queryClient = useQueryClient()
  const [code, setCode] = useState('')
  const [result, setResult] = useState<RunResult | null>(null)
  const [failure, setFailure] = useState('')
  const [saving, setSaving] = useState<ProjectScript | 'new' | null>(null)

  const tools = useQuery({
    queryKey: ['project-tools', projectId],
    queryFn: () => api.get<Tools>(`/projects/${projectId}/tools`),
  })

  const scripts = useQuery({
    queryKey: ['project-scripts', projectId],
    queryFn: () => api.get<ProjectScript[]>(`/projects/${projectId}/scripts`),
  })

  // The environment comes from here rather than from the last run's reply, so
  // that it is still drawn after a reload. A run invalidates this query, which
  // is what refreshes the pane.
  const workspace = useQuery({
    queryKey: ['project-workspace', projectId],
    queryFn: () => api.get<Workspace>(`/projects/${projectId}/workspace`),
    enabled: canManage,
  })

  const settled = (outcome: RunResult) => {
    setResult(outcome)
    setFailure('')
    // A script can create or replace a dataset, so everything that lists them
    // is now out of date - including the workspace listing it wrote into.
    queryClient.invalidateQueries({ queryKey: ['datasets'] })
    queryClient.invalidateQueries({ queryKey: ['project', projectId] })
    queryClient.invalidateQueries({ queryKey: ['project-workspace', projectId] })
    queryClient.invalidateQueries({ queryKey: ['project-scripts', projectId] })
  }

  const runConsole = useMutation({
    mutationFn: async () => waitForJob<RunResult>(await api.post<Job>(`/projects/${projectId}/queue-run`, { code })),
    onSuccess: settled,
    onError: (error: Error) => {
      setResult(null)
      setFailure(error.message)
    },
  })

  const runSaved = useMutation({
    mutationFn: async (script: ProjectScript) =>
      waitForJob<RunResult>(await api.post<Job>(`/projects/${projectId}/queue-run`, { code: script.code, script_id: script.id })),
    onSuccess: settled,
    onError: (error: Error) => {
      setResult(null)
      setFailure(error.message)
      queryClient.invalidateQueries({ queryKey: ['project-scripts', projectId] })
    },
  })

  const remove = useMutation({
    mutationFn: (script: ProjectScript) =>
      api.delete(`/projects/${projectId}/scripts/${script.id}`),
    onSuccess: () => {
      toast.push('Script deleted', 'info')
      queryClient.invalidateQueries({ queryKey: ['project-scripts', projectId] })
    },
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  const setOnImport = useMutation({
    mutationFn: ({ script, on }: { script: ProjectScript; on: boolean }) =>
      api.patch(`/projects/${projectId}/scripts/${script.id}`, { run_on_import: on }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['project-scripts', projectId] }),
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  const clearWorkspace = useMutation({
    mutationFn: () => api.delete(`/projects/${projectId}/workspace`),
    onSuccess: () => {
      toast.push('Workspace emptied. The datasets are untouched.', 'info')
      queryClient.invalidateQueries({ queryKey: ['project-workspace', projectId] })
    },
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  if (tools.isLoading) return <Loading />

  if (!tools.data?.r.enabled) {
    return (
      <Card title="R is not available here" className="mt-4">
        <p className="text-sm text-ink-600">{tools.data?.r.reason}</p>
      </Card>
    )
  }

  if (!canManage) {
    return (
      <Card title="R runs with the server's own permissions" className="mt-4">
        <p className="text-sm text-ink-600">
          Running R here needs the manager role on this project. An R script is a
          program, not a query: it can do anything the server can.
        </p>
      </Card>
    )
  }

  return (
    <div className="mt-4 grid gap-4 lg:grid-cols-3">
      <div className="space-y-4 lg:col-span-2">
        <Card
          title="Console"
          subtitle="Runs in this project's workspace, against every dataset in it"
          actions={
            <div className="flex gap-2">
              <button
                className="btn-secondary btn-sm"
                disabled={!code.trim()}
                onClick={() => setSaving('new')}
              >
                Save as a script
              </button>
              <button
                className="btn-primary btn-sm"
                title="Ctrl or Cmd with Enter"
                disabled={!code.trim() || runConsole.isPending}
                onClick={() => runConsole.mutate()}
              >
                {runConsole.isPending ? 'Queued / running…' : 'Run'}
              </button>
            </div>
          }
        >
          <CodeEditor
            ariaLabel="R console"
            value={code}
            onChange={setCode}
            placeholder={
              'h <- read_dataset("household")\nh$adult <- h$age >= 18\nwrite_dataset(h, "Household prepared")'
            }
            onSubmit={() => {
              if (code.trim() && !runConsole.isPending) runConsole.mutate()
            }}
          />
        </Card>

        {failure && (
          <Card title="It did not run">
            <pre className="whitespace-pre-wrap font-mono text-xs text-danger-700">
              {failure}
            </pre>
          </Card>
        )}

        {result && (
          <Card title="Result" subtitle={result.message}>
            {result.written.length > 0 && (
              <ul className="mb-3 space-y-1 text-sm text-ink-700">
                {result.written.map((item) => (
                  <li key={item.id}>
                    Saved <strong>{item.name}</strong> ({item.rows.toLocaleString()} rows)
                  </li>
                ))}
              </ul>
            )}
            {result.output ? (
              <pre className="max-h-72 overflow-auto whitespace-pre-wrap rounded bg-ink-50 p-2 font-mono text-xs text-ink-700">
                {result.output}
              </pre>
            ) : (
              <p className="text-sm text-ink-400">It printed nothing.</p>
            )}
          </Card>
        )}
      </div>

      <div className="space-y-4">
        <REnvironment objects={workspace.data?.environment ?? []} />

        <Card
          title="Saved scripts"
          subtitle="Run in this order after a new export lands"
        >
          {scripts.isLoading ? (
            <Loading />
          ) : !scripts.data?.length ? (
            <p className="text-sm text-ink-400">
              Nothing saved yet. Write something in the console and save it.
            </p>
          ) : (
            <ul className="space-y-3">
              {scripts.data.map((script) => (
                <li key={script.id} className="border-b border-ink-100 pb-3 last:border-0">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium text-ink-800">
                        {script.name}
                      </p>
                      {script.description && (
                        <p className="truncate text-xs text-ink-500">{script.description}</p>
                      )}
                      {script.last_run_at && (
                        <p
                          className={`text-xs ${
                            script.last_ok ? 'text-ink-400' : 'text-danger-600'
                          }`}
                          title={script.last_output}
                        >
                          {script.last_ok ? 'Ran' : 'Failed'}{' '}
                          {relativeTime(script.last_run_at)}
                        </p>
                      )}
                    </div>
                    <button
                      className="btn-secondary btn-sm shrink-0"
                      disabled={runSaved.isPending}
                      onClick={() => runSaved.mutate(script)}
                    >
                      Run
                    </button>
                  </div>
                  <div className="mt-1.5 flex flex-wrap items-center gap-3 text-xs">
                    <label className="flex items-center gap-1.5 text-ink-600">
                      <input
                        type="checkbox"
                        checked={script.run_on_import}
                        onChange={(event) =>
                          setOnImport.mutate({ script, on: event.target.checked })
                        }
                      />
                      After each import
                    </label>
                    <button
                      className="text-brand-700 hover:underline"
                      onClick={() => setCode(script.code)}
                    >
                      Open in the console
                    </button>
                    <button
                      className="text-ink-500 hover:underline"
                      onClick={() => setSaving(script)}
                    >
                      Edit
                    </button>
                    <button
                      className="text-danger-600 hover:underline"
                      onClick={() => {
                        if (confirm(`Delete "${script.name}"? What it wrote stays.`))
                          remove.mutate(script)
                      }}
                    >
                      Delete
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card title="What you can read" subtitle="read_dataset() takes either name">
          {!tools.data.datasets.length ? (
            <p className="text-sm text-ink-400">
              This project has no datasets yet, so there is nothing to read.
            </p>
          ) : (
            <ul className="space-y-1 text-xs text-ink-600">
              {tools.data.datasets.map((dataset) => (
                <li key={dataset.slug}>
                  <button
                    className="text-left hover:text-brand-700 hover:underline"
                    title="Add a line that reads this one"
                    onClick={() =>
                      setCode((current) =>
                        `${current ? `${current}\n` : ''}` +
                        `d <- read_dataset("${dataset.name}")`,
                      )
                    }
                  >
                    <span className="font-mono">{dataset.name}</span>
                    <span className="ml-1.5 text-ink-400">
                      {dataset.rows.toLocaleString()} rows
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          <p className="mt-2 text-xs text-ink-500">
            <code>write_dataset(df, "Name")</code> saves a data frame back as a dataset
            of this project, replacing one of that name if it is already here. So does
            writing a file: <code>write.csv(df, "adults.csv")</code> or{' '}
            <code>haven::write_dta(df, "adults.dta")</code> becomes a dataset called
            adults.
          </p>
        </Card>

        <Card title="A few lines to start from">
          <ul className="space-y-1 font-mono text-xs text-ink-600">
            {EXAMPLES.map((example) => (
              <li key={example}>
                <button
                  className="text-left hover:text-brand-700 hover:underline"
                  title="Add this line to the console"
                  onClick={() =>
                    setCode((current) => (current ? `${current}\n${example}` : example))
                  }
                >
                  <CodeSnippet source={example} />
                </button>
              </li>
            ))}
          </ul>
        </Card>

        <Card
          title="Working directory"
          subtitle="Kept between runs, so a saved object is there next time"
          actions={
            Boolean(workspace.data?.files.length) && (
              <button
                className="btn-ghost btn-sm text-danger-600"
                onClick={() => {
                  if (
                    confirm(
                      'Empty the working directory? Saved objects and installed packages go with it. The datasets are untouched.',
                    )
                  )
                    clearWorkspace.mutate()
                }}
              >
                Empty
              </button>
            )
          }
        >
          {Boolean(workspace.data?.datasets.length) && (
            <div className="mb-3">
              <Heading>Datasets</Heading>
              <ul className="mt-1 space-y-1 font-mono text-xs text-ink-600">
                {workspace.data?.datasets.map((dataset) => (
                  <li key={dataset.slug} className="flex justify-between gap-2">
                    <span className="truncate" title={dataset.name}>
                      {dataset.path}
                    </span>
                    <span className="shrink-0 text-ink-400">
                      {dataset.rows.toLocaleString()} rows
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {Boolean(workspace.data?.datasets.length) && <Heading>Files</Heading>}
          {!workspace.data?.files.length ? (
            <p className="mt-1 text-sm text-ink-400">Nothing else here yet.</p>
          ) : (
            <ul className="mt-1 space-y-1 font-mono text-xs text-ink-600">
              {workspace.data.files.map((file) => (
                <li key={file.path} className="flex justify-between gap-2">
                  <span className="truncate">
                    {file.path}
                    {file.dataset && (
                      <span
                        className="ml-1.5 font-sans text-[10px] uppercase tracking-wide text-brand-700"
                        title="This file is a dataset of the project"
                      >
                        dataset
                      </span>
                    )}
                  </span>
                  <span className="shrink-0 text-ink-400">
                    {Math.max(1, Math.round(file.bytes / 1024)).toLocaleString()} KB
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      {saving && (
        <SaveScriptModal
          projectId={projectId}
          script={saving === 'new' ? null : saving}
          code={saving === 'new' ? code : saving.code}
          onClose={() => setSaving(null)}
        />
      )}
    </div>
  )
}

/** A small section label inside a card. */
function Heading({ children }: { children: ReactNode }) {
  return (
    <p className="text-[11px] font-semibold uppercase tracking-wide text-ink-400">
      {children}
    </p>
  )
}

/**
 * What the last run left in R's global environment.
 *
 * Grouped the way RStudio groups it, because that is where the expectation
 * comes from: the data frames first, then the loose values, then the functions
 * with their signatures.
 *
 * Nothing here is clickable. Every run is a fresh R session - the working
 * DIRECTORY survives, the session does not - so an object listed here is a
 * record of what the last run made, not something the next line of code can
 * reach. Offering to paste `str(h)` into the console would be offering a line
 * that errors, so the pane says plainly what to do instead.
 */
function REnvironment({ objects }: { objects: REnvironmentObject[] }) {
  const groups: [string, REnvironmentObject[]][] = [
    ['Data', objects.filter((object) => object.kind === 'data')],
    ['Values', objects.filter((object) => object.kind === 'value')],
    ['Functions', objects.filter((object) => object.kind === 'function')],
  ]

  return (
    <Card title="Environment" subtitle="What the last run left behind">
      {!objects.length ? (
        <p className="text-sm text-ink-400">
          Nothing yet. Run something, and the objects it makes are listed here.
        </p>
      ) : (
        <div className="space-y-3">
          {groups.map(([label, members]) =>
            members.length === 0 ? null : (
              <div key={label}>
                <Heading>{label}</Heading>
                <ul className="mt-1 space-y-1">
                  {members.map((object) => {
                    const { shape, detail } = summarise(object)
                    return (
                      <li
                        key={object.name}
                        className="flex items-baseline gap-2 text-xs"
                        title={describe(object)}
                      >
                        <span className="shrink-0 font-mono font-medium text-ink-800">
                          {object.name}
                        </span>
                        <span
                          className={`truncate ${
                            object.kind === 'function' ? 'font-mono' : ''
                          }`}
                        >
                          {shape && <span className="text-ink-400">{shape}</span>}
                          {detail && (
                            <span className={`text-ink-500 ${shape ? 'ml-2' : ''}`}>
                              {detail}
                            </span>
                          )}
                        </span>
                      </li>
                    )
                  })}
                </ul>
              </div>
            ),
          )}
        </div>
      )}
      <p className="mt-3 text-xs text-ink-500">
        Every run starts a new R session, so these are gone by the next one. Keep one
        with <code>write_dataset(df, "Name")</code>, by writing it to a file, or with{' '}
        <code>saveRDS()</code>.
      </p>
    </Card>
  )
}

/**
 * The one line shown beside an object's name, RStudio's way round: a frame is
 * its size, a function is its signature, and a value is its value - "length 1"
 * about a number tells nobody anything they wanted to know.
 */
function summarise(object: REnvironmentObject): { shape: string; detail: string } {
  if (object.kind === 'function') return { shape: '', detail: object.preview }
  if (object.kind === 'data') return { shape: object.shape, detail: '' }
  if (!object.preview) return { shape: object.shape, detail: '' }
  if (object.shape === 'length 1') return { shape: '', detail: object.preview }
  return { shape: object.shape, detail: object.preview }
}

/** The full story about one object, for the row's tooltip. */
function describe(object: REnvironmentObject): string {
  const parts = [object.type]
  if (object.shape) parts.push(object.shape)
  if (object.preview && object.kind !== 'function') parts.push(object.preview)
  if (object.kind === 'function') parts.push(object.preview)
  if (object.bytes > 0) parts.push(`${Math.max(1, Math.round(object.bytes / 1024))} KB`)
  return parts.filter(Boolean).join('\n')
}

function SaveScriptModal({
  projectId,
  script,
  code,
  onClose,
}: {
  projectId: string
  /** Null when saving what is in the console as something new. */
  script: ProjectScript | null
  code: string
  onClose: () => void
}) {
  const toast = useToast()
  const queryClient = useQueryClient()
  const [name, setName] = useState(script?.name ?? '')
  const [description, setDescription] = useState(script?.description ?? '')
  const [body, setBody] = useState(code)
  const [onImport, setOnImport] = useState(script?.run_on_import ?? false)

  const save = useMutation({
    mutationFn: () => {
      const payload = {
        name: name.trim(),
        description: description.trim(),
        code: body,
        run_on_import: onImport,
      }
      return script
        ? api.patch(`/projects/${projectId}/scripts/${script.id}`, payload)
        : api.post(`/projects/${projectId}/scripts`, payload)
    },
    onSuccess: () => {
      toast.push(script ? 'Script saved' : 'Script created', 'success')
      queryClient.invalidateQueries({ queryKey: ['project-scripts', projectId] })
      onClose()
    },
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  return (
    <Modal
      open
      onClose={onClose}
      title={script ? `Edit "${script.name}"` : 'Save this as a script'}
      wide
      footer={
        <>
          <button className="btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button
            className="btn-primary"
            disabled={!name.trim() || save.isPending}
            onClick={() => save.mutate()}
          >
            Save
          </button>
        </>
      }
    >
      <Field label="Name">
        <input
          className="input"
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="Derive the poverty line"
          autoFocus
        />
      </Field>
      <Field label="What it does" hint="For whoever opens this project next.">
        <input
          className="input"
          value={description}
          onChange={(event) => setDescription(event.target.value)}
        />
      </Field>
      <Field label="The script">
        <CodeEditor
          ariaLabel="The script"
          value={body}
          onChange={setBody}
          minHeight={200}
        />
      </Field>
      <label className="flex items-center gap-2 text-sm text-ink-700">
        <input
          type="checkbox"
          checked={onImport}
          onChange={(event) => setOnImport(event.target.checked)}
        />
        Run this again after a new export lands in this project
      </label>
      <p className="mt-1 text-xs text-ink-500">
        A variable derived here is not in the file that arrives, so without this it
        disappears on the next import.
      </p>
    </Modal>
  )
}
