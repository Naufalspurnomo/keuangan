import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import ProjectLifecycleMarketChart from './ProjectLifecycleMarketChart'
import type { CompanyId, FinanceProject, FinanceTransaction } from './financeWorkspace'

const project = (id: string, name: string, company: CompanyId, status: FinanceProject['status'], started_on: string, completed_on: string | null = null): FinanceProject => ({
  id, name, company, status, started_on, completed_on, wallet: company === 'Holla' || company === 'Hojja' ? 'CV HB' : company === 'Texturin Bali' ? 'TX Bali' : 'TX SBY',
  client: '', contract_value: null, notes: '', created_at: `${started_on}T00:00:00Z`, updated_at: `${completed_on ?? started_on}T00:00:00Z`,
})

const projects: FinanceProject[] = [
  project('h-old', 'Holla Lama', 'Holla', 'completed', '2026-01-10', '2026-03-12'),
  project('h-active', 'Holla Terbaru', 'Holla', 'active', '2026-10-18'),
  project('hj-active', 'Hojja Aktif', 'Hojja', 'active', '2026-08-01'),
  project('bali-active', 'Bali Aktif', 'Texturin Bali', 'active', '2026-07-01'),
  project('sby-done', 'Surabaya Selesai', 'Texturin Surabaya', 'completed', '2026-03-01', '2026-09-01'),
]

const transactions: FinanceTransaction[] = [
  { id: 't1', date: '2026-01-12', direction: 'income', amount: 10, scope: 'project', wallet: 'CV HB', company: 'Holla', project_id: 'h-old', office_category: null, notes: '', created_at: '', updated_at: '' },
  { id: 't2', date: '2026-03-10', direction: 'expense', amount: 5, scope: 'project', wallet: 'CV HB', company: 'Holla', project_id: 'h-old', office_category: null, notes: '', created_at: '', updated_at: '' },
]

afterEach(cleanup)

describe('ProjectLifecycleMarketChart', () => {
  it('renders four fixed company canvases with active/total summaries and no chart pagination', () => {
    const { container } = render(<ProjectLifecycleMarketChart projects={projects} transactions={transactions} year={2026} asOf={new Date('2026-10-28T12:00:00+07:00')} onOpen={vi.fn()} />)
    expect(container.querySelectorAll('.project-market-canvas')).toHaveLength(4)
    for (const company of ['Holla', 'Hojja', 'Texturin Bali', 'Texturin Surabaya']) {
      expect(screen.getByRole('region', { name: `Chart lifecycle ${company}` })).toBeTruthy()
    }
    expect([...container.querySelectorAll('.project-market-canvas')].map((node) => node.getAttribute('data-project-company'))).toEqual(['Holla', 'Hojja', 'Texturin Bali', 'Texturin Surabaya'])
    expect(screen.getByLabelText('Ringkasan Holla').textContent).toContain('1 / 2')
    expect(screen.getByLabelText('Ringkasan Texturin Surabaya').textContent).toContain('0 / 1')
    expect(container.querySelector('[aria-label="Halaman chart"]')).toBeNull()
    expect(container.textContent).not.toContain('Sebelumnya')
    expect(container.textContent).not.toContain('Berikutnya')
  })

  it('draws a full-year month axis, keeps completed projects, and orders newest on the right', () => {
    const { container } = render(<ProjectLifecycleMarketChart projects={projects} transactions={transactions} year={2026} asOf={new Date('2026-10-28T12:00:00+07:00')} onOpen={vi.fn()} />)
    const holla = container.querySelector('[data-project-company="Holla"]') as HTMLElement
    expect(holla.querySelectorAll('.project-market-month')).toHaveLength(12)
    expect([...holla.querySelectorAll('[data-project-candle]')].map((node) => node.getAttribute('data-project-candle'))).toEqual(['Holla Lama', 'Holla Terbaru'])
    expect(holla.querySelector('[data-project-candle="Holla Lama"]')?.classList.contains('is-completed')).toBe(true)
    expect(holla.querySelector('.project-market-wick')).toBeTruthy()
  })

  it('supports synchronized zoom, drag pan, reset, latest, and candle activation', () => {
    const onOpen = vi.fn()
    const { container } = render(<ProjectLifecycleMarketChart projects={projects} transactions={transactions} year={2026} asOf={new Date('2026-10-28T12:00:00+07:00')} onOpen={onOpen} />)
    const canvas = container.querySelector('[data-project-company="Holla"]') as HTMLElement
    const viewport = canvas.querySelector('.project-market-viewport') as HTMLDivElement
    Object.defineProperties(viewport, {
      scrollWidth: { value: 1200, configurable: true }, clientWidth: { value: 500, configurable: true },
      scrollHeight: { value: 1000, configurable: true }, clientHeight: { value: 420, configurable: true },
      setPointerCapture: { value: vi.fn(), configurable: true }, hasPointerCapture: { value: vi.fn(() => false), configurable: true },
    })
    const chart = canvas.querySelector('.project-market-chart') as HTMLElement
    const before = chart.getAttribute('style')
    fireEvent.click(screen.getByRole('button', { name: 'Perbesar semua chart' }))
    expect(chart.getAttribute('style')).not.toEqual(before)

    const afterButtonZoom = chart.getAttribute('style')
    fireEvent.wheel(viewport, { deltaY: -100 })
    expect(chart.getAttribute('style')).not.toEqual(afterButtonZoom)

    viewport.scrollLeft = 100
    viewport.scrollTop = 100
    fireEvent.pointerDown(viewport, { pointerType: 'mouse', button: 0, pointerId: 7, clientX: 200, clientY: 180 })
    fireEvent.pointerMove(viewport, { pointerType: 'mouse', pointerId: 7, clientX: 150, clientY: 130 })
    fireEvent.pointerUp(viewport, { pointerType: 'mouse', pointerId: 7, clientX: 150, clientY: 130 })
    expect(viewport.scrollLeft).toBeGreaterThan(100)
    expect(viewport.scrollTop).toBeGreaterThan(100)

    const otherViewport = container.querySelector('[data-project-company="Hojja"] .project-market-viewport') as HTMLDivElement
    fireEvent.scroll(viewport)
    expect(otherViewport.scrollTop).toBe(viewport.scrollTop)

    fireEvent.click(screen.getByRole('button', { name: 'Kembali ke proyek terbaru Holla' }))
    expect(viewport.scrollLeft).toBe(700)
    fireEvent.click(screen.getByRole('button', { name: 'Reset tampilan semua chart' }))
    expect(viewport.scrollTop).toBe(0)
    fireEvent.click(canvas.querySelector('[data-project-candle="Holla Terbaru"]') as HTMLButtonElement)
    expect(onOpen).toHaveBeenCalledWith(projects[1])
  })
})
