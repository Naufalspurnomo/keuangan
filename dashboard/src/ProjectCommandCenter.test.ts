import { describe, expect, it } from 'vitest'

import { projectAsOf } from './ProjectCommandCenter'

describe('projectAsOf', () => {
  it('stops a current-year active project at today instead of future year-end', () => {
    const now = new Date('2026-10-28T12:00:00+07:00')
    expect(projectAsOf(2026, now).getTime()).toBe(now.getTime())
  })

  it('uses year-end for historical project cohorts', () => {
    const now = new Date('2026-10-28T12:00:00+07:00')
    const historical = projectAsOf(2025, now)
    expect(historical.getFullYear()).toBe(2025)
    expect(historical.getMonth()).toBe(11)
    expect(historical.getDate()).toBe(31)
  })
})
