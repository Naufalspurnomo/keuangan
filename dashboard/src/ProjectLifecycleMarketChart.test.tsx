import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import ProjectLifecycleMarketChart, { ageBand } from './ProjectLifecycleMarketChart'
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
  it.each([
    [0, 'new'],
    [14, 'new'],
    [15, 'steady'],
    [30, 'steady'],
    [31, 'watch'],
    [60, 'watch'],
    [61, 'late'],
    [90, 'late'],
    [91, 'overdue'],
  ] as const)('maps %i lifecycle days to the %s age band', (days, expected) => {
    expect(ageBand(days)).toBe(expected)
  })

  it('keeps the same overdue color for active and completed projects and marks completion separately', () => {
    const lifecycleProjects = [
      project('active-100', 'Aktif 100 Hari', 'Holla', 'active', '2026-07-20'),
      project('completed-100', 'Selesai 100 Hari', 'Holla', 'completed', '2026-07-20', '2026-10-28'),
    ]
    const { container } = render(<ProjectLifecycleMarketChart projects={lifecycleProjects} transactions={[]} year={2026} asOf={new Date('2026-10-28T12:00:00+07:00')} onOpen={vi.fn()} />)
    const active = container.querySelector('[data-project-id="active-100"]') as HTMLElement
    const completed = container.querySelector('[data-project-id="completed-100"]') as HTMLElement

    expect(active.getAttribute('data-age-band')).toBe('overdue')
    expect(completed.getAttribute('data-age-band')).toBe('overdue')
    expect(active.style.getPropertyValue('--bar-color')).toBe('#b83a3f')
    expect(completed.style.getPropertyValue('--bar-color')).toBe(active.style.getPropertyValue('--bar-color'))
    expect(active.style.getPropertyValue('--bar-mid-color')).toBe('')
    expect(active.style.getPropertyValue('--bar-start-color')).toBe('')
    expect(completed.querySelector('.project-market-completed')).toBeTruthy()
    expect(active.querySelector('.project-market-completed')).toBeNull()
    expect(completed.getAttribute('aria-label')).toContain('selesai')
    expect(completed.getAttribute('title')).toContain('selesai')
  })

  it('renders solid age-band and completion legend copy', () => {
    const { container } = render(<ProjectLifecycleMarketChart projects={projects} transactions={transactions} year={2026} asOf={new Date('2026-10-28T12:00:00+07:00')} onOpen={vi.fn()} />)
    expect(container.querySelectorAll('.age-band-swatches > i')).toHaveLength(5)
    expect(container.textContent).toContain('Warna umur: hijau · toska · kuning · oranye · merah')
    expect(container.textContent).toContain('Selesai: warna umur dipertahankan, tanda centang menunjukkan status')
  })

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

  it('renders each month axis ahead of the candle layer with 12 unique, fully spaced positions', () => {
    const { container } = render(<ProjectLifecycleMarketChart projects={projects} transactions={transactions} year={2026} asOf={new Date('2026-10-28T12:00:00+07:00')} onOpen={vi.fn()} />)

    for (const canvas of container.querySelectorAll('.project-market-canvas')) {
      const axis = canvas.querySelector('.project-market-axis') as HTMLElement
      const columns = canvas.querySelector('.project-market-columns') as HTMLElement
      const chart = canvas.querySelector('.project-market-chart') as HTMLElement
      const positions = [...canvas.querySelectorAll<HTMLElement>('.project-market-month')]
        .map((month) => Number.parseFloat(month.style.getPropertyValue('--month-position')))

      expect(axis.compareDocumentPosition(columns) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
      expect(positions).toHaveLength(12)
      expect(new Set(positions)).toHaveLength(12)
      expect(positions.every((position, index) => index === 0 || position > positions[index - 1])).toBe(true)
      expect(Number.parseFloat(chart.style.getPropertyValue('--market-height'))).toBeGreaterThanOrEqual(624)
    }
  })

  it('keeps completed projects and orders newest on the right', () => {
    const { container } = render(<ProjectLifecycleMarketChart projects={projects} transactions={transactions} year={2026} asOf={new Date('2026-10-28T12:00:00+07:00')} onOpen={vi.fn()} />)
    const holla = container.querySelector('[data-project-company="Holla"]') as HTMLElement
    expect([...holla.querySelectorAll('[data-project-candle]')].map((node) => node.getAttribute('data-project-candle'))).toEqual(['Holla Lama', 'Holla Terbaru'])
    expect(holla.querySelector('[data-project-candle="Holla Lama"]')?.classList.contains('is-completed')).toBe(true)
    expect(holla.querySelector('.project-market-wick')).toBeTruthy()
  })

  it('keeps drag and wheel zoom independent per canvas while global controls remain explicit', () => {
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
    const otherCanvas = container.querySelector('[data-project-company="Hojja"]') as HTMLElement
    const otherViewport = otherCanvas.querySelector('.project-market-viewport') as HTMLDivElement
    const otherChart = otherCanvas.querySelector('.project-market-chart') as HTMLElement
    Object.defineProperties(otherViewport, {
      scrollWidth: { value: 1200, configurable: true }, clientWidth: { value: 500, configurable: true },
      scrollHeight: { value: 1000, configurable: true }, clientHeight: { value: 420, configurable: true },
    })
    const before = chart.getAttribute('style')
    const otherBefore = otherChart.getAttribute('style')
    const scrollBy = vi.spyOn(window, 'scrollBy').mockImplementation(() => undefined)
    viewport.scrollTop = 100
    const minWheel = new WheelEvent('wheel', { deltaY: 100, bubbles: true, cancelable: true })
    act(() => { expect(viewport.dispatchEvent(minWheel)).toBe(false) })
    expect(minWheel.defaultPrevented).toBe(true)
    expect(viewport.scrollTop).toBe(200)
    expect(scrollBy).not.toHaveBeenCalled()
    viewport.scrollTop = 580
    const boundaryWheel = new WheelEvent('wheel', { deltaY: 100, bubbles: true, cancelable: true })
    act(() => { expect(viewport.dispatchEvent(boundaryWheel)).toBe(false) })
    expect(boundaryWheel.defaultPrevented).toBe(true)
    expect(viewport.scrollTop).toBe(580)
    expect(scrollBy).not.toHaveBeenCalled()
    viewport.scrollTop = 500
    const lineBoundaryWheel = new WheelEvent('wheel', { deltaY: 3, deltaMode: WheelEvent.DOM_DELTA_LINE, bubbles: true, cancelable: true })
    act(() => { viewport.dispatchEvent(lineBoundaryWheel) })
    expect(lineBoundaryWheel.defaultPrevented).toBe(true)
    expect(viewport.scrollTop).toBe(548)
    expect(scrollBy).not.toHaveBeenCalled()
    viewport.scrollLeft = 100
    const horizontalWheel = new WheelEvent('wheel', { deltaX: 100, bubbles: true, cancelable: true })
    act(() => { expect(viewport.dispatchEvent(horizontalWheel)).toBe(false) })
    expect(horizontalWheel.defaultPrevented).toBe(true)
    expect(viewport.scrollLeft).toBe(200)
    const wheel = new WheelEvent('wheel', { deltaY: -100, ctrlKey: true, bubbles: true, cancelable: true })
    act(() => { expect(viewport.dispatchEvent(wheel)).toBe(false) })
    expect(wheel.defaultPrevented).toBe(true)
    expect(chart.getAttribute('style')).not.toEqual(before)
    expect(otherChart.getAttribute('style')).toEqual(otherBefore)

    const hollaAfterLocalZoom = chart.getAttribute('style')
    fireEvent.click(screen.getByRole('button', { name: 'Perbesar semua chart' }))
    expect(chart.getAttribute('style')).not.toEqual(hollaAfterLocalZoom)
    expect(otherChart.getAttribute('style')).not.toEqual(otherBefore)
    for (let index = 0; index < 5; index += 1) fireEvent.click(screen.getByRole('button', { name: 'Perbesar semua chart' }))
    const maxWheel = new WheelEvent('wheel', { deltaY: -100, ctrlKey: true, bubbles: true, cancelable: true })
    act(() => { viewport.dispatchEvent(maxWheel) })
    expect(maxWheel.defaultPrevented).toBe(true)
    expect(scrollBy).not.toHaveBeenCalled()

    viewport.scrollTop = 0
    fireEvent.pointerDown(viewport, { pointerType: 'touch', button: 0, pointerId: 6, clientX: 180, clientY: 120 })
    fireEvent.pointerMove(viewport, { pointerType: 'touch', pointerId: 6, clientX: 180, clientY: 220 })
    fireEvent.pointerUp(viewport, { pointerType: 'touch', pointerId: 6, clientX: 180, clientY: 220 })
    expect(viewport.scrollTop).toBe(0)
    expect(scrollBy).not.toHaveBeenCalled()

    viewport.scrollLeft = 100
    viewport.scrollTop = 100
    fireEvent.pointerDown(viewport, { pointerType: 'mouse', button: 0, pointerId: 7, clientX: 200, clientY: 180 })
    fireEvent.pointerMove(viewport, { pointerType: 'mouse', pointerId: 7, clientX: 150, clientY: 130 })
    fireEvent.pointerUp(viewport, { pointerType: 'mouse', pointerId: 7, clientX: 150, clientY: 130 })
    expect(viewport.scrollLeft).toBeGreaterThan(100)
    expect(viewport.scrollTop).toBeGreaterThan(100)
    expect(otherViewport.scrollLeft).toBe(0)
    expect(otherViewport.scrollTop).toBe(0)

    const candle = canvas.querySelector('[data-project-candle="Holla Terbaru"]') as HTMLButtonElement
    const beforeCandleDrag = viewport.scrollLeft
    fireEvent.pointerDown(candle, { pointerType: 'mouse', button: 0, pointerId: 8, clientX: 220, clientY: 180 })
    fireEvent.pointerMove(viewport, { pointerType: 'mouse', pointerId: 8, clientX: 160, clientY: 180 })
    fireEvent.pointerUp(viewport, { pointerType: 'mouse', pointerId: 8, clientX: 160, clientY: 180 })
    expect(viewport.scrollLeft).toBeGreaterThan(beforeCandleDrag)
    fireEvent.click(candle, { detail: 1 })
    expect(onOpen).not.toHaveBeenCalled()

    fireEvent.pointerDown(candle, { pointerType: 'touch', pointerId: 10, clientX: 120, clientY: 120 })
    fireEvent.pointerDown(candle, { pointerType: 'touch', pointerId: 11, clientX: 220, clientY: 120 })
    fireEvent.pointerMove(viewport, { pointerType: 'touch', pointerId: 11, clientX: 250, clientY: 120 })
    fireEvent.pointerUp(viewport, { pointerType: 'touch', pointerId: 11, clientX: 250, clientY: 120 })
    fireEvent.pointerUp(viewport, { pointerType: 'touch', pointerId: 10, clientX: 120, clientY: 120 })
    fireEvent.click(candle, { detail: 1 })
    expect(onOpen).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: 'Kembali ke proyek terbaru Holla' }))
    expect(viewport.scrollLeft).toBe(700)
    const cancelFrame = vi.spyOn(window, 'cancelAnimationFrame')
    const scheduleFrame = vi.spyOn(window, 'requestAnimationFrame').mockReturnValue(91)
    viewport.scrollLeft = 100
    viewport.scrollTop = 100
    fireEvent.pointerDown(viewport, { pointerType: 'mouse', button: 0, pointerId: 9, clientX: 200, clientY: 180 })
    fireEvent.pointerMove(viewport, { pointerType: 'mouse', pointerId: 9, clientX: 120, clientY: 110 })
    fireEvent.pointerUp(viewport, { pointerType: 'mouse', pointerId: 9, clientX: 120, clientY: 110 })
    fireEvent.click(screen.getByRole('button', { name: 'Reset tampilan semua chart' }))
    expect(cancelFrame).toHaveBeenCalledWith(91)
    expect(viewport.scrollTop).toBe(0)
    scheduleFrame.mockRestore()
    cancelFrame.mockRestore()
    scrollBy.mockRestore()
    fireEvent.click(candle)
    expect(onOpen).toHaveBeenCalledWith(projects[1])
  })
})
