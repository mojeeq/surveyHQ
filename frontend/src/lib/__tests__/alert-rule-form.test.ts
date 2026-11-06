/**
 * Opening a rule and saving it unchanged must leave it unchanged.
 *
 * One form creates rules and edits them, so every field it sends has to be a
 * field it read back. A field that is sent but not prefilled looks fine on
 * screen - the box is simply empty or on its default - and quietly overwrites
 * whatever the rule had the moment somebody corrects a threshold.
 */
import { describe, expect, it } from 'vitest'

import { bodyFrom, formFor, isComplete } from '@/lib/alert-rule-form'
import type { AlertRule } from '@/lib/types'

const rule: AlertRule = {
  id: 'rule-1',
  name: 'Interviews falling behind',
  description: '',
  indicator_id: 'indicator-7',
  dataset_id: null,
  condition: { operator: 'gte', value: 250 },
  severity: 'critical',
  channels: ['in_app', 'email'],
  recipients: ['field@example.org', 'hq@example.org'],
  cooldown_minutes: 15,
  is_active: true,
  last_triggered_at: null,
  created_at: '2026-01-01T00:00:00Z',
}

describe('the alert rule form', () => {
  it('sends a rule back exactly as it found it', () => {
    expect(bodyFrom(formFor(rule))).toEqual({
      name: rule.name,
      indicator_id: rule.indicator_id,
      condition: rule.condition,
      severity: rule.severity,
      cooldown_minutes: rule.cooldown_minutes,
      channels: rule.channels,
      recipients: rule.recipients,
    })
  })

  it('keeps a threshold of zero, which is not the same as an empty box', () => {
    const form = formFor({ ...rule, condition: { operator: 'lte', value: 0 } })
    expect(form.value).toBe('0')
    expect(isComplete(form)).toBe(true)
    expect(bodyFrom(form).condition).toEqual({ operator: 'lte', value: 0 })
  })

  it('drops the email channel when the box is cleared', () => {
    expect(bodyFrom({ ...formFor(rule), email: false }).channels).toEqual(['in_app'])
  })

  it('reads the email box from the rule rather than defaulting it off', () => {
    expect(formFor(rule).email).toBe(true)
    expect(formFor({ ...rule, channels: ['in_app'] }).email).toBe(false)
  })

  it('starts a new rule blank, and refuses to send it that way', () => {
    const blank = formFor()
    expect(blank).toEqual({
      name: '',
      indicatorId: '',
      operator: 'lt',
      value: '',
      severity: 'warning',
      cooldown: '60',
      email: false,
      recipients: '',
    })
    expect(isComplete(blank)).toBe(false)
    expect(isComplete({ ...blank, name: 'A rule' })).toBe(false)
    expect(isComplete({ ...blank, name: 'A rule', indicatorId: 'i', value: '5' })).toBe(true)
  })

  it('takes recipients apart on commas and tidies the spacing', () => {
    expect(bodyFrom({ ...formFor(rule), recipients: ' a@x.org ,, b@x.org ' }).recipients).toEqual([
      'a@x.org',
      'b@x.org',
    ])
  })
})
