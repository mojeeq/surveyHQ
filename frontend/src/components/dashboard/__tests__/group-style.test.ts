/**
 * A group's own ground and heading.
 *
 * Its background was a fixed grey wash and its heading a fixed 12px, and the
 * frame colour it carried had nothing that set it.
 */
import { describe, expect, it } from 'vitest'

import {
  DEFAULT_GROUP_TITLE,
  groupBarGround,
  groupGround,
  groupInk,
} from '@/components/dashboard/WidgetGroups'
import type { WidgetGroup } from '@/lib/types'

const group = (extra: Partial<WidgetGroup> = {}): WidgetGroup => ({
  id: 'g1',
  name: 'Fieldwork',
  page: 0,
  x: 0,
  y: 0,
  w: 12,
  ...extra,
})

describe('a group dressed in its own colours', () => {
  it('keeps the faint wash until a ground is chosen', () => {
    expect(groupGround(group())).toContain('148 163 184')
    expect(groupBarGround(group())).toContain('148 163 184')
    expect(groupGround(group({ background: '#fdf3e7' }))).toBe('#fdf3e7')
    expect(groupBarGround(group({ background: '#fdf3e7' }))).toBe('#fdf3e7')
  })

  it('turns its heading light on a dark ground without being asked', () => {
    expect(groupInk(group({ background: '#0b2545' }))).toBe('#f4f5f7')
    expect(groupInk(group({ background: '#fdf3e7' }))).toBeUndefined()
    expect(groupInk(group())).toBeUndefined()
  })

  it('lets a chosen heading colour win over the automatic one', () => {
    expect(groupInk(group({ background: '#0b2545', color: '#ffd54f' }))).toBe('#ffd54f')
  })

  it('draws its heading at 12px until it is sized', () => {
    expect(DEFAULT_GROUP_TITLE).toBe(12)
  })
})
