import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import ReportsWorkspace, { exportReportPdf } from './ReportsWorkspace'
import { seedDemoFinanceWorkspace } from './demoFinanceFixtures'
import { buildCanonicalReportDataset } from './canonicalReports'
import { buildReportModel, defaultReportFilters } from './financeView'

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals() })
function downloads() {
  vi.stubGlobal('URL', { createObjectURL: vi.fn(() => 'blob:test'), revokeObjectURL: vi.fn() })
  return vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
}
it('downloads only one PDF by default', async () => {
  const click = downloads()
  const workspace = seedDemoFinanceWorkspace()
  const dataset = buildCanonicalReportDataset(workspace, buildReportModel(workspace, defaultReportFilters(workspace)), 'cashflow')
  const result = await exportReportPdf(dataset)
  expect(click).toHaveBeenCalledTimes(1)
  expect(result.artifactHash).toHaveLength(64)
})
it('clears scoped export feedback after a filter change', () => {
  downloads()
  render(<ReportsWorkspace workspace={seedDemoFinanceWorkspace()} />)
  fireEvent.click(screen.getByRole('button', { name: 'Ekspor CSV' }))
  expect(screen.getByRole('status')).toBeTruthy()
  fireEvent.change(screen.getByLabelText('Dari tanggal'), { target: { value: '2026-01-01' } })
  expect(screen.queryByRole('status')).toBeNull()
})
it('clears export errors when the report or workspace changes', () => {
  downloads().mockImplementation(() => { throw new Error('Download blocked') })
  const workspace = seedDemoFinanceWorkspace()
  const { rerender } = render(<ReportsWorkspace workspace={workspace} />)
  fireEvent.click(screen.getByRole('button', { name: 'Ekspor CSV' }))
  expect(screen.getByRole('alert')).toHaveTextContent('CSV belum dapat dibuat')
  fireEvent.change(screen.getByLabelText('Jenis laporan'), { target: { value: 'debt-aging' } })
  expect(screen.queryByRole('alert')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: 'Ekspor CSV' }))
  expect(screen.getByRole('alert')).toBeTruthy()
  rerender(<ReportsWorkspace workspace={{ ...workspace, mode: 'live' }} />)
  expect(screen.queryByRole('alert')).toBeNull()
})
it('guards PDF reentry and does not show stale completion after scope changes', async () => {
  const click = downloads()
  render(<ReportsWorkspace workspace={seedDemoFinanceWorkspace()} />)
  const button = screen.getByRole('button', { name: 'Ekspor PDF' })
  act(() => { button.click(); button.click() })
  fireEvent.change(screen.getByLabelText('Dari tanggal'), { target: { value: '2026-01-01' } })
  await waitFor(() => expect(button).not.toBeDisabled(), { timeout: 10000 })
  expect(click).toHaveBeenCalledTimes(1)
  expect(screen.queryByRole('status')).toBeNull()
})
