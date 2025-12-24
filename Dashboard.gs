/**
 * ============================================
 * ULTIMATE FINANCIAL DASHBOARD - STABLE V3
 * ============================================
 * Project: Keuangan Multi-Proyek
 * 
 * STRUKTUR SHEET PROYEK:
 * - Kolom B: Tanggal
 * - Kolom C: Keterangan
 * - Kolom D: Jumlah (Angka Uang)
 * - Kolom E: Tipe ("Pemasukan" atau "Pengeluaran")
 * - Kolom H: Kategori (Bahan, Gaji, Alat, Operasional)
 * 
 * CARA PAKAI:
 * 1. Extensions > Apps Script
 * 2. Paste kode ini
 * 3. Jalankan updateDashboard()
 * 4. Buat grafik manual (sekali saja) dari data source
 */

// KONFIGURASI TEMA & SHEET
const SHEET_CONFIG = {
  DASHBOARD: 'Dashboard',
  IGNORE: ['Dashboard', 'Meta_Projek', 'Data_Agregat'],
  COLORS: {
    BG: '#F3F4F6',          // Abu-abu background aplikasi
    CARD_BG: '#FFFFFF',     // Putih bersih untuk kartu
    HEADER_DARK: '#1E293B', // Biru gelap (Slate 800)
    TEXT_MAIN: '#0F172A',   // Hitam kebiruan (Slate 900)
    TEXT_MUTED: '#64748B',  // Abu-abu teks (Slate 500)
    ACCENT_BLUE: '#3B82F6', // Biru cerah (Primary)
    ACCENT_GREEN: '#10B981',// Hijau sukses
    ACCENT_RED: '#EF4444',  // Merah error
    ACCENT_WARN: '#F59E0B'  // Kuning warning
  }
};

/**
 * Fungsi Utama - Jalankan ini untuk update Dashboard
 */
function updateDashboard() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  
  // 1. SIAPKAN SHEET DASHBOARD
  let dashboard = ss.getSheetByName(SHEET_CONFIG.DASHBOARD);
  if (!dashboard) {
    dashboard = ss.insertSheet(SHEET_CONFIG.DASHBOARD);
    ss.moveActiveSheet(1);
  }
  
  // Bersihkan total
  dashboard.clear(); 
  dashboard.setHiddenGridlines(true);
  
  // Set Font Global & Background
  const fullRange = dashboard.getRange("A1:Z200");
  fullRange.setBackground(SHEET_CONFIG.COLORS.BG).setFontFamily("Montserrat");

  // 2. AMBIL SEMUA DATA TRANSAKSI
  const rawData = fetchAllData(ss);
  
  // Hitung KPI Global
  let kpi = { income: 0, expense: 0, balance: 0 };
  rawData.forEach(d => {
    kpi.income += d.income;
    kpi.expense += d.expense;
  });
  kpi.balance = kpi.income - kpi.expense;

  // 3. RENDER VISUAL (HEADER & SCORECARDS)
  renderHeader(dashboard);
  renderScorecards(dashboard, kpi);

  // 4. RENDER TABEL & DATA
  let currentY = 13; // Mulai di baris 13
  
  // A. Tabel Project Health
  currentY = renderProjectHealth(dashboard, rawData, currentY);
  
  // B. Tabel Big Spenders
  currentY += 2; 
  currentY = renderBigSpenders(dashboard, rawData, currentY);

  // C. Data Source untuk Grafik (Bagian Manual)
  currentY += 3;
  renderChartDataSources(dashboard, rawData, currentY);
  
  // Log sukses
  Logger.log('✅ Dashboard berhasil diperbarui! Total transaksi: ' + rawData.length);
}

// ==========================================
// BAGIAN 1: LOGIKA DATA (ENGINE)
// ==========================================

function fetchAllData(ss) {
  const sheets = ss.getSheets();
  let allTransactions = [];
  let debugInfo = { sheetsProcessed: 0, rowsRead: 0, incomeFound: 0, expenseFound: 0, errors: [] };

  sheets.forEach(sheet => {
    const sheetName = sheet.getName();
    if (SHEET_CONFIG.IGNORE.includes(sheetName)) return;
    if (sheet.getLastRow() < 2) return; // Skip sheet kosong

    debugInfo.sheetsProcessed++;

    // Ambil semua data (Kolom A-H = 1-8)
    const lastRow = sheet.getLastRow();
    const dataVals = sheet.getRange(2, 1, lastRow - 1, 8).getValues();
    
    dataVals.forEach((row, idx) => {
      debugInfo.rowsRead++;
      
      // Validasi: Harus ada Tanggal (col B = index 1) dan Jumlah (col D = index 3)
      if (!row[1] || row[3] === "" || row[3] === null || row[3] === undefined) return; 

      let inc = 0, exp = 0;
      let rawType = row[4]; // Kolom E
      let type = String(rawType).toLowerCase().trim();
      
      // DEBUG: Log first few rows
      if (debugInfo.rowsRead <= 3) {
        Logger.log(`[DEBUG] Sheet: ${sheetName}, Row ${idx+2}: Type="${rawType}", Jumlah=${row[3]}`);
      }
      
      // DETEKSI TIPE - Lebih toleran
      if (type.includes('masuk') || type.includes('income') || type === 'pemasukan') {
        inc = Number(row[3]) || 0;
        debugInfo.incomeFound++;
      } else if (type.includes('keluar') || type.includes('expense') || type === 'pengeluaran') {
        exp = Number(row[3]) || 0;
        debugInfo.expenseFound++;
      } else {
        // Log unknown type
        if (debugInfo.errors.length < 5) {
          debugInfo.errors.push(`Unknown type: "${rawType}" in ${sheetName} row ${idx+2}`);
        }
      }

      allTransactions.push({
        project: sheetName,
        date: row[1], // Kolom B
        desc: row[2], // Kolom C
        category: row[7], // Kolom H
        income: inc,
        expense: exp
      });
    });
  });
  
  // Log debug summary
  Logger.log('=== DEBUG SUMMARY ===');
  Logger.log(`Sheets processed: ${debugInfo.sheetsProcessed}`);
  Logger.log(`Total rows read: ${debugInfo.rowsRead}`);
  Logger.log(`Income transactions: ${debugInfo.incomeFound}`);
  Logger.log(`Expense transactions: ${debugInfo.expenseFound}`);
  if (debugInfo.errors.length > 0) {
    Logger.log(`Errors: ${JSON.stringify(debugInfo.errors)}`);
  }
  
  return allTransactions;
}

// ==========================================
// BAGIAN 2: LOGIKA UI (DESIGNER)
// ==========================================

function renderHeader(sheet) {
  sheet.getRange("A1:M3").setBackground(SHEET_CONFIG.COLORS.HEADER_DARK);
  
  const titleCell = sheet.getRange("B2");
  titleCell.setValue("🏢 EXECUTIVE PROJECT DASHBOARD");
  titleCell.setFontSize(18).setFontWeight("bold").setFontColor("#FFFFFF");
  
  const subCell = sheet.getRange("B3");
  subCell.setValue("Last Updated: " + new Date().toLocaleString('id-ID'));
  subCell.setFontSize(9).setFontColor(SHEET_CONFIG.COLORS.TEXT_MUTED);
}

function renderScorecards(sheet, kpi) {
  const drawBox = (rangeStr, label, val, color) => {
    const rng = sheet.getRange(rangeStr);
    rng.breakApart(); // Reset merge

    // Setup Kotak
    rng.merge().setBackground(SHEET_CONFIG.COLORS.CARD_BG)
       .setBorder(true, true, true, true, null, null, "#E2E8F0", SpreadsheetApp.BorderStyle.SOLID_MEDIUM);
    
    // Strip Warna (Safe Mode)
    try {
      sheet.getRange(rng.getRow(), rng.getColumn(), 1, rng.getNumColumns()).setBackground(color);
      sheet.setRowHeight(rng.getRow(), 6); 
    } catch (e) {}

    // Teks
    const cell = sheet.getRange(rng.getRow() + 1, rng.getColumn());
    const formattedVal = "Rp " + Number(val).toLocaleString('id-ID');
    const fullText = label + "\n\n" + formattedVal;
    
    const richText = SpreadsheetApp.newRichTextValue()
      .setText(fullText)
      .setTextStyle(0, label.length, SpreadsheetApp.newTextStyle().setFontSize(10).setForegroundColor(SHEET_CONFIG.COLORS.TEXT_MUTED).build())
      .setTextStyle(label.length + 2, fullText.length, SpreadsheetApp.newTextStyle().setFontSize(16).setForegroundColor(SHEET_CONFIG.COLORS.TEXT_MAIN).build())
      .build();
      
    cell.setRichTextValue(richText);
    cell.setHorizontalAlignment("center").setVerticalAlignment("middle").setWrap(true);
  };

  drawBox("B5:E9", "SALDO AKTIF (CASH)", kpi.balance, SHEET_CONFIG.COLORS.ACCENT_BLUE);
  drawBox("G5:J9", "TOTAL PEMASUKAN", kpi.income, SHEET_CONFIG.COLORS.ACCENT_GREEN);
  drawBox("L5:O9", "TOTAL PENGELUARAN", kpi.expense, SHEET_CONFIG.COLORS.ACCENT_RED);
}

function renderProjectHealth(sheet, data, startRow) {
  let projSummary = {};
  data.forEach(d => {
    if (!projSummary[d.project]) projSummary[d.project] = {inc:0, exp:0};
    projSummary[d.project].inc += d.income;
    projSummary[d.project].exp += d.expense;
  });

  sheet.getRange(startRow, 2).setValue("A. TABEL PROJECT HEALTH (Status Proyek)")
       .setFontWeight("bold").setFontColor(SHEET_CONFIG.COLORS.HEADER_DARK);
  startRow++;

  const headers = ["NAMA PROYEK", "BUDGET (IN)", "TERPAKAI (OUT)", "SISA", "% PAKAI", "STATUS"];
  sheet.getRange(startRow, 2, 1, 6).setValues([headers])
       .setBackground(SHEET_CONFIG.COLORS.HEADER_DARK)
       .setFontColor("white").setFontWeight("bold").setHorizontalAlignment("center");

  let r = startRow + 1;
  const projects = Object.keys(projSummary);
  
  // Jika tidak ada project
  if (projects.length === 0) {
     sheet.getRange(r, 2).setValue("Belum ada data proyek.");
     return r + 1;
  }

  projects.forEach((p, i) => {
    const s = projSummary[p];
    const balance = s.inc - s.exp;
    const percent = s.inc === 0 ? 0 : (s.exp / s.inc);
    
    let status = "🟢 AMAN";
    let statusColor = "#DCFCE7"; let statusText = "#166534";
    
    if (percent > 0.8 && percent <= 1.0) { status = "🟡 WASPADA"; statusColor = "#FEF3C7"; statusText = "#B45309"; } 
    else if (percent > 1.0) { status = "🔴 OVER"; statusColor = "#FEE2E2"; statusText = "#991B1B"; }

    const rowRange = sheet.getRange(r, 2, 1, 6);
    rowRange.setValues([[p, s.inc, s.exp, balance, percent, status]]);
    rowRange.setBackground(i % 2 === 0 ? "#FFFFFF" : "#F8FAFC");
    
    // Safety check formatting
    sheet.getRange(r, 3, 1, 3).setNumberFormat('Rp #,##0');
    sheet.getRange(r, 6).setNumberFormat('0.0%');
    
    sheet.getRange(r, 7).setBackground(statusColor).setFontColor(statusText)
         .setFontWeight("bold").setHorizontalAlignment("center");

    r++;
  });
  
  // Border
  if (r > startRow + 1) {
    sheet.getRange(startRow, 2, r - startRow, 6)
         .setBorder(true, true, true, true, null, null, "#CBD5E1", SpreadsheetApp.BorderStyle.SOLID_MEDIUM);
  }

  return r;
}

function renderBigSpenders(sheet, data, startRow) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const spenders = data.filter(d => d.expense > 0)
                       .sort((a, b) => b.expense - a.expense)
                       .slice(0, 10);

  sheet.getRange(startRow, 2).setValue("B. BIG SPENDERS (Top 10 Pengeluaran)")
       .setFontWeight("bold").setFontColor(SHEET_CONFIG.COLORS.HEADER_DARK);
  startRow++;

  const headers = ["TANGGAL", "PROYEK", "DESKRIPSI", "JUMLAH"];
  sheet.getRange(startRow, 2, 1, 4).setValues([headers])
       .setBackground(SHEET_CONFIG.COLORS.HEADER_DARK)
       .setFontColor("white").setFontWeight("bold").setHorizontalAlignment("center");
  
  if (spenders.length === 0) {
    sheet.getRange(startRow + 1, 2).setValue("Belum ada data pengeluaran.");
    return startRow + 2;
  }

  let r = startRow + 1;
  spenders.forEach((d, i) => {
    let dateStr = d.date;
    try { dateStr = Utilities.formatDate(new Date(d.date), ss.getSpreadsheetTimeZone(), "dd MMM yyyy"); } catch(e) {}

    const rowRange = sheet.getRange(r, 2, 1, 4);
    rowRange.setValues([[dateStr, d.project, d.desc, d.expense]]);
    rowRange.setBackground(i % 2 === 0 ? "#FFFFFF" : "#F8FAFC");
    r++;
  });

  // Safe Formatting
  if (spenders.length > 0) {
    sheet.getRange(startRow + 1, 5, spenders.length, 1).setNumberFormat('Rp #,##0');
    sheet.getRange(startRow, 2, r - startRow, 4)
         .setBorder(true, true, true, true, null, null, "#CBD5E1", SpreadsheetApp.BorderStyle.SOLID_MEDIUM);
  }
  
  return r;
}

function renderChartDataSources(sheet, data, startRow) {
  sheet.getRange(startRow, 2).setValue("📈 SUMBER DATA GRAFIK (Untuk Insert Chart Manual)")
       .setFontSize(14).setFontWeight("bold").setFontColor(SHEET_CONFIG.COLORS.ACCENT_BLUE);
  startRow += 2;

  // 1. DATA KATEGORI (untuk Pie/Doughnut Chart)
  let catData = {};
  data.forEach(d => { 
    if(d.expense > 0) {
      let c = d.category || "Lainnya";
      if(!catData[c]) catData[c] = 0;
      catData[c] += d.expense;
    }
  });
  
  let r = startRow;
  sheet.getRange(r, 2, 1, 2).setValues([["KATEGORI", "TOTAL"]]).setBackground("#DBEAFE").setFontWeight("bold");
  r++;
  
  const catKeys = Object.keys(catData);
  if (catKeys.length > 0) {
    catKeys.forEach(k => {
      sheet.getRange(r, 2, 1, 2).setValues([[k, catData[k]]]);
      r++;
    });
    sheet.getRange(startRow+1, 3, catKeys.length, 1).setNumberFormat('Rp #,##0');
  } else {
    sheet.getRange(r, 2).setValue("- Kosong -");
    r++;
  }
  
  // 2. DATA CASHFLOW (untuk Line Chart)
  let monthData = {};
  data.forEach(d => {
    let dt = new Date(d.date);
    if (isNaN(dt.getTime())) return;
    let key = Utilities.formatDate(dt, SpreadsheetApp.getActive().getSpreadsheetTimeZone(), "yyyy-MM");
    if(!monthData[key]) monthData[key] = {inc:0, exp:0};
    monthData[key].inc += d.income;
    monthData[key].exp += d.expense;
  });
  
  r = startRow; 
  sheet.getRange(r, 5, 1, 3).setValues([["BULAN", "MASUK", "KELUAR"]]).setBackground("#D1FAE5").setFontWeight("bold");
  r++;

  const monthKeys = Object.keys(monthData).sort();
  if (monthKeys.length > 0) {
    monthKeys.forEach(k => {
      sheet.getRange(r, 5, 1, 3).setValues([[k, monthData[k].inc, monthData[k].exp]]);
      r++;
    });
    sheet.getRange(startRow+1, 6, monthKeys.length, 2).setNumberFormat('Rp #,##0');
  } else {
    sheet.getRange(r, 5).setValue("- Kosong -");
    r++;
  }

  // 3. DATA PROYEK (untuk Bar Chart)
  let projData = {};
  data.forEach(d => {
    if(!projData[d.project]) projData[d.project] = 0;
    projData[d.project] += d.expense;
  });
  
  r = startRow;
  sheet.getRange(r, 9, 1, 2).setValues([["PROYEK", "TOTAL PENGELUARAN"]]).setBackground("#FEF3C7").setFontWeight("bold");
  r++;

  const projKeys = Object.keys(projData);
  if (projKeys.length > 0) {
    projKeys.forEach(k => {
      sheet.getRange(r, 9, 1, 2).setValues([[k, projData[k]]]);
      r++;
    });
    sheet.getRange(startRow+1, 10, projKeys.length, 1).setNumberFormat('Rp #,##0');
  } else {
    sheet.getRange(r, 9).setValue("- Kosong -");
    r++;
  }
}

// ==========================================
// MENU KUSTOM
// ==========================================

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('📊 Dashboard')
    .addItem('🔄 Update Dashboard', 'updateDashboard')
    .addSeparator()
    .addItem('ℹ️ Bantuan', 'showHelp')
    .addToUi();
}

function showHelp() {
  const html = HtmlService.createHtmlOutput(`
    <h2>📊 Panduan Dashboard</h2>
    <h3>1. Update Data</h3>
    <p>Klik menu <b>📊 Dashboard > 🔄 Update Dashboard</b></p>
    
    <h3>2. Membuat Grafik (Sekali Saja)</h3>
    <p><b>Pie Chart:</b> Blok tabel KATEGORI > Insert > Chart > Doughnut</p>
    <p><b>Line Chart:</b> Blok tabel BULAN > Insert > Chart > Line</p>
    <p><b>Bar Chart:</b> Blok tabel PROYEK > Insert > Chart > Bar</p>
    
    <h3>3. Grafik Auto-Update</h3>
    <p>Setelah dibuat, grafik akan otomatis berubah setiap kali script dijalankan!</p>
  `).setWidth(400).setHeight(350);
  
  SpreadsheetApp.getUi().showModalDialog(html, 'Bantuan Dashboard');
}
