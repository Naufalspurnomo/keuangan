import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'

import ProjectCommandCenter from './ProjectCommandCenter'
import { seedFinanceWorkspace } from './financeWorkspace'

beforeEach(() => {
  Object.defineProperty(Element.prototype, 'scrollIntoView', {
    configurable: true,
    value: vi.fn(() => { Object.defineProperty(window, 'scrollY', { configurable: true, value: 0 }) }),
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  Reflect.deleteProperty(Element.prototype, 'scrollIntoView')
})

describe('ProjectCommandCenter scroll stability', () => {
  it('locks project completion actions and announces progress while status is pending', () => {
    render(<ProjectCommandCenter
      workspace={seedFinanceWorkspace()}
      onAdd={vi.fn()}
      onEdit={vi.fn()}
      onComplete={vi.fn()}
      onQuickComplete={vi.fn()}
      onDelete={vi.fn()}
      onOpen={vi.fn()}
      busy
    />)

    expect(screen.getByRole('status').textContent).toContain('Menyelesaikan Project')
    for (const button of screen.getAllByRole('button', { name: /^Selesaikan / })) expect((button as HTMLButtonElement).disabled).toBe(true)
  })

  it('selects the project year in a compact control without scrolling the page', () => {
    render(<ProjectCommandCenter
      workspace={seedFinanceWorkspace()}
      onAdd={vi.fn()}
      onEdit={vi.fn()}
      onComplete={vi.fn()}
      onQuickComplete={vi.fn()}
      onDelete={vi.fn()}
      onOpen={vi.fn()}
    />)

    const selector = screen.getByRole('combobox', { name: 'Project per tahun' })
    Object.defineProperty(window, 'scrollY', { configurable: true, value: 1600 })
    const nextYear = [...(selector as HTMLSelectElement).options].find((option) => option.value !== (selector as HTMLSelectElement).value)!
    fireEvent.change(selector, { target: { value: nextYear.value } })

    expect(window.scrollY).toBe(1600)
    expect(selector).toHaveValue(nextYear.value)
    expect(Element.prototype.scrollIntoView).not.toHaveBeenCalled()
  })
})
