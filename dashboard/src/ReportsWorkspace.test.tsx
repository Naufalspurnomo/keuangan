import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { seedDemoFinanceWorkspace } from './demoFinanceFixtures'
import ReportsWorkspace from './ReportsWorkspace'


describe('canonical report center', () => {
  it('offers every required report dataset and switches the preview table', () => {
    render(<ReportsWorkspace workspace={seedDemoFinanceWorkspace()} />)

    const reportType = screen.getByRole('combobox', { name: 'Jenis laporan' })
    expect(screen.getAllByRole('option').filter((option) => option.closest('select') === reportType)).toHaveLength(7)

    fireEvent.change(reportType, { target: { value: 'debt-aging' } })
    expect(screen.getByRole('heading', { name: 'Aging Hutang' })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'Outstanding' })).toBeInTheDocument()
  })

  it('shows canonical authority metadata in live mode', () => {
    const workspace = seedDemoFinanceWorkspace()
    workspace.mode = 'live'
    workspace.live_source = 'Hollawall PostgreSQL canonical ledger'
    workspace.live_data_through = '2026-11-12T10:00:00+00:00'

    render(<ReportsWorkspace workspace={workspace} />)

    expect(screen.getByText('Hollawall PostgreSQL canonical ledger')).toBeInTheDocument()
    expect(screen.getByText(/Data sampai 12 Nov 2026/)).toBeInTheDocument()
  })
})
