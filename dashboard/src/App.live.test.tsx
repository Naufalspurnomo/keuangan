import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'

import App from './App'
import { validLiveSnapshot } from './liveSnapshot.test'

const PROJECT_ALFA_ID = '00000000-0000-4000-8000-000000000101'
const PROJECT_BETA_ID = '00000000-0000-4000-8000-000000000102'

const liveSnapshot = (): import('./snapshot').DashboardSnapshot => ({
  ...validLiveSnapshot(),
  meta: {
    ...validLiveSnapshot().meta,
    as_of: '2026-11-02T09:30:00Z',
    data_through: '2026-11-01',
  },
  wallets: [
    { source_key: 'wallet-live-1', name: 'Dompet Produksi Utama', balance: 12_500_000 },
    { source_key: 'wallet-live-2', name: 'Dompet Produksi Bali', balance: 2_500_000 },
    { source_key: 'wallet-live-3', name: 'Dompet Tak Terpetakan', balance: 750_000 },
  ],
  project_summaries: [
    { name: 'Proyek Produksi Alfa', project_id: PROJECT_ALFA_ID, portfolio: 'Hollawall' as const, net_cashflow: 9_000_000, transaction_count: 1, lifecycle_status: 'active' as const, started_on: '2026-10-01' },
    { name: 'Proyek Produksi Beta', project_id: PROJECT_BETA_ID, portfolio: 'Texturin' as const, net_cashflow: -1_500_000, transaction_count: 1, lifecycle_status: 'completed' as const, started_on: '2026-09-01', completed_on: '2026-10-31' },
  ],
  transactions: [
    {
      id: 981,
      source_key: 'tx-live-981',
      transaction_date: '2026-11-01',
      transaction_type: 'Pemasukan',
      amount: 9_000_000,
      wallet: 'Dompet Produksi Utama',
      company: 'Holla',
      project: 'Proyek Produksi Alfa',
      project_id: PROJECT_ALFA_ID,
      scope: 'project',
      notes: 'Pembayaran produksi aktual',
    },
    {
      id: 982,
      source_key: 'tx-live-982',
      transaction_date: '2026-10-31',
      transaction_type: 'Pengeluaran',
      amount: 1_500_000,
      wallet: 'Dompet Produksi Bali',
      company: 'Texturin Regional Baru',
      project: 'Proyek Produksi Beta',
      project_id: PROJECT_BETA_ID,
      scope: 'project',
      notes: 'Material produksi aktual',
    },
    {
      id: 983,
      source_key: 'tx-live-983',
      transaction_date: '2026-10-30',
      transaction_type: 'Pengeluaran',
      amount: 250_000,
      wallet: 'Dompet Tak Terpetakan',
      company: 'Unit Operasional Baru',
      project: 'Operasional',
      scope: 'office',
      office_category: 'Kategori Produksi Khusus',
      notes: 'Biaya kategori aktual',
    },
  ],
  debts: [{
    source_key: 'debt-live-1', date: '2026-10-20', amount: 500_000, notes: 'Pinjaman aktual',
    borrower: 'Dompet Tak Terpetakan', lender: 'Dompet Produksi Utama', status: 'OPEN',
  }],
  cash_trend: [
    { month: '2026-10', balance: 6_750_000, net_movement: -1_750_000 },
    { month: '2026-11', balance: 15_750_000, net_movement: 9_000_000 },
  ],
})

function liveResponse(snapshot = liveSnapshot()) {
  return new Response(JSON.stringify(snapshot), { status: 200, headers: { 'content-type': 'application/json' } })
}

function productionProjectsResponse(transactionLifecycle = false, wallet = 'CV HB(101)') {
  const company = wallet === 'TX SBY(216)' ? 'TEXTURIN-Surabaya'
    : wallet === 'TX BALI(087)' ? 'TEXTURIN-Bali'
      : 'HOLLA'
  return new Response(JSON.stringify({
    api_version: 'dashboard.v1',
    data: {
      items: [{
        id: '123e4567-e89b-42d3-a456-426614174000',
        name: 'Kontrak Panggung Utama',
        client_name: 'PT Klien Produksi',
        client_company: 'PT Klien Produksi',
        client_address: 'Surabaya',
        client_contact: 'Operasional',
        issuer_key: 'cv-holla-berkreasi',
        status: 'active',
        start_date: '2026-11-01',
        completion_date: null,
        contract_notes: '',
        wallet,
        company,
        lock_version: 1,
        archived_at: null,
        created_at: '2026-11-01T00:00:00Z',
        updated_at: '2026-11-01T00:00:00Z',
      }],
    },
    meta: { capabilities: { project_document_writes_enabled: false, transaction_correction_reversal: transactionLifecycle } },
  }), { status: 200, headers: { 'content-type': 'application/json' } })
}

function writableProductionProjectsResponse() {
  const response = productionProjectsResponse()
  return response.json().then((body) => new Response(JSON.stringify({
    ...body,
    meta: { capabilities: { project_document_writes_enabled: true, transaction_correction_reversal: false } },
  }), { status: 200, headers: { 'content-type': 'application/json' } }))
}

function writeSessionResponse(canonicalFinanceWrites = true, writesEnabled = true, debtWritesEnabled = false) {
  return new Response(JSON.stringify({
    api_version: 'dashboard.v1',
    data: {
      csrf_token: 'csrf-token-1234567890',
      capabilities: {
        writes_enabled: writesEnabled,
        canonical_finance_writes_enabled: canonicalFinanceWrites,
        canonical_debt_writes_enabled: debtWritesEnabled,
      },
    },
  }), { status: 200, headers: { 'content-type': 'application/json' } })
}

function canonicalMutationResponse(action: 'correction' | 'reversal') {
  return new Response(JSON.stringify({
    api_version: 'finance.v1',
    data: {
      transaction: {
        id: action === 'correction'
          ? '00000000-0000-4000-8000-000000000212'
          : '00000000-0000-4000-8000-000000000213',
        version: 2,
        status: action,
        amount: 300_000,
      },
      duplicate: false,
    },
  }), { status: 201, headers: { 'content-type': 'application/json' } })
}

function recordedTransactionResponse() {
  return new Response(JSON.stringify({
    api_version: 'dashboard.v1',
    data: {
      recorded: true,
      authority: 'postgresql',
      transaction_id: '00000000-0000-4000-8000-000000000601',
      transaction_version: 1,
      duplicate: false,
    },
  }), { status: 201, headers: { 'content-type': 'application/json' } })
}

const forbiddenProductionCopy = /DATA LIVE|Workspace live|Mode live|PostgreSQL|buku besar produksi|pemetaan kanonis|snapshot live|kontrak snapshot|ID proyek PostgreSQL/i

function expectNoProductionChatter() {
  expect(document.body.textContent).not.toMatch(forbiddenProductionCopy)
}

function navigation() {
  return within(document.querySelector('aside.sidebar') as HTMLElement)
}

beforeEach(() => {
  localStorage.clear()
  sessionStorage.clear()
  window.history.replaceState(null, '', '/admin/')
  vi.stubGlobal('matchMedia', vi.fn().mockReturnValue({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() }))
  vi.spyOn(window, 'scrollTo').mockImplementation(() => undefined)
})

afterEach(() => {
  cleanup()
  vi.useRealTimers()
  localStorage.clear()
  sessionStorage.clear()
  window.history.replaceState(null, '', '/')
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('production live source mode', () => {
  it('opens the single canonical production project form from the live project add control', async () => {
    const request = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url === '/admin/api/write-session.php') return writeSessionResponse(false, false)
      if (url.startsWith('/admin/api/projects.php?action=list')) return writableProductionProjectsResponse()
      return liveResponse()
    })
    vi.stubGlobal('fetch', request)
    render(<App />)
    await screen.findByRole('heading', { name: 'Pusat kendali keuangan Hollawall' })

    fireEvent.click(await screen.findByRole('button', { name: 'Tambah proyek' }))

    expect(screen.getByRole('dialog', { name: 'Buat proyek' })).toBeInTheDocument()
    expect(screen.getByLabelText('Dompet pencatatan')).toHaveValue('CV HB(101)')
  })

  it('does not expose transaction creation for a legacy-only write session', async () => {
    const request = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url === '/admin/api/write-session.php') return writeSessionResponse(false, true)
      if (url.startsWith('/admin/api/projects.php?action=list')) return productionProjectsResponse()
      return liveResponse()
    })
    vi.stubGlobal('fetch', request)
    render(<App />)
    await screen.findByRole('heading', { name: 'Pusat kendali keuangan Hollawall' })

    fireEvent.click(navigation().getByRole('button', { name: 'Proyek' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Buka proyek Kontrak Panggung Utama' }))

    expect(screen.queryByRole('button', { name: 'Tambah transaksi' })).toBeNull()
  })

  it.each(['CV HB(101)', 'TX SBY(216)', 'TX BALI(087)'])('preserves canonical project wallet %s in the Hutang shortcut', async (wallet) => {
    const request = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url === '/admin/api/write-session.php') return writeSessionResponse(true, false, true)
      if (url.startsWith('/admin/api/projects.php?action=list')) return productionProjectsResponse(false, wallet)
      return liveResponse()
    })
    vi.stubGlobal('fetch', request)
    render(<App />)
    await screen.findByRole('heading', { name: 'Pusat kendali keuangan Hollawall' })

    fireEvent.click(navigation().getByRole('button', { name: 'Proyek' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Buka proyek Kontrak Panggung Utama' }))
    fireEvent.click(screen.getByRole('tab', { name: 'Pinjaman' }))
    fireEvent.click(screen.getByRole('button', { name: 'Buka Hutang' }))

    expect(screen.getByLabelText('Dompet peminjam')).toHaveValue(wallet)
  })

  it('opens the review queue from the dashboard', async () => {
    const request = vi.fn(async (input: RequestInfo | URL) => String(input).includes('write-session')
      ? writeSessionResponse(false)
      : String(input).includes('/projects') ? productionProjectsResponse() : liveResponse())
    vi.stubGlobal('fetch', request)
    render(<App />)

    fireEvent.click(await screen.findByRole('button', { name: 'Perlu ditinjau' }))

    expect(window.location.hash).toBe('#inbox-reviews')
    expect(await screen.findByRole('heading', { name: 'Perlu Ditinjau' })).toBeInTheDocument()
  })
  it('renders PostgreSQL projects and routes the live detail workspace by UUID', async () => {
    const request = vi.fn(async (input: RequestInfo | URL) => String(input).startsWith('/admin/api/projects.php?action=list')
      ? productionProjectsResponse()
      : liveResponse())
    vi.stubGlobal('fetch', request)

    render(<App />)
    await screen.findByRole('heading', { name: 'Pusat kendali keuangan Hollawall' })
    fireEvent.click(navigation().getByRole('button', { name: 'Proyek' }))

    fireEvent.click(await screen.findByRole('button', { name: 'Buka proyek Kontrak Panggung Utama' }))
    expect(screen.queryByText('123e4567-e89b-42d3-a456-426614174000')).toBeNull()
    expect(screen.getByRole('tab', { name: 'Transaksi' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('tab', { name: 'Dokumen' })).toBeTruthy()
    expect(window.location.hash).toContain('project=123e4567-e89b-42d3-a456-426614174000')
    expect(request).toHaveBeenCalledWith('/admin/api/projects.php?action=list', expect.objectContaining({ credentials: 'same-origin' }))
  }, 30_000)

  it('posts the first transaction for a PostgreSQL project using its UUID', async () => {
    let postedBody: Record<string, unknown> | undefined
    const request = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url === '/admin/api/write-session.php') return writeSessionResponse()
      if (url === '/admin/api/transactions.php') {
        postedBody = JSON.parse(String(init?.body)) as Record<string, unknown>
        return recordedTransactionResponse()
      }
      if (url.startsWith('/admin/api/projects.php?action=list')) return productionProjectsResponse()
      return liveResponse()
    })
    vi.stubGlobal('fetch', request)
    render(<App />)
    await screen.findByRole('heading', { name: 'Pusat kendali keuangan Hollawall' })

    fireEvent.click(navigation().getByRole('button', { name: 'Proyek' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Buka proyek Kontrak Panggung Utama' }))
    fireEvent.click(screen.getByRole('button', { name: 'Tambah transaksi' }))
    const dialog = screen.getByRole('dialog')
    expect(within(dialog).queryByLabelText('Proyek *')).toBeNull()
    expect(within(dialog).getByLabelText('Dompet proyek')).toHaveValue('CV HB(101)')
    expect(within(dialog).getByLabelText('Unit usaha proyek')).toHaveValue('HOLLA')
    fireEvent.change(within(dialog).getByLabelText('Jumlah *'), { target: { value: '500000' } })
    fireEvent.change(within(dialog).getByLabelText('Keterangan *'), { target: { value: 'Biaya proyek pertama' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Simpan transaksi' }))
    await act(async () => { await Promise.resolve(); await Promise.resolve(); await Promise.resolve() })

    expect(postedBody).toMatchObject({
      project: '123e4567-e89b-42d3-a456-426614174000',
      wallet: 'CV HB(101)',
      company: 'HOLLA',
    })
  }, 30_000)

  it('creates an active production project and opens its transaction workspace', async () => {
    const createdId = '223e4567-e89b-42d3-a456-426614174001'
    const created = {
      id: createdId,
      name: 'Proyek Online Baru',
      client_name: 'Klien Online',
      client_company: '', client_address: '', client_contact: '',
      issuer_key: 'hollawall', wallet: 'TX SBY(216)', company: 'TEXTURIN-Surabaya',
      status: 'active', start_date: '2026-11-11', completion_date: null, contract_notes: '',
      lock_version: 1, archived_at: null, created_at: '2026-11-11T00:00:00Z', updated_at: '2026-11-11T00:00:00Z',
    }
    let createBody: Record<string, unknown> | undefined
    const request = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url === '/admin/api/write-session.php') return writeSessionResponse()
      if (url.startsWith('/admin/api/projects.php?action=list')) return writableProductionProjectsResponse()
      if (url === `/admin/api/projects.php?action=get&project_id=${createdId}`) {
        return new Response(JSON.stringify({ api_version: 'dashboard.v1', data: created, meta: { capabilities: { project_document_writes_enabled: true } } }), { status: 200, headers: { 'content-type': 'application/json' } })
      }
      if (url === '/admin/api/projects.php' && init?.method === 'POST') {
        createBody = JSON.parse(String(init.body)) as Record<string, unknown>
        return new Response(JSON.stringify({ api_version: 'dashboard.v1', data: { project: created }, meta: { capabilities: { project_document_writes_enabled: true } } }), { status: 201, headers: { 'content-type': 'application/json' } })
      }
      return liveResponse()
    })
    vi.stubGlobal('fetch', request)
    render(<App />)
    await screen.findByRole('heading', { name: 'Pusat kendali keuangan Hollawall' })

    fireEvent.click(navigation().getByRole('button', { name: 'Proyek' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Buat proyek' }))
    fireEvent.change(screen.getByLabelText('Nama proyek'), { target: { value: created.name } })
    fireEvent.change(screen.getByLabelText('Nama klien'), { target: { value: created.client_name } })
    fireEvent.change(screen.getByLabelText('Dompet pencatatan'), { target: { value: 'TX SBY(216)' } })
    expect(screen.getByLabelText('Unit usaha')).toHaveValue('TEXTURIN-Surabaya')
    expect(screen.queryByRole('option', { name: 'TX SBY' })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Simpan proyek' }))

    await screen.findByRole('heading', { name: created.name })
    expect(window.location.hash).toBe(`#projects?project=${createdId}&tab=transactions`)
    expect(screen.getByRole('tab', { name: 'Transaksi' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('button', { name: 'Tambah transaksi' })).toBeTruthy()
    expect(screen.getByRole('status').textContent).toBe('Proyek aktif dibuat. Lanjutkan dengan mencatat transaksi proyek.')
    expect(createBody).toMatchObject({ action: 'create', values: { name: created.name, wallet: 'TX SBY(216)', company: 'TEXTURIN-Surabaya', status: 'active' } })
  }, 30_000)

  it('gates and persists canonical correction and reversal before authoritative refresh', async () => {
    const snapshot = liveSnapshot()
    const canonicalId = '00000000-0000-4000-8000-000000000210'
    snapshot.transactions[2] = {
      ...snapshot.transactions[2],
      canonical_transaction_id: canonicalId,
      transaction_version: 1,
    }
    const mutations: Array<{ url: string; body: Record<string, unknown>; headers: Headers }> = []
    let snapshotReads = 0
    const request = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url === '/admin/api/write-session.php') return writeSessionResponse(true)
      if (url.startsWith('/admin/api/transactions.php?action=')) {
        const body = JSON.parse(String(init?.body)) as Record<string, unknown>
        mutations.push({ url, body, headers: new Headers(init?.headers) })
        return canonicalMutationResponse(url.includes('action=correction') ? 'correction' : 'reversal')
      }
      if (url.startsWith('/admin/api/projects.php?action=list')) return productionProjectsResponse(true)
      snapshotReads += 1
      return liveResponse(snapshot)
    })
    vi.stubGlobal('fetch', request)
    vi.spyOn(window, 'prompt')
      .mockReturnValueOnce('300000')
      .mockReturnValueOnce('Nominal vendor terkoreksi')
      .mockReturnValueOnce('Transaksi dibatalkan vendor')
    vi.spyOn(window, 'confirm').mockReturnValue(true)

    render(<App />)
    await screen.findByRole('heading', { name: 'Pusat kendali keuangan Hollawall' })
    fireEvent.click(navigation().getByRole('button', { name: 'Operasional Kantor' }))

    fireEvent.click(await screen.findByRole('button', { name: 'Koreksi transaksi Biaya kategori aktual' }))
    await screen.findByText('Koreksi tercatat dan data diperbarui.')
    fireEvent.click(screen.getByRole('button', { name: 'Balik transaksi Biaya kategori aktual' }))
    await screen.findByText('Pembalikan tercatat dan data diperbarui.')

    expect(mutations).toHaveLength(2)
    expect(mutations[0].url).toBe(`/admin/api/transactions.php?action=correction&transaction_id=${canonicalId}`)
    expect(mutations[0].body).toMatchObject({ expected_version: 1, amount: 300_000, reason: 'Nominal vendor terkoreksi' })
    expect(mutations[1].url).toBe(`/admin/api/transactions.php?action=reversal&transaction_id=${canonicalId}`)
    expect(mutations[1].body).toMatchObject({ expected_version: 1, reason: 'Transaksi dibatalkan vendor' })
    expect(mutations[0].headers.get('X-CSRF-Token')).toBe('csrf-token-1234567890')
    const correctionKey = mutations[0].headers.get('Idempotency-Key')
    const reversalKey = mutations[1].headers.get('Idempotency-Key')
    expect(correctionKey).toMatch(/^\S{16,128}$/)
    expect(reversalKey).toMatch(/^\S{16,128}$/)
    expect(correctionKey).toBe(mutations[0].body.idempotency_key)
    expect(reversalKey).toBe(mutations[1].body.idempotency_key)
    expect(correctionKey).not.toBe(reversalKey)
    expect(snapshotReads).toBeGreaterThanOrEqual(3)
  })

  it('keeps the complete dashboard shell, analytics, routes, reports, and source-grounded unknown values', async () => {
    const request = vi.fn(async (_input?: RequestInfo | URL) => liveResponse())
    vi.stubGlobal('fetch', request)

    render(<App />)

    expect(await screen.findByRole('heading', { name: 'Pusat kendali keuangan Hollawall' })).toBeTruthy()
    expect(document.querySelector('.app-shell.finance-workspace-shell')).toBeTruthy()
    expect(navigation().getByRole('button', { name: 'Dashboard' })).toBeTruthy()
    expect(navigation().getByRole('button', { name: 'Arus Kas' })).toBeTruthy()
    expect(navigation().getByRole('button', { name: 'Dompet' })).toBeTruthy()
    expect(navigation().getByRole('button', { name: 'Proyek' })).toBeTruthy()
    expect(navigation().getByRole('button', { name: 'Operasional Kantor' })).toBeTruthy()
    expect(navigation().getByRole('button', { name: 'Hutang' })).toBeTruthy()
    expect(navigation().getByRole('button', { name: 'Laporan' })).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'Tren kas 12 bulan' })).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'Sebaran saldo dompet' })).toBeTruthy()
    expect(screen.getByText('Dompet Tak Terpetakan')).toBeTruthy()

    expect(screen.queryByText('Workspace demo')).toBeNull()
    expect(screen.queryByText('Workspace live')).toBeNull()

    fireEvent.click(navigation().getByRole('button', { name: 'Operasional Kantor' }))
    expect(window.location.hash).toBe('#office')
    expect(screen.getByText('Kategori Produksi Khusus')).toBeTruthy()
    expect(screen.getByText('Biaya kategori aktual')).toBeTruthy()
    expect(screen.queryByText('DATA LIVE')).toBeNull()
    expect(screen.queryByText('DATA DEMO')).toBeNull()

    fireEvent.click(navigation().getByRole('button', { name: 'Laporan' }))
    expect(window.location.hash).toBe('#reports')
    expect(screen.getByRole('heading', { name: 'Pusat laporan kanonis' })).toBeTruthy()
    expect(screen.getByText('Texturin Regional Baru')).toBeTruthy()
    expect(screen.queryByText('Unit Operasional Baru')).toBeNull()
    expect(screen.queryByText(/DATA LIVE/i)).toBeNull()
    expect(screen.queryByText(/DATA DEMO/i)).toBeNull()
    expect(screen.queryByText(/^DEMO$/i)).toBeNull()
    expect(request).toHaveBeenCalledWith('/admin/api/snapshot.php', expect.objectContaining({ credentials: 'same-origin' }))
  })

  it('is read-only, never seeds the demo workspace, and keeps theme behavior', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => liveResponse()))

    render(<App />)

    await screen.findByRole('heading', { name: 'Pusat kendali keuangan Hollawall' })
    expect(screen.queryByText(/Data keuangan demo tersimpan/)).toBeNull()
    expect(screen.queryByRole('button', { name: /Reset/i })).toBeNull()
    expect(screen.queryByRole('button', { name: /Tambah transaksi/i })).toBeNull()
    expect(screen.queryByRole('button', { name: /Tambah proyek/i })).toBeNull()
    expect(screen.queryByRole('button', { name: /Tambah hutang/i })).toBeNull()
    expect(screen.queryByRole('button', { name: /Ubah transaksi/i })).toBeNull()
    expect(screen.queryByText('Audit data demo')).toBeNull()
    expect(localStorage.getItem('hollawall-finance-demo-v3')).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: 'Gunakan tema gelap' }))
    await waitFor(() => expect(document.documentElement.dataset.theme).toBe('dark'))
    expect(localStorage.getItem('hollawall-theme')).toBe('dark')
    expect(localStorage.getItem('hollawall-finance-demo-v3')).toBeNull()
  })

  it('keeps snapshot failure closed instead of mounting or seeding demo data', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ error: 'unavailable' }), {
      status: 503,
      headers: { 'content-type': 'application/json' },
    })))

    render(<App />)

    expect(await screen.findByRole('alert')).toHaveTextContent('Data belum tersedia')
    expect(document.querySelector('.app-shell')).toBeNull()
    expect(localStorage.getItem('hollawall-finance-demo-v3')).toBeNull()
  })

  it('quarantines projects without canonical UUID and never queries presensi with generated identity', async () => {
    const snapshot = liveSnapshot()
    snapshot.project_summaries[0] = { ...snapshot.project_summaries[0], project_id: undefined }
    const request = vi.fn(async (_input?: RequestInfo | URL) => liveResponse(snapshot))
    vi.stubGlobal('fetch', request)

    render(<App />)
    await screen.findByRole('heading', { name: 'Pusat kendali keuangan Hollawall' })
    fireEvent.click(navigation().getByRole('button', { name: 'Proyek' }))

    expect(screen.queryByRole('button', { name: 'Buka proyek Proyek Produksi Alfa' })).toBeNull()
    expect(request.mock.calls.some(([input]) => String(input).includes('/admin/api/presensi.php'))).toBe(false)
  })

  it('queries presensi only with an explicit canonical project mapping', async () => {
    const snapshot = liveSnapshot()
    snapshot.project_summaries[0] = { ...snapshot.project_summaries[0], project_id: PROJECT_ALFA_ID }
    const request = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.startsWith('/admin/api/presensi.php')) {
        return new Response(JSON.stringify({ version: 'presensi.admin.v1', records: [] }), { status: 200, headers: { 'content-type': 'application/json' } })
      }
      if (url.startsWith('/admin/api/projects.php?action=list')) return productionProjectsResponse()
      if (url === '/admin/api/write-session.php') return writeSessionResponse()
      return liveResponse(snapshot)
    })
    vi.stubGlobal('fetch', request)

    render(<App />)
    await screen.findByRole('heading', { name: 'Pusat kendali keuangan Hollawall' })
    fireEvent.click(navigation().getByRole('button', { name: 'Proyek' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Buka proyek Kontrak Panggung Utama' }))
    fireEvent.click(screen.getByRole('tab', { name: 'Presensi' }))

    await screen.findByText('Belum ada presensi untuk Kontrak Panggung Utama')
    expect(request).toHaveBeenCalledWith(
      '/admin/api/presensi.php?project_id=123e4567-e89b-42d3-a456-426614174000',
      expect.objectContaining({ credentials: 'same-origin' }),
    )
    expect(request.mock.calls.some(([input]) => String(input).includes('project_id=proyek-produksi-alfa'))).toBe(false)
  })

  it('removes implementation chatter from every production route and transaction form', async () => {
    const request = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.startsWith('/admin/api/projects.php?action=list')) return productionProjectsResponse()
      if (url === '/admin/api/write-session.php') return writeSessionResponse()
      return liveResponse()
    })
    vi.stubGlobal('fetch', request)
    render(<App />)

    await screen.findByRole('heading', { name: 'Pusat kendali keuangan Hollawall' })
    expectNoProductionChatter()
    for (const page of ['Arus Kas', 'Dompet', 'Operasional Kantor', 'Hutang', 'Laporan']) {
      fireEvent.click(navigation().getByRole('button', { name: page }))
      expectNoProductionChatter()
    }
    fireEvent.click(navigation().getByRole('button', { name: 'Proyek' }))
    await screen.findByRole('heading', { name: 'Portofolio proyek per tahun' })
    expectNoProductionChatter()
    fireEvent.click(screen.getByRole('button', { name: 'Buka proyek Kontrak Panggung Utama' }))
    expectNoProductionChatter()
    fireEvent.click(screen.getByRole('tab', { name: 'Ringkasan' }))
    expect(await screen.findByRole('heading', { name: 'Ringkasan proyek' })).toBeTruthy()
    fireEvent.click(screen.getByRole('tab', { name: 'Pinjaman' }))
    expect(await screen.findByRole('heading', { name: 'Pinjaman terkait proyek' })).toBeTruthy()
    fireEvent.click(screen.getByRole('tab', { name: 'Audit' }))
    expect(await screen.findByRole('heading', { name: 'Riwayat perubahan proyek' })).toBeTruthy()

    fireEvent.click(navigation().getByRole('button', { name: 'Dashboard' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Transaksi proyek' }))
    expect(await screen.findByRole('heading', { name: 'Portofolio proyek per tahun' })).toBeTruthy()
    expect(screen.queryByRole('dialog')).toBeNull()
    expectNoProductionChatter()
  })

  it('refreshes immediately after a transaction write and again on the next poll', async () => {
    vi.useFakeTimers()
    let snapshotRequests = 0
    const request = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url === '/admin/api/snapshot.php') { snapshotRequests += 1; return liveResponse() }
      if (url === '/admin/api/write-session.php') return writeSessionResponse()
      if (url === '/admin/api/transactions.php') return recordedTransactionResponse()
      if (url.startsWith('/admin/api/projects.php?action=list')) return productionProjectsResponse()
      return liveResponse()
    })
    vi.stubGlobal('fetch', request)
    render(<App />)
    await act(async () => { await Promise.resolve(); await Promise.resolve(); await Promise.resolve() })

    fireEvent.click(screen.getByRole('button', { name: 'Operasional kantor' }))
    fireEvent.click(screen.getAllByRole('button', { name: /Biaya kantor|Catat biaya/ })[0])
    expect(within(screen.getByRole('dialog')).queryByRole('group', { name: 'Pilih aktivitas' })).toBeNull()
    fireEvent.change(screen.getByLabelText('Jumlah *'), { target: { value: '500000' } })
    fireEvent.change(screen.getByLabelText('Keterangan *'), { target: { value: 'Biaya kantor hari ini' } })
    fireEvent.click(screen.getByRole('button', { name: 'Simpan transaksi' }))
    await act(async () => { await Promise.resolve(); await Promise.resolve(); await Promise.resolve() })
    expect(snapshotRequests).toBe(2)

    await act(async () => { await vi.advanceTimersByTimeAsync(5_000) })
    expect(snapshotRequests).toBe(3)
  })
})
