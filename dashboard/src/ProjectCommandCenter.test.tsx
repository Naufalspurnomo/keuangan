import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'

import ProjectCommandCenter from './ProjectCommandCenter'
import { seedFinanceWorkspace } from './financeWorkspace'

let resizeCallback: ResizeObserverCallback

beforeEach(() => {
  vi.stubGlobal('ResizeObserver', class {
    constructor(callback: ResizeObserverCallback) { resizeCallback = callback }
    observe() {}
    disconnect() {}
  })
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
  it('reveals the active year inside its horizontal rail without scrolling the page', () => {
    render(<ProjectCommandCenter
      workspace={seedFinanceWorkspace()}
      onAdd={vi.fn()}
      onEdit={vi.fn()}
      onComplete={vi.fn()}
      onQuickComplete={vi.fn()}
      onDelete={vi.fn()}
      onOpen={vi.fn()}
    />)

    const activeYear = screen.getByRole('button', { current: 'page' })
    const rail = activeYear.closest('nav') as HTMLElement
    Object.defineProperties(rail, {
      clientWidth: { configurable: true, value: 200 },
      scrollLeft: { configurable: true, writable: true, value: 0 },
    })
    Object.defineProperties(activeYear, {
      offsetLeft: { configurable: true, value: 420 },
      offsetWidth: { configurable: true, value: 120 },
    })
    Object.defineProperty(window, 'scrollY', { configurable: true, value: 1600 })

    resizeCallback([], {} as ResizeObserver)

    expect(window.scrollY).toBe(1600)
    expect(rail.scrollLeft).toBe(340)
    expect(Element.prototype.scrollIntoView).not.toHaveBeenCalled()
  })
})
