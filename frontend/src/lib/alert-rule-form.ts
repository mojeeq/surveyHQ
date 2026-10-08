import type { AlertRule, Severity } from '@/lib/types'

/**
 * The alert rule form, as plain values.
 *
 * Both directions live here so they can be checked against each other. The
 * danger in one form that both creates and edits is a field that is sent but
 * not read back: open a rule, change its name, save, and the field nobody
 * prefilled is quietly reset to the form's default. The round trip test beside
 * this catches that, which no amount of looking at the modal would.
 */
export interface RuleForm {
  name: string
  indicatorId: string
  operator: string
  value: string
  severity: Severity
  cooldown: string
  email: boolean
  recipients: string
}

/** What the fields start as: a rule's own values, or sensible blanks. */
export function formFor(rule?: AlertRule): RuleForm {
  return {
    name: rule?.name ?? '',
    indicatorId: rule?.indicator_id ?? '',
    operator: rule?.condition.operator ?? 'lt',
    // Through a string, because the input is one. A threshold of 0 has to
    // survive this as "0" and not as the empty box that disables Save.
    value: rule ? String(rule.condition.value) : '',
    severity: rule?.severity ?? 'warning',
    cooldown: String(rule?.cooldown_minutes ?? 60),
    email: rule?.channels.includes('email') ?? false,
    recipients: rule?.recipients.join(', ') ?? '',
  }
}

/** What goes to the API. The same body creates a rule and updates one. */
export function bodyFrom(form: RuleForm) {
  return {
    name: form.name,
    indicator_id: form.indicatorId,
    condition: { operator: form.operator, value: Number(form.value) },
    severity: form.severity,
    cooldown_minutes: Number(form.cooldown),
    // in_app is not a choice: an alert nobody can see in the app is not an
    // alert. Email is the one that gets added.
    channels: form.email ? ['in_app', 'email'] : ['in_app'],
    recipients: form.recipients
      .split(',')
      .map((item) => item.trim())
      .filter(Boolean),
  }
}

/** Nothing is sent until the three fields a rule cannot work without are set. */
export function isComplete(form: RuleForm): boolean {
  return Boolean(form.name) && Boolean(form.indicatorId) && form.value !== ''
}
