import { useEffect, useRef, useState } from 'react'

import {
  reviewErrorMessage,
  type InboxReviewAction,
  type InboxReviewApi,
  type InboxReviewCommand,
  type InboxReviewDetail,
  type InboxReviewItem,
  type InboxReviewList,
} from './inboxReviewApi'

interface Props {
  api: InboxReviewApi
  csrfToken: string
}

interface PendingDecision {
  action: InboxReviewAction
  command: InboxReviewCommand
}

function displayTime(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat('id-ID', {
    dateStyle: 'medium', timeStyle: 'short', timeZone: 'Asia/Jakarta',
  }).format(date)
}

function statusLabel(value: string) {
  return value.replace(/^needs_review_?/, '').replaceAll('_', ' ') || 'perlu ditinjau'
}

function ReviewList({ items, selected, select }: { items: InboxReviewItem[]; selected?: string; select: (item: InboxReviewItem) => void }) {
  if (!items.length) return <p className="inbox-review-empty">Tidak ada pesan yang menunggu keputusan.</p>
  return <ul className="inbox-review-list">{items.map((item) => <li key={item.eventKey}>
    <button
      type="button"
      className={selected === item.eventKey ? 'is-selected' : ''}
      aria-current={selected === item.eventKey ? 'true' : undefined}
      aria-label={`Tinjau ${item.messageId}`}
      onClick={() => select(item)}
    >
      <span><strong>{item.messageId}</strong><small>{item.provider} · {item.eventType}</small></span>
      <span><b>{statusLabel(item.status)}</b><small>{displayTime(item.updatedAt)}</small></span>
    </button>
  </li>)}</ul>
}

function Confirmation({ decision, close, confirm, busy }: { decision: PendingDecision; close: () => void; confirm: () => void; busy: boolean }) {
  const ignore = decision.action === 'ignore'
  return <div className="modal-backdrop" role="presentation">
    <section className="modal-card inbox-review-confirm" role="dialog" aria-modal="true" aria-labelledby="inbox-review-confirm-title">
      <h2 id="inbox-review-confirm-title">Konfirmasi keputusan</h2>
      <p>{ignore
        ? 'Pesan akan diabaikan permanen. Keputusan ini tidak dapat dibatalkan.'
        : 'Pesan akan ditandai sudah diproses berdasarkan pemeriksaan buku besar. Keputusan ini tidak dapat dibatalkan.'}</p>
      <div className="modal-actions">
        <button type="button" className="secondary-button" onClick={close} disabled={busy}>Batal</button>
        <button type="button" className={ignore ? 'danger-button' : 'primary-button'} onClick={confirm} disabled={busy}>
          {busy ? 'Menyimpan…' : ignore ? 'Ya, abaikan permanen' : 'Ya, tandai sudah diproses'}
        </button>
      </div>
    </section>
  </div>
}

export function InboxReviewWorkspace({ api, csrfToken }: Props) {
  const [list, setList] = useState<InboxReviewList>()
  const [selected, setSelected] = useState<InboxReviewItem>()
  const [detail, setDetail] = useState<InboxReviewDetail>()
  const [reason, setReason] = useState('')
  const [loading, setLoading] = useState(true)
  const [detailLoading, setDetailLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [pending, setPending] = useState<PendingDecision>()
  const uncertainCommand = useRef<InboxReviewCommand>()

  const load = async (offset = list?.offset ?? 0) => {
    setLoading(true)
    setError('')
    try {
      setList(await api.list({ offset, limit: 25 }))
    } catch (failure) {
      setError(reviewErrorMessage(failure))
    } finally { setLoading(false) }
  }

  useEffect(() => { void load() }, [api])

  const select = async (item: InboxReviewItem) => {
    setSelected(item)
    setDetail(undefined)
    setReason('')
    setError('')
    setNotice('')
    setPending(undefined)
    uncertainCommand.current = undefined
    setDetailLoading(true)
    try {
      setDetail(await api.detail(item.eventKey))
    } catch (failure) {
      setError(reviewErrorMessage(failure))
    } finally { setDetailLoading(false) }
  }

  const decide = (action: InboxReviewAction) => {
    if (!detail || !reason.trim() || reason.trim().length > 1000) return
    const command = api.command({
      eventKey: detail.eventKey,
      action,
      reason,
      expectedStatus: detail.status,
    })
    setPending({ action, command })
  }

  const confirm = async () => {
    if (!pending) return
    setBusy(true)
    setError('')
    setNotice('')
    try {
      await pending.command.submit({ csrfToken })
      uncertainCommand.current = undefined
      setPending(undefined)
      setSelected(undefined)
      setDetail(undefined)
      setReason('')
      setNotice('Keputusan tersimpan.')
      setList(await api.list({ offset: list?.offset ?? 0, limit: 25 }))
    } catch (failure) {
      if (failure && typeof failure === 'object' && 'uncertain' in failure && failure.uncertain === true) {
        uncertainCommand.current = pending.command
      } else {
        uncertainCommand.current = undefined
      }
      setPending(undefined)
      setError(reviewErrorMessage(failure))
    } finally { setBusy(false) }
  }

  const writesEnabled = list?.writesEnabled === true
  const canIgnore = writesEnabled && list.allowedActions.includes('ignore')
  const canConfirm = writesEnabled && list.allowedActions.includes('confirm_processed')
  const validReason = reason.trim().length > 0 && reason.trim().length <= 1000

  return <section className="inbox-review-workspace" aria-labelledby="inbox-review-title">
    <header className="page-heading inbox-review-heading">
      <div><p className="eyebrow">KOTAK MASUK TAHAN GAGAL</p><h1 id="inbox-review-title">Perlu Ditinjau</h1><p>Periksa pesan yang belum mendapat hasil pasti. Hanya keputusan terminal yang tersedia; sistem tidak mengulang proses otomatis.</p></div>
      <button type="button" className="secondary-button" onClick={() => void load(list?.offset ?? 0)} disabled={loading}>Muat daftar kembali</button>
    </header>

    {notice && <p role="status" className="inbox-review-notice">{notice}</p>}
    {error && <p role="alert" className="form-error">{error}</p>}
    {loading ? <p role="status">Memuat pesan yang perlu ditinjau…</p> : <div className="inbox-review-grid">
      <section className="inbox-review-panel" aria-label="Daftar pesan perlu ditinjau">
        <header><h2>Pesan tertunda</h2><span>{list?.total ?? 0}</span></header>
        <ReviewList items={list?.items ?? []} selected={selected?.eventKey} select={(item) => void select(item)} />
        {list && <nav className="inbox-review-pagination" aria-label="Halaman pesan perlu ditinjau">
          <span>{list.items.length ? `${list.offset + 1}–${list.offset + list.items.length}` : '0'} dari {list.total}</span>
          <div>
            <button type="button" className="secondary-button" aria-label="Halaman sebelumnya" disabled={loading || list.offset === 0} onClick={() => void load(Math.max(0, list.offset - list.limit))}>Sebelumnya</button>
            <button type="button" className="secondary-button" aria-label="Halaman berikutnya" disabled={loading || !list.hasMore} onClick={() => void load(list.offset + list.limit)}>Berikutnya</button>
          </div>
        </nav>}
      </section>

      <section className="inbox-review-panel inbox-review-detail" aria-label="Detail pesan">
        {!selected && <p className="inbox-review-empty">Pilih pesan untuk melihat detail yang sudah disaring.</p>}
        {selected && detailLoading && <p role="status">Memuat detail aman…</p>}
        {detail && <>
          <header><div><p className="eyebrow">DETAIL AMAN</p><h2>{detail.messageId}</h2></div><span className="status-chip">{statusLabel(detail.status)}</span></header>
          <dl className="inbox-review-facts">
            <div><dt>Penyedia</dt><dd>{detail.provider}</dd></div>
            <div><dt>Jenis</dt><dd>{detail.eventType}</dd></div>
            <div><dt>Upaya sebelumnya</dt><dd>{detail.attempts}</dd></div>
            <div><dt>Diterima</dt><dd>{displayTime(detail.receivedAt)}</dd></div>
            <div><dt>Sinyal keuangan</dt><dd>{detail.financeSignal ? 'Ya' : 'Tidak'}</dd></div>
            <div><dt>Media</dt><dd>{detail.mediaAvailable ? 'Tersedia di layanan privat' : 'Tidak tersedia'}</dd></div>
          </dl>
          <div className="inbox-review-body"><h3>Isi pesan</h3><pre>{detail.bodyText || '(kosong)'}</pre></div>
          {detail.quotedMessageId && <p className="inbox-review-quote">Pesan yang dikutip: <code>{detail.quotedMessageId}</code></p>}
          {!writesEnabled ? <p className="inbox-review-readonly">Perubahan dinonaktifkan. Detail tersedia hanya untuk pemeriksaan.</p> : <div className="inbox-review-actions">
            <label>Alasan keputusan<textarea aria-label="Alasan keputusan" value={reason} onChange={(event) => setReason(event.target.value)} maxLength={1000} rows={4} placeholder="Tuliskan bukti yang diperiksa dan alasan keputusan." /></label>
            <small>{reason.length}/1000 karakter</small>
            <div>
              {canIgnore && <button type="button" className="danger-button" disabled={!validReason || busy} onClick={() => decide('ignore')}>Abaikan permanen</button>}
              {canConfirm && <button type="button" className="primary-button" disabled={!validReason || busy} onClick={() => decide('confirm_processed')}>Tandai sudah diproses</button>}
            </div>
          </div>}
        </>}
      </section>
    </div>}
    {pending && <Confirmation decision={pending} close={() => setPending(undefined)} confirm={() => void confirm()} busy={busy} />}
  </section>
}

export default InboxReviewWorkspace
