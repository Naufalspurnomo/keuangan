import { describe, expect, it } from 'vitest'

import { ACTION_REGISTRY, actionProps, type OwnerRoute } from './actionRegistry'

describe('canonical action registry', () => {
  it('keeps every action id stable, unique, and owned by one canonical route', () => {
    const entries = Object.entries(ACTION_REGISTRY)
    expect(entries.length).toBeGreaterThan(20)
    expect(new Set(entries.map(([id]) => id)).size).toBe(entries.length)
    for (const [id, action] of entries) {
      expect(id).toMatch(/^[a-z]+(?:\.[a-z0-9-]+)+$/)
      expect(action.owner satisfies OwnerRoute).toMatch(/^(dashboard|cashflow|wallets|projects|office|debts|reports|shell)$/)
      expect(action.label.trim()).not.toBe('')
      expect(action.kind).toMatch(/^(navigate|mutate|filter|export|preference)$/)
    }
  })

  it('projects a registered action into inspectable DOM ownership attributes', () => {
    expect(actionProps('nav.dashboard')).toEqual({
      'data-action-id': 'nav.dashboard',
      'data-owner-route': 'dashboard',
    })
  })
})
