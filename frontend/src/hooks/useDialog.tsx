import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from 'react'

import { Field, Modal } from '@/components/ui'

/**
 * The platform's own confirm, prompt and alert.
 *
 * The browser's are a different piece of software wearing a different skin,
 * announcing the server's IP address above the question, and they cannot be
 * styled at all. They also cannot do the things these need to: a destructive
 * confirm with a red button, a prompt that refuses a duplicate name without
 * throwing away what you typed.
 *
 * Promise-based so a call site reads almost the way the native one did:
 *
 *   if (await ask.confirm({ ... })) remove.mutate(id)
 *
 * The difference is `await`, which makes the handler async. That is the whole
 * migration.
 */

export interface ConfirmOptions {
  title: string
  /** The sentence under the title. Say what will happen, not "Are you sure?". */
  message?: ReactNode
  confirmLabel?: string
  cancelLabel?: string
  /** Red primary button, for anything that destroys or cannot be undone. */
  tone?: 'default' | 'danger'
}

export interface PromptOptions extends ConfirmOptions {
  label?: string
  defaultValue?: string
  placeholder?: string
  /**
   * Returns a complaint to show, or null to accept.
   *
   * Checked before the dialog closes, so a rejected value is corrected in
   * place. The native prompt could only close and be reopened empty, which is
   * why every caller of it followed up with an alert.
   */
  validate?: (value: string) => string | null
}

export interface AlertOptions {
  title: string
  message?: ReactNode
  confirmLabel?: string
  tone?: 'default' | 'danger'
}

type Pending =
  | { kind: 'confirm'; options: ConfirmOptions; settle: (ok: boolean) => void }
  | { kind: 'prompt'; options: PromptOptions; settle: (value: string | null) => void }
  | { kind: 'alert'; options: AlertOptions; settle: () => void }

interface DialogApi {
  confirm: (options: ConfirmOptions) => Promise<boolean>
  prompt: (options: PromptOptions) => Promise<string | null>
  alert: (options: AlertOptions) => Promise<void>
}

const DialogContext = createContext<DialogApi | null>(null)

export function DialogProvider({ children }: { children: ReactNode }) {
  // A queue rather than a single slot. Native dialogs blocked the thread, so
  // two could never overlap; these do not, and a second one opened from the
  // answer to the first would otherwise replace it and leave the first
  // promise unsettled forever.
  const [queue, setQueue] = useState<Pending[]>([])
  const [value, setValue] = useState('')
  const [complaint, setComplaint] = useState<string | null>(null)
  const current = queue[0]

  // Each opened dialog starts from its own default. Keyed on the request
  // itself rather than an effect, so the first paint already has the text in
  // it and nothing flashes empty.
  const shown = useRef<Pending | null>(null)
  if (current && shown.current !== current) {
    shown.current = current
    setValue(current.kind === 'prompt' ? (current.options.defaultValue ?? '') : '')
    setComplaint(null)
  }

  const ask = useCallback((request: Pending) => setQueue((q) => [...q, request]), [])

  const api = useRef<DialogApi>({
    confirm: (options) =>
      new Promise((resolve) => ask({ kind: 'confirm', options, settle: resolve })),
    prompt: (options) =>
      new Promise((resolve) => ask({ kind: 'prompt', options, settle: resolve })),
    alert: (options) =>
      new Promise((resolve) => ask({ kind: 'alert', options, settle: () => resolve() })),
  }).current

  /** Answer the open dialog and move to the next. Always settles its promise. */
  const close = (answer: 'ok' | 'cancel') => {
    if (!current) return
    if (current.kind === 'prompt') {
      if (answer === 'cancel') current.settle(null)
      else {
        const trimmed = value.trim()
        const problem = current.options.validate?.(trimmed) ?? null
        // Rejected: stay open with what they typed and say why.
        if (problem) {
          setComplaint(problem)
          return
        }
        current.settle(trimmed)
      }
    } else if (current.kind === 'confirm') {
      current.settle(answer === 'ok')
    } else {
      current.settle()
    }
    shown.current = null
    setQueue((q) => q.slice(1))
  }

  const danger = current?.options.tone === 'danger'

  return (
    <DialogContext.Provider value={api}>
      {children}
      {current && (
        <Modal
          open
          onClose={() => close('cancel')}
          title={current.options.title}
          footer={
            <>
              {current.kind !== 'alert' && (
                <button className="btn-secondary" onClick={() => close('cancel')}>
                  {current.options.cancelLabel ?? 'Cancel'}
                </button>
              )}
              <button
                className={danger ? 'btn-danger' : 'btn-primary'}
                onClick={() => close('ok')}
              >
                {current.options.confirmLabel
                  ?? (current.kind === 'alert' ? 'OK' : 'Confirm')}
              </button>
            </>
          }
        >
          {current.options.message && (
            <p className="text-sm text-ink-600 dark:text-dark-700">
              {current.options.message}
            </p>
          )}
          {current.kind === 'prompt' && (
            <div className="mt-3">
              <Field label={current.options.label ?? 'Value'}>
                <input
                  className="input"
                  autoFocus
                  value={value}
                  placeholder={current.options.placeholder}
                  onChange={(event) => {
                    setValue(event.target.value)
                    // Clear the complaint as soon as they start fixing it,
                    // rather than leaving it under a box that no longer
                    // says what it is complaining about.
                    if (complaint) setComplaint(null)
                  }}
                />
              </Field>
              {complaint && (
                <p className="-mt-2 text-sm text-red-600 dark:text-red-400" role="alert">
                  {complaint}
                </p>
              )}
            </div>
          )}
        </Modal>
      )}
    </DialogContext.Provider>
  )
}

export function useDialog(): DialogApi {
  const context = useContext(DialogContext)
  if (!context) throw new Error('useDialog must be used inside <DialogProvider>')
  return context
}
