import { useState } from 'react'
import { PresensiPanel } from './ProjectTransactionsWorkspace'
import { useLiveSnapshot } from './liveSnapshotView'
import type { ProjectSummary } from './snapshot'
import './live-snapshot.css'

type LivePage = 'Ringkasan' | 'Proyek' | 'Transaksi' | 'Dompet'
type ProjectTab = 'Transaksi' | 'Presensi'

function projectId(name: string) {
  const slug = name
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLocaleLowerCase('id-ID')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '')
  return slug.length >= 2 ? slug.slice(0, 64) : `project-${slug || 'live'}`
}

export default function LiveFinanceApp() {
  const state = useLiveSnapshot({ endpoint: '/admin/api/snapshot.php' })
  const [page, setPage] = useState<LivePage>('Ringkasan')
  const [selectedProject, setSelectedProject] = useState<ProjectSummary | null>(null)
  const [projectTab, setProjectTab] = useState<ProjectTab>('Transaksi')

  if (state.status === 'loading') return <main role="status">Menghubungkan data keuangan live</main>
  if (state.status === 'error') return <main role="alert"><h1>Data live belum tersedia</h1><p>Data demo tidak ditampilkan sebagai pengganti.</p><button onClick={state.reload}>Coba lagi</button></main>

  const data = state.data
  const openProject = (project: ProjectSummary) => {
    const id = projectId(project.name)
    window.location.hash = `projects?project=${encodeURIComponent(id)}`
    setSelectedProject(project)
    setProjectTab('Transaksi')
  }
  const choosePage = (nextPage: LivePage) => {
    setPage(nextPage)
    setSelectedProject(null)
  }
  const selectedId = selectedProject ? projectId(selectedProject.name) : ''
  const selectedTransactions = selectedProject
    ? data.transactions.filter((transaction) => transaction.project === selectedProject.name)
    : []

  return <main className="live-snapshot">
    <h1>Hollawall</h1>
    <p>Mode live · hanya baca</p>
    <nav aria-label="Menu utama">
      {(['Ringkasan', 'Proyek', 'Transaksi', 'Dompet'] as LivePage[]).map((name) => <button key={name} onClick={() => choosePage(name)}>{name}</button>)}
    </nav>
    <button onClick={state.reload}>Muat ulang</button>

    {selectedProject ? <section aria-label={`Detail ${selectedProject.name}`}>
      <button type="button" onClick={() => setSelectedProject(null)}>Kembali ke proyek</button>
      <h2>{selectedProject.name}</h2>
      <div role="tablist" aria-label={`Detail proyek ${selectedProject.name}`}>
        {(['Transaksi', 'Presensi'] as ProjectTab[]).map((tab) => <button
          type="button"
          role="tab"
          aria-selected={projectTab === tab}
          key={tab}
          onClick={() => setProjectTab(tab)}
        >{tab}</button>)}
      </div>
      {projectTab === 'Transaksi' ? <section aria-label={`Transaksi ${selectedProject.name}`}>
        {selectedTransactions.length ? <table><thead><tr><th>Tanggal</th><th>Keterangan</th><th>Jumlah</th></tr></thead><tbody>{selectedTransactions.map((transaction) => <tr key={transaction.source_key ?? transaction.id}><td>{transaction.transaction_date}</td><td>{transaction.notes}</td><td>{transaction.amount.toLocaleString('id-ID')}</td></tr>)}</tbody></table> : <p>Belum ada transaksi untuk {selectedProject.name}</p>}
      </section> : <PresensiPanel project={{ id: selectedId, name: selectedProject.name }} />}
    </section> : <>
      <h2>{page}</h2>
      {(page === 'Ringkasan' || page === 'Dompet') && <section><h3>Dompet</h3>{data.wallets.map((wallet) => <p key={wallet.source_key}><span>{wallet.name}</span>: {wallet.balance.toLocaleString('id-ID')}</p>)}</section>}
      {page === 'Proyek' && <section><h3>Proyek</h3>{data.project_summaries.map((project) => <article key={project.name}><p>{project.name}</p><button type="button" aria-label={`Buka ${project.name}`} onClick={() => openProject(project)}>Buka proyek</button></article>)}</section>}
      {(page === 'Ringkasan' || page === 'Transaksi') && <section><h3>Transaksi</h3><table><thead><tr><th>Tanggal</th><th>Proyek</th><th>Keterangan</th><th>Jumlah</th></tr></thead><tbody>{data.transactions.map((transaction) => <tr key={transaction.source_key ?? transaction.id}><td>{transaction.transaction_date}</td><td>{transaction.project}</td><td>{transaction.notes}</td><td>{transaction.amount.toLocaleString('id-ID')}</td></tr>)}</tbody></table></section>}
    </>}
  </main>
}
