(() => {
  "use strict";

  const data = window.HOLLAWALL_FIXTURE;
  const state = {
    view: "overview",
    period: "october",
    company: "all",
    wallet: "all",
    project: "all",
    search: ""
  };

  const viewMeta = {
    overview: ["Ikhtisar keuangan", "Ringkasan Perusahaan"],
    cashflow: ["Pergerakan kas", "Arus Kas"],
    wallets: ["Posisi dana", "Posisi Dompet"],
    transactions: ["Penelusuran ledger", "Semua Transaksi"],
    projects: ["Ekonomi proyek", "Kinerja Proyek"],
    debts: ["Kewajiban antar-dompet", "Hutang Antar-Dompet"],
    reports: ["Ekspor deterministik", "Pusat Laporan"]
  };

  const root = document.getElementById("viewRoot");
  const walletFilter = document.getElementById("walletFilter");
  const companyFilter = document.getElementById("companyFilter");
  const projectFilter = document.getElementById("projectFilter");
  const periodFilter = document.getElementById("periodFilter");

  const idr = new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 });
  const compact = value => {
    const abs = Math.abs(value);
    if (abs >= 1e9) return `Rp${(value / 1e9).toFixed(1).replace(/,0$/, "").replace(".", ",")} M`;
    if (abs >= 1e6) return `Rp${(value / 1e6).toFixed(1).replace(/\.0$/, "").replace(".", ",")} jt`;
    if (abs >= 1e3) return `Rp${(value / 1e3).toFixed(0)} rb`;
    return idr.format(value);
  };
  const esc = value => String(value ?? "").replace(/[&<>'"]/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[char]);

  function populateFilters() {
    [...new Set(data.transactions.map(row => row.company))].sort().forEach(value => companyFilter.add(new Option(value, value)));
    data.wallets.forEach(wallet => walletFilter.add(new Option(wallet.name, wallet.name)));
    data.projects.forEach(project => projectFilter.add(new Option(project.name, project.name)));
  }

  function restoreQuery() {
    const query = new URLSearchParams(location.search);
    ["view", "period", "company", "wallet", "project"].forEach(key => {
      if (query.get(key)) state[key] = query.get(key);
    });
    if (!viewMeta[state.view]) state.view = "overview";
    periodFilter.value = state.period;
    companyFilter.value = state.company;
    walletFilter.value = state.wallet;
    projectFilter.value = state.project;
    document.getElementById("staleBanner").hidden = query.get("stale") !== "1";
  }

  function writeQuery() {
    const query = new URLSearchParams();
    if (state.view !== "overview") query.set("view", state.view);
    ["period", "company", "wallet", "project"].forEach(key => {
      if (state[key] !== "all" && !(key === "period" && state[key] === "october")) query.set(key, state[key]);
    });
    if (new URLSearchParams(location.search).get("stale") === "1") query.set("stale", "1");
    history.replaceState(null, "", `${location.pathname}${query.size ? `?${query}` : ""}`);
  }

  function periodMatch(row) {
    if (state.period === "today") return row.date === "2026-10-21";
    if (state.period === "week") return row.date >= "2026-10-15";
    return row.date >= "2026-10-01" && row.date <= "2026-10-21";
  }

  function filteredRows(extra = {}) {
    const active = { ...state, ...extra };
    const needle = active.search.trim().toLowerCase();
    return data.transactions.filter(row =>
      periodMatch(row) &&
      (active.company === "all" || row.company === active.company) &&
      (active.wallet === "all" || row.wallet === active.wallet) &&
      (active.project === "all" || row.project === active.project) &&
      (!needle || Object.values(row).some(value => String(value).toLowerCase().includes(needle)))
    );
  }

  function metrics(rows) {
    const external = rows.filter(row => !["Transfer", "Hutang"].includes(row.type));
    const inflow = external.filter(row => row.type === "Pemasukan").reduce((sum, row) => sum + row.amount, 0);
    const outflow = external.filter(row => row.type === "Pengeluaran").reduce((sum, row) => sum + row.amount, 0);
    const wallets = state.wallet === "all" ? data.wallets : data.wallets.filter(wallet => wallet.name === state.wallet);
    const cash = wallets.reduce((sum, wallet) => sum + wallet.balance, 0);
    const debts = data.debts.reduce((sum, debt) => sum + debt.open, 0);
    const complete = rows.length ? Math.round(rows.filter(row => row.evidence).length / rows.length * 100) : 100;
    return { cash, inflow, outflow, net: inflow - outflow, debts, complete };
  }

  function kpiButton(label, value, foot, metric, cls = "") {
    return `<button class="kpi ${cls}" data-metric="${metric}" data-testid="kpi-${metric}"><span class="kpi-label">${label}<i></i></span><b class="kpi-value">${value}</b><span class="kpi-foot">${foot}</span></button>`;
  }

  function summarySection(rows) {
    const value = metrics(rows);
    return `<div class="kpi-grid" data-testid="kpi-grid">
      ${kpiButton("Saldo kas", compact(value.cash), "Per 21 Okt · 3 dompet", "cash")}
      ${kpiButton("Pemasukan eksternal", compact(value.inflow), "Periode 1–21 Okt", "inflow")}
      ${kpiButton("Pengeluaran eksternal", compact(value.outflow), "Periode 1–21 Okt", "outflow")}
      ${kpiButton("Arus kas bersih", compact(value.net), "Pemasukan − pengeluaran", "net")}
      ${kpiButton("Saldo antar-dompet", compact(value.debts), "Internal · tidak dikonsolidasi", "debt", "is-risk")}
      ${kpiButton("Bukti lengkap", `${value.complete}%`, `${rows.filter(row => !row.evidence).length} dari ${rows.length} transaksi belum lengkap`, "quality", "is-quality")}
    </div>`;
  }

  function cashChart(rows) {
    const buckets = ["01–03", "04–06", "07–09", "10–12", "13–15", "16–18", "19–21"];
    const values = buckets.map((label, idx) => {
      const from = 1 + idx * 3;
      const to = from + 2;
      const matching = rows.filter(row => {
        const day = Number(row.date.slice(-2));
        return day >= from && day <= to && !["Transfer", "Hutang"].includes(row.type);
      });
      return {
        label,
        incoming: matching.filter(row => row.type === "Pemasukan").reduce((sum, row) => sum + row.amount, 0),
        outgoing: matching.filter(row => row.type === "Pengeluaran").reduce((sum, row) => sum + row.amount, 0)
      };
    });
    const max = Math.max(1, ...values.flatMap(item => [item.incoming, item.outgoing]));
    return `<div class="chart-wrap">
      <div class="chart-summary"><span><i class="legend-dot incoming"></i>Pemasukan <b>${compact(values.reduce((s,x) => s + x.incoming, 0))}</b></span><span><i class="legend-dot outgoing"></i>Pengeluaran <b>${compact(values.reduce((s,x) => s + x.outgoing, 0))}</b></span><span class="chart-scale">Skala maks. ${compact(max)}</span></div>
      <div class="cash-chart" role="img" aria-label="Grafik pemasukan dan pengeluaran per tiga hari">
        ${values.map(item => `<div class="bar-pair" title="${item.label}: masuk ${idr.format(item.incoming)}, keluar ${idr.format(item.outgoing)}"><i class="bar in" style="height:${item.incoming / max * 92}%"></i><i class="bar out" style="height:${item.outgoing / max * 92}%"></i><span>${item.label}</span></div>`).join("")}
      </div><div class="chart-axis-label">Tanggal Oktober 2026 · transfer internal dieliminasi</div>
    </div>`;
  }

  function walletList() {
    return `<div class="wallet-list" data-testid="wallet-list">${data.wallets.map(wallet => `<button class="wallet-row" data-wallet="${wallet.name}" style="--accent:${wallet.accent}"><i></i><span><strong>${wallet.name}</strong><small>${wallet.note}</small></span><b>${compact(wallet.balance)}</b></button>`).join("")}<div class="wallet-total"><span>Total konsolidasi</span><b>${compact(data.wallets.reduce((s,w) => s + w.balance, 0))}</b></div></div>`;
  }

  function attentionList(rows) {
    const missing = rows.filter(row => !row.evidence).length;
    const oldest = Math.max(...data.debts.map(debt => debt.age));
    return `<div class="attention-list">
      <div class="attention-row"><span class="marker">${missing}</span><span><strong>Bukti transaksi belum lengkap</strong><small>Perlu dilengkapi sebelum tutup periode</small></span><b>TINJAU</b></div>
      <div class="attention-row"><span class="marker">${data.debts.length}</span><span><strong>Hutang antar-dompet terbuka</strong><small>Umur tertua ${oldest} hari</small></span><b>${compact(data.debts.reduce((s,d) => s+d.open,0))}</b></div>
      <div class="attention-row"><span class="marker">!</span><span><strong>Project Ubud perlu data tambahan</strong><small>Kelengkapan berada di bawah 80%</small></span><b>72%</b></div>
    </div>`;
  }

  function projectList(rows) {
    return `<div class="project-list">${data.projects.map(project => {
      const scoped = rows.filter(row => row.project === project.name && !["Transfer", "Hutang"].includes(row.type));
      const contribution = scoped.reduce((sum,row) => sum + (row.type === "Pemasukan" ? row.amount : -row.amount),0);
      return `<div class="project-row"><span><strong>${project.name}</strong><small>${project.company} · ${project.status}</small></span><span><small>Kelengkapan ${project.completeness}%</small><i class="progress"><i style="width:${project.completeness}%"></i></i></span><b>${compact(contribution)}</b></div>`;
    }).join("")}</div>`;
  }

  function transactionsTable(rows, limit = 8) {
    const visible = rows.slice(0, limit);
    if (!visible.length) return `<div class="empty-state">Tidak ada transaksi untuk filter ini.</div>`;
    return `<div class="table-wrap"><table data-testid="transaction-table"><thead><tr><th>Tanggal</th><th>Transaksi</th><th>Dompet</th><th>Proyek</th><th>Status</th><th>Nominal</th></tr></thead><tbody>${visible.map(row => `<tr>
      <td>${row.date.split("-").reverse().join("/")}</td>
      <td><strong>${esc(row.description)}</strong><br><small>${row.id} · ${row.category}</small></td>
      <td>${row.wallet}</td><td>${row.project}</td>
      <td><span class="tag ${row.type === "Pemasukan" ? "in" : row.type === "Pengeluaran" ? "out" : "internal"}">${row.type}</span>${row.evidence ? "" : ` <span class="evidence-missing">Bukti?</span>`}</td>
      <td class="amount">${row.type === "Pengeluaran" ? "−" : row.type === "Pemasukan" ? "+" : ""}${compact(row.amount)}</td>
    </tr>`).join("")}</tbody></table></div>`;
  }

  function renderOverview(rows) {
    return `<section class="section-intro"><div><h2>Posisi keuangan per 21 Oktober</h2><p>Saldo saat ini dan pergerakan periode 1–21 Oktober; transfer internal dieliminasi.</p></div><div class="as-of">DIPERBARUI<br>21 OKT 2026 · 18.42 WIB</div></section>
      ${summarySection(rows)}
      <section class="priority-strip"><button data-open-view="transactions"><span>2</span><b>Bukti transaksi belum lengkap</b><small>Tinjau sebelum tutup periode</small></button><button data-open-view="debts"><span>33h</span><b>Saldo antar-dompet menua</b><small>${compact(data.debts.reduce((s,d)=>s+d.open,0))} masih terbuka</small></button><button data-open-view="transactions"><span>5</span><b>Aktivitas hari ini</b><small>Lihat transaksi dan sumber terbaru</small></button></section>
      <section class="dashboard-grid">
        <article class="panel"><header class="panel-head"><div><h3>Arus kas periode berjalan</h3><p>Perbandingan pemasukan dan pengeluaran eksternal</p></div><button data-open-view="cashflow">Lihat detail</button></header>${cashChart(rows)}</article>
        <article class="panel"><header class="panel-head"><div><h3>Saldo kas per unit</h3><p>Dompet operasional dan pengelola dana</p></div><button data-open-view="wallets">Lihat semua</button></header>${walletList()}</article>
      </section>
      <section class="dashboard-grid equal">
        <article class="panel"><header class="panel-head"><div><h3>Perlu perhatian</h3><p>Pengecualian yang memengaruhi kualitas keputusan</p></div><button>Semua isu</button></header>${attentionList(rows)}</article>
        <article class="panel"><header class="panel-head"><div><h3>Arus kas proyek bersih</h3><p>Bukan laba akuntansi; berdasarkan kas yang tercatat</p></div><button data-open-view="projects">Semua proyek</button></header>${projectList(rows)}</article>
      </section>
      <section class="panel table-panel" style="margin-top:14px"><header class="panel-head"><div><h3>Aktivitas terbaru</h3><p>Semua sumber input yang sudah masuk ledger</p></div><button data-open-view="transactions">Lihat semua</button></header>${transactionsTable(rows)}</section>`;
  }

  function renderCashflow(rows) {
    const value = metrics(rows);
    return `<section class="section-intro"><div><h2>Pergerakan kas perusahaan</h2><p>Transfer internal dikeluarkan dari konsolidasi.</p></div><div class="as-of">NET MOVEMENT<br>${compact(value.net)}</div></section>${summarySection(rows)}<section class="panel" style="margin-top:14px"><header class="panel-head"><div><h3>Pemasukan vs pengeluaran</h3><p>Klik grafik di versi produk untuk membuka transaksi pembentuk angka</p></div></header>${cashChart(rows)}<div class="metric-strip"><div><small>Transaksi masuk</small><b>${rows.filter(r=>r.type==="Pemasukan").length}</b></div><div><small>Transaksi keluar</small><b>${rows.filter(r=>r.type==="Pengeluaran").length}</b></div><div><small>Transfer internal</small><b>${rows.filter(r=>r.type==="Transfer").length}</b></div><div><small>Arus bersih</small><b>${compact(value.net)}</b></div></div></section>`;
  }

  function renderWallets(rows) {
    return `<section class="section-intro"><div><h2>Tiga dompet operasional</h2><p>Posisi, aliran, perusahaan, dan project pengguna dana.</p></div></section><section class="dashboard-grid equal">${data.wallets.map(wallet => {
      const scoped = rows.filter(row => row.wallet === wallet.name && !["Transfer","Hutang"].includes(row.type));
      const value = metrics(scoped);
      return `<article class="panel"><header class="panel-head"><div><h3>${wallet.name}</h3><p>${wallet.note}</p></div><i style="width:8px;height:32px;background:${wallet.accent}"></i></header><div style="padding:10px 17px 20px"><small>Saldo saat ini</small><div class="big-number" style="margin:8px 0 20px">${compact(wallet.balance)}</div></div><div class="metric-strip"><div><small>Masuk</small><b>${compact(value.inflow)}</b></div><div><small>Keluar</small><b>${compact(value.outflow)}</b></div><div><small>Transaksi</small><b>${scoped.length}</b></div><div><small>Bukti lengkap</small><b>${value.complete}%</b></div></div></article>`;
    }).join("")}</section>`;
  }

  function renderTransactions(rows) {
    return `<section class="section-intro"><div><h2>Ledger transaksi</h2><p>Telusuri angka sampai sumber WhatsApp atau sistem.</p></div><div class="view-toolbar"><input id="transactionSearch" aria-label="Cari transaksi" placeholder="Cari ID, proyek, kategori…" value="${esc(state.search)}"><button class="action-secondary">Export XLSX</button></div></section><section class="panel table-panel"><header class="panel-head"><div><h3>Hasil pencarian</h3><p data-testid="transaction-count">${rows.length} transaksi sesuai filter</p></div><span class="filter-count">Halaman 1</span></header>${transactionsTable(rows,50)}</section>`;
  }

  function renderProjects(rows) {
    return `<section class="section-intro"><div><h2>Kinerja proyek</h2><p>Menampilkan kontribusi tercatat, belum laba akuntansi.</p></div></section><section class="dashboard-grid equal">${data.projects.map(project => {
      const scoped = rows.filter(row => row.project === project.name && !["Transfer","Hutang"].includes(row.type));
      const value = metrics(scoped);
      return `<article class="panel"><header class="panel-head"><div><h3>${project.name}</h3><p>${project.company} · ${project.wallet}</p></div><span class="tag ${project.completeness < 80 ? "out":"in"}">${project.completeness}% lengkap</span></header><div style="padding:12px 17px 20px"><small>Kontribusi tercatat</small><div class="big-number" style="margin:8px 0 20px">${compact(value.net)}</div><div class="progress"><i style="width:${Math.min(100,(value.outflow/project.budget)*100)}%"></i></div><small style="display:block;margin-top:7px;color:var(--muted)">${compact(value.outflow)} biaya tercatat dari budget ${compact(project.budget)}</small></div><div class="metric-strip"><div><small>Masuk</small><b>${compact(value.inflow)}</b></div><div><small>Keluar</small><b>${compact(value.outflow)}</b></div><div><small>Transaksi</small><b>${scoped.length}</b></div><div><small>Status</small><b>${project.status}</b></div></div></article>`;
    }).join("")}</section>`;
  }

  function renderDebts() {
    const total = data.debts.reduce((s,d)=>s+d.open,0);
    return `<section class="section-intro"><div><h2>Hutang antar-dompet</h2><p>Terlihat per unit, dieliminasi dari angka perusahaan.</p></div><div class="as-of">SALDO TERBUKA<br>${compact(total)}</div></section><section class="panel table-panel"><header class="panel-head"><div><h3>Posisi kewajiban internal</h3><p>${data.debts.length} hubungan pendanaan terbuka</p></div></header><div class="table-wrap"><table><thead><tr><th>ID / Tanggal</th><th>Arah pendanaan</th><th>Keperluan</th><th>Umur</th><th>Status</th><th>Saldo terbuka</th></tr></thead><tbody>${data.debts.map(debt=>`<tr><td><strong>${debt.id}</strong><br><small>${debt.date}</small></td><td class="debt-direction">${debt.lender}<br>↓ ${debt.borrower}</td><td>${debt.purpose}</td><td>${debt.age} hari</td><td><span class="tag ${debt.status==="Terbuka"?"out":"internal"}">${debt.status}</span></td><td class="amount">${compact(debt.open)}</td></tr>`).join("")}</tbody></table></div></section>`;
  }

  function renderReports() {
    const reports = [
      ["01","Posisi Kas","Saldo terkonsolidasi dan rincian setiap dompet."],
      ["02","Arus Kas","Pemasukan, pengeluaran, dan pergerakan bersih."],
      ["03","Kontribusi Proyek","Transaksi dan kontribusi tercatat per proyek."],
      ["04","Operasional Kantor","Biaya kantor lintas tiga dompet."],
      ["05","Hutang Internal","Posisi dan umur hutang antar-dompet."],
      ["06","Kelengkapan Data","Transaksi tanpa bukti atau konteks lengkap."]
    ];
    return `<section class="section-intro"><div><h2>Laporan siap keputusan</h2><p>Angka dihitung backend; file hanya menyajikan hasil deterministik.</p></div></section><section class="report-grid">${reports.map(report=>`<article class="report-card"><span class="number">${report[0]}</span><h3>${report[1]}</h3><p>${report[2]}</p><button class="action-secondary">Buat laporan</button></article>`).join("")}</section>`;
  }

  function render() {
    const rows = filteredRows();
    const [eyebrow,title] = viewMeta[state.view];
    document.getElementById("pageEyebrow").textContent = eyebrow;
    document.getElementById("pageTitle").textContent = title;
    document.querySelectorAll(".nav-item").forEach(item => item.classList.toggle("is-active", item.dataset.view === state.view));
    root.innerHTML = ({
      overview: renderOverview,
      cashflow: renderCashflow,
      wallets: renderWallets,
      transactions: renderTransactions,
      projects: renderProjects,
      debts: renderDebts,
      reports: renderReports
    })[state.view](rows);
    bindDynamic();
    writeQuery();
    document.title = `${title} — Hollawall`;
  }

  function setView(view) {
    if (!viewMeta[view]) return;
    state.view = view;
    closeDrawer();
    render();
    document.querySelector(".main-panel").scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
  }

  function openTransactions(extra = {}) {
    Object.assign(state, extra, { view: "transactions" });
    walletFilter.value = state.wallet;
    render();
  }

  function bindDynamic() {
    root.querySelectorAll("[data-open-view]").forEach(button => button.addEventListener("click", () => setView(button.dataset.openView)));
    root.querySelectorAll("[data-wallet]").forEach(button => button.addEventListener("click", () => openTransactions({ wallet: button.dataset.wallet })));
    root.querySelectorAll("[data-metric]").forEach(button => button.addEventListener("click", () => {
      const metric = button.dataset.metric;
      if (metric === "inflow") state.search = "Pemasukan";
      else if (metric === "outflow") state.search = "Pengeluaran";
      else if (metric === "debt") return setView("debts");
      else if (metric === "quality") state.search = "";
      else state.search = "";
      setView("transactions");
    }));
    const search = document.getElementById("transactionSearch");
    if (search) search.addEventListener("input", event => { state.search = event.target.value; render(); document.getElementById("transactionSearch")?.focus(); });
  }

  function closeDrawer() {
    document.getElementById("sidebar").classList.remove("is-open");
    document.getElementById("drawerBackdrop").hidden = true;
    document.getElementById("menuButton").setAttribute("aria-expanded", "false");
  }

  document.querySelectorAll(".nav-item").forEach(item => item.addEventListener("click", () => setView(item.dataset.view)));
  [periodFilter, companyFilter, walletFilter, projectFilter].forEach(element => element.addEventListener("change", () => {
    state.period = periodFilter.value;
    state.company = companyFilter.value;
    state.wallet = walletFilter.value;
    state.project = projectFilter.value;
    render();
  }));
  document.getElementById("menuButton").addEventListener("click", () => {
    const sidebar = document.getElementById("sidebar");
    const open = sidebar.classList.toggle("is-open");
    document.getElementById("drawerBackdrop").hidden = !open;
    document.getElementById("menuButton").setAttribute("aria-expanded", String(open));
  });
  document.getElementById("drawerBackdrop").addEventListener("click", closeDrawer);
  document.getElementById("askButton").addEventListener("click", () => document.getElementById("aiDialog").showModal());
  document.addEventListener("keydown", event => { if (event.key === "Escape") closeDrawer(); });
  window.addEventListener("popstate", () => { restoreQuery(); render(); });

  populateFilters();
  restoreQuery();
  render();
})();
