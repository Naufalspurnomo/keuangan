import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import ProjectHealthBoard, { buildCandleDemo } from './ProjectHealthBoard'
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

afterEach(cleanup)

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

  it('survives malformed snapshot dates and accepts ISO timestamps', () => {
    expect(() => buildCandleDemo([project('Malformed', 'Hollawall')], '2026-99-99')).not.toThrow()
    render(<ProjectHealthBoard projects={[{ ...project('Timestamp', 'Hollawall'), last_activity_on: '2026-10-20T12:30:00Z' }]} asOf="2026-10-21" onOpen={vi.fn()} />)
    expect(screen.queryByText(/Invalid Date/)).toBeNull()
    expect(screen.getByText(/aktivitas terakhir 20 Okt 2026/)).toBeTruthy()
  })

  it('defaults to actual snapshot data outside explicit snapshot QA builds', () => {
    render(<ProjectHealthBoard projects={[project('Actual Age', 'Hollawall')]} asOf="2026-10-21" onOpen={vi.fn()} />)
    expect(screen.getByRole('button', { name: 'Data aktual' }).getAttribute('aria-pressed')).toBe('true')
    expect(screen.getAllByText('200 hari').length).toBeGreaterThan(0)
  })

  it('reports unmarked projects and exposes complete row context', () => {
    const unmarked = { ...project('Tanpa Marker', 'Hollawall'), health: 'unmarked' as const, lifecycle_status: 'unmarked' as const, age_days: null }
    render(<ProjectHealthBoard projects={[unmarked]} asOf="2026-10-21" onOpen={vi.fn()} />)
    expect(screen.getAllByText('Belum ditandai').length).toBeGreaterThan(0)
    expect(screen.getByRole('button', { name: /Buka transaksi proyek Tanpa Marker, Hollawall, 0 transaksi/ })).toBeTruthy()
  })
})
