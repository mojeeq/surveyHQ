/**
 * The web servers dashboards can be published to.
 *
 * Set up here, by an administrator, because each one holds the credentials
 * for somebody else's server - a GitHub token, an SSH key, an FTP password.
 * Anybody who may share a dashboard can then publish it to one from the
 * dashboard's Share dialog, without ever seeing those credentials.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { Badge, Card, ErrorNote, Field, Loading, Modal, Segmented, Spinner, Toggle } from '@/components/ui'
import { useDialog } from '@/hooks/useDialog'
import { useToast } from '@/hooks/useToast'
import { api } from '@/lib/api'
import { KIND_LABEL, whereTo } from '@/lib/publishing'
import type { PublishKind, PublishTarget, TargetCheck } from '@/lib/publishing'

export default function PublishTargets() {
  const toast = useToast()
  const ask = useDialog()
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState<PublishTarget | 'new' | null>(null)
  // The last test, shown under the list until another. Carries the name it
  // was started with: a destination just added is not in the list yet when
  // its test starts, and the panel should say what it is testing at once.
  const [tested, setTested] = useState<Tested | null>(null)

  const targets = useQuery({
    queryKey: ['publish-targets'],
    queryFn: () => api.get<PublishTarget[]>('/publishing/targets'),
  })

  const test = useMutation({
    mutationFn: ({ id }: { id: string; name: string }) =>
      api.post<TargetCheck>(`/publishing/targets/${id}/test`),
    onMutate: (which) => setTested(which),
    onSuccess: (result, which) => {
      setTested({ ...which, result })
      // A first SSH test trusts the server's key, which the list shows.
      queryClient.invalidateQueries({ queryKey: ['publish-targets'] })
    },
    onError: (error: Error, which) => setTested({ ...which, error: error.message }),
  })

  const remove = useMutation({
    mutationFn: (id: string) => api.delete<{ detail: string }>(`/publishing/targets/${id}`),
    onSuccess: (result) => {
      toast.push(result.detail, 'success')
      setTested(null)
      queryClient.invalidateQueries({ queryKey: ['publish-targets'] })
    },
    onError: (error: Error) => toast.push(error.message, 'error'),
  })

  return (
    <Card
      title="Publishing"
      subtitle="Websites dashboards can be published to: GitHub Pages, or a web server over SFTP or FTP."
      actions={
        <button className="btn-primary btn-sm" onClick={() => setEditing('new')}>
          Add destination
        </button>
      }
    >
      <p className="mb-4 max-w-3xl text-sm text-ink-600 dark:text-dark-600">
        A published dashboard is the same file as the HTML download: its filters work, and it
        carries the numbers each widget shows - never a row of data. Anybody who may share a
        dashboard can publish it to a destination here, from the dashboard&rsquo;s Share dialog.
        Nothing this platform did not write is overwritten or deleted on the server.
      </p>

      {targets.isLoading ? (
        <Loading />
      ) : targets.error ? (
        <ErrorNote error={targets.error} retry={targets.refetch} />
      ) : (
        <div className="overflow-x-auto">
          <table className="table-base">
            <thead>
              <tr>
                <th>Name</th>
                <th>Kind</th>
                <th>Where</th>
                <th>Address</th>
                <th>Published</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {(targets.data ?? []).map((target) => (
                <tr key={target.id}>
                  <td className="font-medium">{target.name}</td>
                  <td>
                    <Badge>{KIND_LABEL[target.kind]}</Badge>
                  </td>
                  <td className="max-w-[16rem] truncate font-mono text-xs" title={whereTo(target)}>
                    {whereTo(target)}
                  </td>
                  <td className="max-w-[16rem] truncate text-xs">
                    {target.folder_url ? (
                      <a
                        href={target.folder_url}
                        target="_blank"
                        rel="noreferrer"
                        className="text-brand-700 hover:underline dark:text-brand-400"
                      >
                        {target.folder_url}
                      </a>
                    ) : (
                      <span className="text-ink-500">Not set</span>
                    )}
                  </td>
                  <td className="text-xs text-ink-600 dark:text-dark-600">
                    {target.publications
                      ? `${target.publications} dashboard${target.publications === 1 ? '' : 's'}`
                      : 'Nothing yet'}
                  </td>
                  <td className="whitespace-nowrap text-right">
                    <button
                      className="btn-ghost btn-sm"
                      disabled={test.isPending}
                      onClick={() => test.mutate({ id: target.id, name: target.name })}
                    >
                      {test.isPending && test.variables?.id === target.id && (
                        <Spinner className="h-3.5 w-3.5" />
                      )}
                      Test
                    </button>
                    <button className="btn-ghost btn-sm" onClick={() => setEditing(target)}>
                      Edit
                    </button>
                    <button
                      className="btn-ghost btn-sm text-red-700 dark:text-red-300"
                      onClick={async () => {
                        const sure = await ask.confirm({
                          title: `Delete “${target.name}”?`,
                          message:
                            'The destination and its credentials are removed from this platform. ' +
                            'Nothing on the server is touched.',
                          confirmLabel: 'Delete destination',
                          tone: 'danger',
                        })
                        if (sure) remove.mutate(target.id)
                      }}
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
              {!targets.data?.length && (
                <tr>
                  <td colSpan={6} className="py-8 text-center text-sm text-ink-500">
                    No destinations yet. Add one to publish dashboards to a website.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {tested && <TestResult tested={tested} />}

      {editing && (
        <TargetForm
          target={editing === 'new' ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={(saved, created) => {
            setEditing(null)
            queryClient.invalidateQueries({ queryKey: ['publish-targets'] })
            // Tried straight away: a destination that has never been tested
            // is one nobody knows works, and an SFTP one cannot be published
            // to until its server's key has been seen.
            if (created) test.mutate({ id: saved.id, name: saved.name })
            else toast.push('Destination saved', 'success')
          }}
        />
      )}
    </Card>
  )
}

interface Tested {
  id: string
  name: string
  result?: TargetCheck
  error?: string
}

function TestResult({ tested }: { tested: Tested }) {
  const { name, result, error } = tested
  if (!result && !error) {
    return (
      <p className="mt-4 flex items-center gap-2 text-sm text-ink-600 dark:text-dark-600">
        <Spinner className="h-4 w-4" /> Testing {name}&hellip;
      </p>
    )
  }
  return (
    <div
      role="status"
      className={`mt-4 rounded-card border px-3 py-2.5 text-sm ${
        error
          ? 'border-red-200 bg-red-50 text-red-800 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-200'
          : 'border-ink-200 bg-ink-50 text-ink-800 dark:border-dark-200 dark:bg-dark-100 dark:text-dark-800'
      }`}
    >
      <p className="font-medium">{error ? `${name} could not be used` : `${name} works`}</p>
      <p className="mt-0.5">{error || result?.message}</p>
      {result?.notes.map((note) => (
        <p key={note} className="mt-1 text-xs text-ink-600 dark:text-dark-600">
          {note}
        </p>
      ))}
      {result?.host_key_fingerprint && (
        <p className="mt-1 font-mono text-xs text-ink-600 dark:text-dark-600">
          Server key: {result.host_key_fingerprint}
        </p>
      )}
    </div>
  )
}

type Draft = Record<string, string | number | boolean>

const DEFAULTS: Record<PublishKind, Draft> = {
  github: { owner: '', repo: '', branch: 'gh-pages', folder: '', site_url: '', api_url: '', contents_page: true },
  sftp: { host: '', port: 22, username: '', auth: 'password', folder: '', site_url: '', contents_page: false },
  ftp: { host: '', port: 21, username: '', folder: '', site_url: '', tls: true, verify_tls: true, contents_page: false },
}

function TargetForm({
  target,
  onClose,
  onSaved,
}: {
  target: PublishTarget | null
  onClose: () => void
  onSaved: (target: PublishTarget, created: boolean) => void
}) {
  const queryClient = useQueryClient()
  const [kind, setKind] = useState<PublishKind>(target?.kind ?? 'github')
  const [name, setName] = useState(target?.name ?? '')
  const [settings, setSettings] = useState<Draft>(() => ({
    ...DEFAULTS[target?.kind ?? 'github'],
    ...(target?.settings as Draft | undefined),
  }))
  const [secret, setSecret] = useState({ token: '', password: '', private_key: '', passphrase: '' })
  const [error, setError] = useState('')
  const kept = new Set(target?.secrets ?? [])
  const set = (key: string, value: string | number | boolean) =>
    setSettings((was) => ({ ...was, [key]: value }))
  const value = (key: string) => String(settings[key] ?? '')

  const save = useMutation({
    mutationFn: () => {
      const body = { name: name.trim(), settings, ...secret }
      return target
        ? api.patch<PublishTarget>(`/publishing/targets/${target.id}`, body)
        : api.post<PublishTarget>('/publishing/targets', { ...body, kind })
    },
    onSuccess: (saved) => onSaved(saved, !target),
    onError: (failed: Error) => setError(failed.message),
  })

  const forget = useMutation({
    mutationFn: () =>
      api.patch<PublishTarget>(`/publishing/targets/${target!.id}`, { forget_host_key: true }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['publish-targets'] }),
  })

  const secretHint = (key: keyof typeof secret, otherwise: string) =>
    kept.has(key) ? 'Kept. Leave this empty to keep it, or type a new one to replace it.' : otherwise

  return (
    <Modal
      open
      wide
      title={target ? `Edit “${target.name}”` : 'Add a destination'}
      onClose={onClose}
      footer={
        <>
          <button className="btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button
            className="btn-primary"
            disabled={save.isPending || !name.trim()}
            onClick={() => {
              setError('')
              save.mutate()
            }}
          >
            {save.isPending && <Spinner className="h-4 w-4 text-white" />}
            {target ? 'Save' : 'Add and test'}
          </button>
        </>
      }
    >
      {!target && (
        <div className="mb-4">
          <Segmented
            label="Kind of destination"
            value={kind}
            onChange={(next) => {
              setKind(next)
              setSettings(DEFAULTS[next])
            }}
            options={[
              { value: 'github', label: 'GitHub Pages' },
              { value: 'sftp', label: 'Web server (SFTP)' },
              { value: 'ftp', label: 'Web host (FTP)' },
            ]}
          />
        </div>
      )}

      <Field label="Name" hint="What people choose when they publish, e.g. Public website.">
        <input
          className="input"
          aria-label="Name"
          value={name}
          maxLength={120}
          onChange={(event) => setName(event.target.value)}
        />
      </Field>

      {kind === 'github' && (
        <>
          <p className="mb-3 text-xs text-ink-600 dark:text-dark-600">
            Pages are committed to a branch of a repository and served by GitHub Pages at{' '}
            <code>https://account.github.io/repository/</code>. A GitHub Pages site is public even
            when the repository is private.
          </p>
          <div className="grid gap-x-4 sm:grid-cols-2">
            <Text label="Account or organisation" name="owner" value={value} set={set} placeholder="statsoffice" />
            <Text label="Repository" name="repo" value={value} set={set} placeholder="dashboards" />
            <Text
              label="Branch"
              name="branch"
              value={value}
              set={set}
              hint="GitHub Pages serves this branch. Made if it does not exist yet."
            />
            <Text
              label="Folder in the repository"
              name="folder"
              value={value}
              set={set}
              hint="Optional. Leave empty to publish at the top of the site."
            />
          </div>
          <Field
            label="Token"
            hint={secretHint(
              'token',
              'A fine-grained personal access token for this repository, with Contents: Read and write - and Pages: Read and write, to switch GitHub Pages on by itself.',
            )}
          >
            <input
              className="input font-mono"
              aria-label="Token"
              type="password"
              autoComplete="off"
              value={secret.token}
              onChange={(event) => setSecret((was) => ({ ...was, token: event.target.value }))}
            />
          </Field>
          <p className="-mt-2 mb-4 text-xs">
            <a
              className="text-brand-700 hover:underline dark:text-brand-400"
              href="https://github.com/settings/personal-access-tokens/new"
              target="_blank"
              rel="noreferrer"
            >
              Make a token on GitHub
            </a>
          </p>
          <details className="mb-4 text-sm">
            <summary className="cursor-pointer text-ink-700 dark:text-dark-700">
              A custom domain, or GitHub Enterprise
            </summary>
            <div className="mt-3 grid gap-x-4 sm:grid-cols-2">
              <Text
                label="Web address of the site"
                name="site_url"
                value={value}
                set={set}
                placeholder="https://dashboards.example.org/"
                hint="Only if the site has its own domain."
              />
              <Text
                label="API address"
                name="api_url"
                value={value}
                set={set}
                placeholder="https://api.github.com/"
                hint="Only for GitHub Enterprise Server."
              />
            </div>
          </details>
        </>
      )}

      {kind !== 'github' && (
        <>
          <div className="grid gap-x-4 sm:grid-cols-[1fr_7rem]">
            <Text label="Server" name="host" value={value} set={set} placeholder="stats.example.org" />
            <Field label="Port">
              <input
                className="input"
                aria-label="Port"
                inputMode="numeric"
                value={value('port')}
                onChange={(event) => set('port', event.target.value.replace(/\D/g, ''))}
              />
            </Field>
          </div>
          <Text label="User name" name="username" value={value} set={set} />
          {kind === 'sftp' && (
            <div className="mb-4">
              <Segmented
                label="Sign in with"
                value={(value('auth') || 'password') as 'password' | 'key'}
                onChange={(next) => set('auth', next)}
                options={[
                  { value: 'password', label: 'Password' },
                  { value: 'key', label: 'Private key' },
                ]}
              />
            </div>
          )}
          {kind === 'sftp' && value('auth') === 'key' ? (
            <>
              <Field
                label="Private key"
                hint={secretHint(
                  'private_key',
                  'The whole key, from its -----BEGIN line to its -----END line. Ed25519, ECDSA and RSA keys work.',
                )}
              >
                <textarea
                  className="input font-mono text-xs"
                  aria-label="Private key"
                  rows={5}
                  autoComplete="off"
                  spellCheck={false}
                  value={secret.private_key}
                  onChange={(event) => setSecret((was) => ({ ...was, private_key: event.target.value }))}
                />
              </Field>
              <Field label="Passphrase" hint="Only if the key has one.">
                <input
                  className="input"
                  aria-label="Passphrase"
                  type="password"
                  autoComplete="off"
                  value={secret.passphrase}
                  onChange={(event) => setSecret((was) => ({ ...was, passphrase: event.target.value }))}
                />
              </Field>
            </>
          ) : (
            <Field label="Password" hint={secretHint('password', 'For the user name above.')}>
              <input
                className="input"
                aria-label="Password"
                type="password"
                autoComplete="off"
                value={secret.password}
                onChange={(event) => setSecret((was) => ({ ...was, password: event.target.value }))}
              />
            </Field>
          )}
          <div className="grid gap-x-4 sm:grid-cols-2">
            <Text
              label="Folder on the server"
              name="folder"
              value={value}
              set={set}
              placeholder={kind === 'sftp' ? '/var/www/html/dashboards' : 'public_html/dashboards'}
              hint="Where the pages go. Made if it is not there."
            />
            <Text
              label="Web address of that folder"
              name="site_url"
              value={value}
              set={set}
              placeholder="https://stats.example.org/dashboards/"
              hint="What a reader types to reach it, so published dashboards get a link."
            />
          </div>
          {kind === 'ftp' && (
            <div className="mb-4 space-y-2">
              <Toggle
                checked={settings.tls !== false}
                onChange={(next) => set('tls', next)}
                label="Encrypt the connection (FTPS)"
              />
              {settings.tls === false && (
                <p className="text-xs text-amber-800 dark:text-amber-200">
                  Without encryption the password and the pages cross the network as they are.
                </p>
              )}
              {settings.tls !== false && (
                <div>
                  <Toggle
                    checked={settings.verify_tls !== false}
                    onChange={(next) => set('verify_tls', next)}
                    label="Check the server's certificate"
                  />
                </div>
              )}
            </div>
          )}
          {kind === 'sftp' && target?.host_key_fingerprint && (
            <p className="mb-4 text-xs text-ink-600 dark:text-dark-600">
              Trusted server key: <span className="font-mono">{target.host_key_fingerprint}</span>.{' '}
              <button
                type="button"
                className="font-medium text-brand-700 hover:underline dark:text-brand-400"
                disabled={forget.isPending}
                onClick={() => forget.mutate()}
              >
                {forget.isSuccess ? 'Forgotten - test it to trust the new one' : 'Forget it'}
              </button>{' '}
              if the server was rebuilt and its key changed.
            </p>
          )}
        </>
      )}

      <div className="mb-1">
        <Toggle
          checked={Boolean(settings.contents_page)}
          onChange={(next) => set('contents_page', next)}
          label="Keep a list of the published dashboards at the front of the folder"
        />
        <p className="mt-1 text-xs text-ink-500 dark:text-dark-500">
          An index.html linking to each one, kept up to date as they are published and taken
          down. Left alone if the folder already has a front page of its own.
        </p>
      </div>

      {error && (
        <p role="alert" className="mt-3 text-sm text-red-700 dark:text-red-300">
          {error}
        </p>
      )}
    </Modal>
  )
}

function Text({
  label,
  name,
  value,
  set,
  placeholder,
  hint,
}: {
  label: string
  name: string
  value: (key: string) => string
  set: (key: string, value: string) => void
  placeholder?: string
  hint?: string
}) {
  return (
    <Field label={label} hint={hint}>
      <input
        className="input"
        aria-label={label}
        value={value(name)}
        placeholder={placeholder}
        onChange={(event) => set(name, event.target.value)}
      />
    </Field>
  )
}
