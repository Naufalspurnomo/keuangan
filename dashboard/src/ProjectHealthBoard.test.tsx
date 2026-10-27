import { describe, expect, it } from 'vitest'

import { buildCandleDemo } from './ProjectHealthBoard'
import type { ProjectSummary } from './snapshot'

const project = (name: string, portfolio: 'Hollawall' | 'Texturin'): ProjectSummary => ({
  name,
  portfolio,
  net_cashflow: 0,
  lifecycle_status: 'active',
  health: 'overdue',
  age_days: 200,
  started_on: '2026-01-01',
  first_activity_on: '2026-01-02',
  last_activity_on: '2026-10-20',
})

describe('project candle demo data', () => {
  it('spreads every portfolio independently from green through red', () => {
    const result = buildCandleDemo([
      project('H1', 'Hollawall'), project('H2', 'Hollawall'), project('H3', 'Hollawall'),
      project('T1', 'Texturin'), project('T2', 'Texturin'), project('T3', 'Texturin'),
    ], '2026-10-21')

    expect(result.filter((item) => item.portfolio === 'Hollawall').map((item) => item.age_days)).toEqual([3, 47, 90])
    expect(result.filter((item) => item.portfolio === 'Texturin').map((item) => item.age_days)).toEqual([3, 47, 90])
  })

  it('keeps demo dates aligned with the supplied local calendar date', () => {
    const [result] = buildCandleDemo([project('Single', 'Hollawall')], '2026-10-21')
    expect(result.age_days).toBe(21)
    expect(result.started_on).toBe('2026-09-30')
    expect(result.last_activity_on).toBe('2026-10-19')
  })
})