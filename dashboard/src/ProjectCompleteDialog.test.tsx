import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import ProjectCompleteDialog from './ProjectCompleteDialog'
import { seedFinanceWorkspace } from './financeWorkspace'

afterEach(() => { cleanup(); vi.useRealTimers() })

describe('ProjectCompleteDialog', () => {
  it('defaults to today, enforces project start, and preserves project fields', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-10-30T08:00:00Z'))
    const project = seedFinanceWorkspace().projects.find((item) => item.status === 'active')!
    const onSave = vi.fn()
    render(<ProjectCompleteDialog project={project} onSave={onSave} onClose={vi.fn()} />)

    expect(screen.getByRole('heading', { name: `Selesaikan ${project.name}` })).toBeTruthy()
    const date = screen.getByLabelText('Tanggal selesai *') as HTMLInputElement
    expect(date.value).toBe('2026-10-30')
    expect(date.min).toBe(project.started_on)
    fireEvent.change(date, { target: { value: '2026-10-29' } })
    fireEvent.click(screen.getByRole('button', { name: 'Selesaikan proyek' }))

    expect(onSave).toHaveBeenCalledWith({
      name: project.name,
      company: project.company,
      status: 'completed',
      started_on: project.started_on,
      completed_on: '2026-10-29',
      client: project.client,
      contract_value: project.contract_value,
      notes: project.notes,
    })
  })

  it('keeps the dialog open and reports an invalid completion date', () => {
    const project = { ...seedFinanceWorkspace().projects.find((item) => item.status === 'active')!, started_on: '2026-10-20' }
    const onSave = vi.fn()
    render(<ProjectCompleteDialog project={project} onSave={onSave} onClose={vi.fn()} />)
    fireEvent.change(screen.getByLabelText('Tanggal selesai *'), { target: { value: '2026-10-19' } })
    fireEvent.submit(screen.getByRole('button', { name: 'Selesaikan proyek' }).closest('form')!)

    expect(onSave).not.toHaveBeenCalled()
    expect(screen.getByRole('alert').textContent).toContain('Tanggal selesai tidak boleh sebelum tanggal mulai')
    expect(screen.getByRole('dialog')).toBeTruthy()
  })
})
