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

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
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

interface RunResult {
  message: string
  output: string
  written: { name: string; id: string; rows: number }[]
  files: string[]
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

  const files = useQuery({
    queryKey: ['project-workspace', projectId],
    queryFn: () =>
      api.get<{ files: { path: string; bytes: number }[] }>(
        `/projects/${projectId}/workspace`,
      ),
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
    mutationFn: () => api.post<RunResult>(`/projects/${projectId}/run`, { code }),
    onSuccess: settled,
    onError: (error: Error) => {
      setResult(null)
      setFailure(error.message)
    },
  })

  const runSaved = useMutation({
    mutationFn: (script: ProjectScript) =>
      api.post<RunResult>(`/projects/${projectId}/scripts/${script.id}/run`),
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
                {runConsole.isPending ? 'Running...' : 'Run'}
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
            of this project, replacing one of that name if it is already here.
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
            Boolean(files.data?.files.length) && (
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
          {!files.data?.files.length ? (
            <p className="text-sm text-ink-400">Nothing here yet.</p>
          ) : (
            <ul className="space-y-1 font-mono text-xs text-ink-600">
              {files.data.files.map((file) => (
                <li key={file.path} className="flex justify-between gap-2">
                  <span className="truncate">{file.path}</span>
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
