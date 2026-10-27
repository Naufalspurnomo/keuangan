import { cleanup, fireEvent, render } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import ActiveProjectAgeChart from './ActiveProjectAgeChart'
import type { ProjectSummary } from './snapshot'

const projects: ProjectSummary[] = [
  { name: 'Candle Hijau', portfolio: 'Hollawall', net_cashflow: 1, lifecycle_status: 'active', health: 'healthy', age_days: 3, started_on: '2026-10-18', first_activity_on: '2026-10-19', last_activity_on: '2026-10-20' },
  { name: 'Candle Merah', portfolio: 'Hollawall', net_cashflow: 1, lifecycle_status: 'active', health: 'overdue', age_days: 75, started_on: '2026-08-08', first_activity_on: '2026-08-10', last_activity_on: '2026-10-18' },
]

afterEach(cleanup)

describe('project candles', () => {
  it('uses continuous age colors and keeps desktop candles clickable', () => {
    const onOpen = vi.fn()
    const { container } = render(<ActiveProjectAgeChart projects={projects} portfolios={['Hollawall']} query="" asOf="2026-10-21" onOpen={onOpen} />)
    const young = container.querySelector('[data-project-candle="Candle Hijau"]') as HTMLButtonElement
    const old = container.querySelector('[data-project-candle="Candle Merah"]') as HTMLButtonElement

    expect(young).toBeTruthy()
    expect(old).toBeTruthy()
    expect(young.getAttribute('style')).not.toEqual(old.getAttribute('style'))
    expect(young.getAttribute('style')).toContain('--bar-mid-color')

    fireEvent.pointerDown(old, { pointerType: 'mouse', button: 0, pointerId: 1, clientX: 200, clientY: 120 })
    fireEvent.pointerUp(old, { pointerType: 'mouse', button: 0, pointerId: 1, clientX: 200, clientY: 120 })
    fireEvent.click(old)

    expect(onOpen).toHaveBeenCalledWith('Candle Merah')
    expect(container.querySelector('.candle-legend')?.textContent).toContain('Garis putih = rentang transaksi')
  })
})