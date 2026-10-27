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

    expect(onOpen).toHaveBeenCalledWith('Candle Merah', 'Hollawall')
    expect(container.querySelector('.candle-legend')?.textContent).toContain('Garis putih = rentang transaksi')
  })

  it('keeps keyboard activation working after a mouse pan', () => {
    const onOpen = vi.fn()
    const { container } = render(<ActiveProjectAgeChart projects={projects} portfolios={['Hollawall']} query="" asOf="2026-10-21" onOpen={onOpen} />)
    const viewport = container.querySelector('.active-calendar-viewport') as HTMLDivElement
    const candle = container.querySelector('[data-project-candle="Candle Hijau"]') as HTMLButtonElement
    Object.defineProperty(viewport, 'setPointerCapture', { value: vi.fn() })
    Object.defineProperty(viewport, 'hasPointerCapture', { value: vi.fn(() => false) })
    fireEvent.pointerDown(viewport, { pointerType: 'mouse', button: 0, pointerId: 7, clientX: 200, clientY: 100 })
    fireEvent.pointerMove(viewport, { pointerType: 'mouse', pointerId: 7, clientX: 120, clientY: 100 })
    fireEvent.pointerUp(viewport, { pointerType: 'mouse', pointerId: 7, clientX: 120, clientY: 100 })
    fireEvent.click(candle, { detail: 0 })
    expect(onOpen).toHaveBeenCalledWith('Candle Hijau', 'Hollawall')
  })

  it('does not duplicate the current month marker on the first day', () => {
    const { container } = render(<ActiveProjectAgeChart projects={projects} portfolios={['Hollawall']} query="" asOf="2026-10-01" onOpen={vi.fn()} />)
    const markers = [...container.querySelectorAll('.active-calendar-axis b')].map((node) => node.textContent)
    expect(markers.filter((label) => label === 'SNAPSHOT 1 OKT')).toHaveLength(1)
    expect(markers).not.toContain('OKTOBER')
  })

  it('keeps chart pagination after an equivalent parent rerender', () => {
    const manyProjects = Array.from({ length: 12 }, (_, index) => ({
      ...projects[0], name: `Project ${String(index + 1).padStart(2, '0')}`, age_days: index + 1,
    }))
    const onOpen = vi.fn()
    const { container, rerender } = render(<ActiveProjectAgeChart projects={manyProjects} portfolios={['Hollawall']} query="" asOf="2026-10-21" onOpen={onOpen} />)
    fireEvent.click(container.querySelector('[aria-label="Halaman berikutnya Hollawall"]') as HTMLButtonElement)
    expect(container.querySelector('.active-age-section footer nav span')?.textContent).toBe('2 / 2')
    rerender(<ActiveProjectAgeChart projects={manyProjects.map((project) => ({ ...project }))} portfolios={['Hollawall']} query="" asOf="2026-10-21" onOpen={onOpen} />)
    expect(container.querySelector('.active-age-section footer nav span')?.textContent).toBe('2 / 2')
  })
})
