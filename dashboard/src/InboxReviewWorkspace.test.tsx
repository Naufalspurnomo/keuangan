import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { InboxReviewWorkspace } from './InboxReviewWorkspace'
import type { InboxReviewApi, InboxReviewCommand, InboxReviewDetail, InboxReviewList } from './inboxReviewApi'

const EVENT_KEY = 'a'.repeat(64)
const item = {
  eventKey: EVENT_KEY,
  provider: 'wuzapi',
  messageId: 'message-1',
  eventType: 'image',
  isGroup: false,
  financeSignal: true,
  payloadScore: 9,
  status: 'needs_review_notified',
  resultStatus: 'ignored_finance_signal',
  attempts: 2,
  receivedAt: '2026-11-09T10:00:00Z',
  updatedAt: '2026-11-09T10:05:00Z',
}
const detail: InboxReviewDetail = {
  ...item,
  bodyText: '<img src=x onerror=alert(1)> Transfer Rp100.000',
  quotedMessageId: 'quote-1',
  mediaAvailable: true,
}

function api(list: InboxReviewList, submit = vi.fn().mockResolvedValue({
  eventKey: EVENT_KEY, messageId: 'message-1', action: 'ignore', status: 'ignored',
})) {
  const command: InboxReviewCommand = {
    idempotencyKey: 'review-command-0001',
    payload: Object.freeze({ action: 'ignore', reason: 'Bukan transaksi', expected_status: 'needs_review_notified' }),
    submit,
  }
  return {
    list: vi.fn().mockResolvedValue(list),
    detail: vi.fn().mockResolvedValue(detail),
    command: vi.fn(() => command),
  } satisfies InboxReviewApi
}

function page(items = [item], overrides: Partial<InboxReviewList> = {}): InboxReviewList {
  return {
    items,
    writesEnabled: true,
    allowedActions: ['ignore', 'confirm_processed'],
    total: items.length,
    offset: 0,
    limit: 25,
    hasMore: false,
    ...overrides,
  }
}

afterEach(() => cleanup())

describe('Perlu Ditinjau workspace', () => {
  it('shows a plain-language list and safe text detail without rendering raw HTML', async () => {
    const reviewApi = api(page([item], { writesEnabled: false, allowedActions: [] }))
    const { container } = render(<InboxReviewWorkspace api={reviewApi} csrfToken="owner-csrf-token" />)

    expect(await screen.findByRole('heading', { name: 'Perlu Ditinjau' })).toBeTruthy()
    expect(screen.getByText('message-1')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: /Tinjau message-1/i }))

    expect(await screen.findByText('<img src=x onerror=alert(1)> Transfer Rp100.000')).toBeTruthy()
    expect(container.querySelector('img')).toBeNull()
    expect(screen.getByText(/Perubahan dinonaktifkan/i)).toBeTruthy()
    expect(screen.queryByRole('button', { name: /Abaikan|Sudah diproses|Coba lagi/i })).toBeNull()
  })

  it('shows terminal actions only when locally and upstream-enabled, requiring reason and explicit confirmation', async () => {
    const submit = vi.fn().mockResolvedValue({ eventKey: EVENT_KEY, messageId: 'message-1', action: 'ignore', status: 'ignored' })
    const reviewApi = api(page(), submit)
    render(<InboxReviewWorkspace api={reviewApi} csrfToken="owner-csrf-token" />)
    fireEvent.click(await screen.findByRole('button', { name: /Tinjau message-1/i }))

    const ignore = await screen.findByRole('button', { name: 'Abaikan permanen' })
    expect(ignore).toBeDisabled()
    fireEvent.change(screen.getByLabelText('Alasan keputusan'), { target: { value: 'Bukan transaksi' } })
    expect(ignore).not.toBeDisabled()
    fireEvent.click(ignore)

    const dialog = screen.getByRole('dialog', { name: 'Konfirmasi keputusan' })
    expect(within(dialog).getByText(/tidak dapat dibatalkan/i)).toBeTruthy()
    expect(submit).not.toHaveBeenCalled()
    fireEvent.click(within(dialog).getByRole('button', { name: 'Ya, abaikan permanen' }))

    await waitFor(() => expect(submit).toHaveBeenCalledWith({ csrfToken: 'owner-csrf-token' }))
    expect(reviewApi.command).toHaveBeenCalledWith({
      eventKey: EVENT_KEY,
      action: 'ignore',
      reason: 'Bukan transaksi',
      expectedStatus: 'needs_review_notified',
    })
    expect(await screen.findByRole('status')).toHaveTextContent('Keputusan tersimpan.')
    expect(screen.queryByRole('button', { name: /Coba lagi/i })).toBeNull()
  })

  it('keeps the same command after an uncertain result but gives no retry control', async () => {
    const error = Object.assign(new Error('unknown'), { code: 'review_outcome_unknown', uncertain: true, status: undefined })
    const submit = vi.fn().mockRejectedValue(error)
    const reviewApi = api(page([item], { allowedActions: ['ignore'] }), submit)
    render(<InboxReviewWorkspace api={reviewApi} csrfToken="owner-csrf-token" />)
    fireEvent.click(await screen.findByRole('button', { name: /Tinjau message-1/i }))
    fireEvent.change(await screen.findByLabelText('Alasan keputusan'), { target: { value: 'Bukan transaksi' } })
    fireEvent.click(screen.getByRole('button', { name: 'Abaikan permanen' }))
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Ya, abaikan permanen' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/belum dapat dipastikan/i)
    expect(reviewApi.command).toHaveBeenCalledTimes(1)
    expect(screen.queryByRole('button', { name: /Coba lagi/i })).toBeNull()
  })

  it('maps conflict and ledger service failures for the owner', async () => {
    const submit = vi.fn().mockRejectedValue(Object.assign(new Error('server'), {
      code: 'review_conflict', status: 409, uncertain: false,
    }))
    const reviewApi = api(page([item], { allowedActions: ['confirm_processed'] }), submit)
    render(<InboxReviewWorkspace api={reviewApi} csrfToken="owner-csrf-token" />)
    fireEvent.click(await screen.findByRole('button', { name: /Tinjau message-1/i }))
    fireEvent.change(await screen.findByLabelText('Alasan keputusan'), { target: { value: 'Sudah masuk ledger' } })
    fireEvent.click(screen.getByRole('button', { name: 'Tandai sudah diproses' }))
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Ya, tandai sudah diproses' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/sudah berubah/i)
  })

  it('navigates all review pages and reports the authoritative total', async () => {
    const first = page([item], { total: 76, offset: 0, hasMore: true })
    const secondItem = { ...item, eventKey: 'b'.repeat(64), messageId: 'message-26' }
    const second = page([secondItem], { total: 76, offset: 25, hasMore: true })
    const reviewApi = api(first)
    reviewApi.list.mockResolvedValueOnce(first).mockResolvedValueOnce(second)

    render(<InboxReviewWorkspace api={reviewApi} csrfToken="owner-csrf-token" />)
    expect(await screen.findByText('1–1 dari 76')).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: 'Halaman berikutnya' }))

    expect(await screen.findByText('message-26')).toBeTruthy()
    expect(screen.getByText('26–26 dari 76')).toBeTruthy()
    expect(reviewApi.list).toHaveBeenLastCalledWith({ offset: 25, limit: 25 })
    fireEvent.click(screen.getByRole('button', { name: 'Halaman sebelumnya' }))
    expect(reviewApi.list).toHaveBeenLastCalledWith({ offset: 0, limit: 25 })
  })
})
