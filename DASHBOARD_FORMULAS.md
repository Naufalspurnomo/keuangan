# Dashboard Formulas - Holla & Hojja

Catatan:
- Jika pemisah rumus di spreadsheet kamu adalah `;`, ganti semua `,` menjadi `;`.
- Semua rumus ditempel di sel kiri dari blok angka (kalau merge, isi di sel kiri).
- Untuk CV HB, nama project diprefix `HOLLA -` atau `HOJJA -`.

## Peta Koordinat (sesuai layout)
DAILY REPORT: `A8:I8`  
MONTHLY REPORT: `K8:S8`

Label baris:
- Daily label di `A10:A15`
- Monthly label di `K10:K15`

Angka:
- Daily: Pemasukan `B10`, Pengeluaran `D10`, Profit `F10`
- Monthly: Pemasukan `L10`, Pengeluaran `N10`, Profit `P10`

---

## 1) Data_Agregat

Header (row 1):
Tanggal | Waktu | Tipe | Dompet | Jumlah | Project | Keterangan | Oleh | Source | MessageID | Kategori | Group

### Formula isi data (letakkan di `Data_Agregat!A2`)
```gs
=QUERY({
  {'CV HB(101)'!C9:C, 'CV HB(101)'!B9:B, ARRAYFORMULA(IF(ISBLANK('CV HB(101)'!C9:C), "", "Pemasukan")), ARRAYFORMULA(IF(ISBLANK('CV HB(101)'!C9:C), "", "CV HB(101)")), 'CV HB(101)'!D9:D, 'CV HB(101)'!E9:E, 'CV HB(101)'!F9:F, 'CV HB(101)'!G9:G, 'CV HB(101)'!H9:H, 'CV HB(101)'!I9:I, ARRAYFORMULA(IF(ISBLANK('CV HB(101)'!C9:C), "", ""))};
  {'CV HB(101)'!L9:L, 'CV HB(101)'!K9:K, ARRAYFORMULA(IF(ISBLANK('CV HB(101)'!L9:L), "", "Pengeluaran")), ARRAYFORMULA(IF(ISBLANK('CV HB(101)'!L9:L), "", "CV HB(101)")), 'CV HB(101)'!M9:M, 'CV HB(101)'!N9:N, 'CV HB(101)'!O9:O, 'CV HB(101)'!P9:P, 'CV HB(101)'!Q9:Q, 'CV HB(101)'!R9:R, ARRAYFORMULA(IF(ISBLANK('CV HB(101)'!L9:L), "", ""))};
  {'TX BALI(087)'!C9:C, 'TX BALI(087)'!B9:B, ARRAYFORMULA(IF(ISBLANK('TX BALI(087)'!C9:C), "", "Pemasukan")), ARRAYFORMULA(IF(ISBLANK('TX BALI(087)'!C9:C), "", "TX BALI(087)")), 'TX BALI(087)'!D9:D, 'TX BALI(087)'!E9:E, 'TX BALI(087)'!F9:F, 'TX BALI(087)'!G9:G, 'TX BALI(087)'!H9:H, 'TX BALI(087)'!I9:I, ARRAYFORMULA(IF(ISBLANK('TX BALI(087)'!C9:C), "", ""))};
  {'TX BALI(087)'!L9:L, 'TX BALI(087)'!K9:K, ARRAYFORMULA(IF(ISBLANK('TX BALI(087)'!L9:L), "", "Pengeluaran")), ARRAYFORMULA(IF(ISBLANK('TX BALI(087)'!L9:L), "", "TX BALI(087)")), 'TX BALI(087)'!M9:M, 'TX BALI(087)'!N9:N, 'TX BALI(087)'!O9:O, 'TX BALI(087)'!P9:P, 'TX BALI(087)'!Q9:Q, 'TX BALI(087)'!R9:R, ARRAYFORMULA(IF(ISBLANK('TX BALI(087)'!L9:L), "", ""))};
  {'TX SBY(216)'!C9:C, 'TX SBY(216)'!B9:B, ARRAYFORMULA(IF(ISBLANK('TX SBY(216)'!C9:C), "", "Pemasukan")), ARRAYFORMULA(IF(ISBLANK('TX SBY(216)'!C9:C), "", "TX SBY(216)")), 'TX SBY(216)'!D9:D, 'TX SBY(216)'!E9:E, 'TX SBY(216)'!F9:F, 'TX SBY(216)'!G9:G, 'TX SBY(216)'!H9:H, 'TX SBY(216)'!I9:I, ARRAYFORMULA(IF(ISBLANK('TX SBY(216)'!C9:C), "", ""))};
  {'TX SBY(216)'!L9:L, 'TX SBY(216)'!K9:K, ARRAYFORMULA(IF(ISBLANK('TX SBY(216)'!L9:L), "", "Pengeluaran")), ARRAYFORMULA(IF(ISBLANK('TX SBY(216)'!L9:L), "", "TX SBY(216)")), 'TX SBY(216)'!M9:M, 'TX SBY(216)'!N9:N, 'TX SBY(216)'!O9:O, 'TX SBY(216)'!P9:P, 'TX SBY(216)'!Q9:Q, 'TX SBY(216)'!R9:R, ARRAYFORMULA(IF(ISBLANK('TX SBY(216)'!L9:L), "", ""))};
  {'Operasional Kantor'!B2:B, ARRAYFORMULA(IF(ISBLANK('Operasional Kantor'!B2:B), "", "")), ARRAYFORMULA(IF(ISBLANK('Operasional Kantor'!B2:B), "", "Pengeluaran Operasional")), ARRAYFORMULA(IF(ISBLANK('Operasional Kantor'!B2:B), "", "Operasional Kantor")), 'Operasional Kantor'!C2:C, ARRAYFORMULA(IF(ISBLANK('Operasional Kantor'!B2:B), "", "")), 'Operasional Kantor'!D2:D, 'Operasional Kantor'!E2:E, 'Operasional Kantor'!F2:F, 'Operasional Kantor'!H2:H, 'Operasional Kantor'!G2:G}
}, "SELECT * WHERE Col1 IS NOT NULL", 0)
```

Catatan:
- Kalau mau Operasional dihitung sebagai pengeluaran biasa, ganti string `Pengeluaran Operasional` menjadi `Pengeluaran`.

### Kolom Group (letakkan di `Data_Agregat!L1` dan `Data_Agregat!L2`)
```gs
=ARRAYFORMULA(IF(A2:A="","",
IF(D2:D="Operasional Kantor","OPERASIONAL KANTOR",
IF(D2:D="TX BALI(087)","TX BALI",
IF(D2:D="TX SBY(216)","TX SURABAYA",
IF(D2:D="CV HB(101)",
 IF(REGEXMATCH(LOWER(F2:F),"^hojja(\\b|\\s*[-:])"),"HOJJA",
  IF(REGEXMATCH(LOWER(F2:F),"^holla(wall)?(\\b|\\s*[-:])"),"HOLLA","")
 ),
""))))))
```

---

## 2) DAILY REPORT (kiri)

Gunakan rumus per baris (hindari spill). Letakkan di `B10`, `D10`, `F10` lalu tarik sampai baris 15.

**B10 (Pemasukan)**
```gs
=SUMIFS(Data_Agregat!E:E,Data_Agregat!C:C,"Pemasukan",Data_Agregat!L:L,$A10,Data_Agregat!A:A,TODAY())
```

**D10 (Pengeluaran)**  
(menangkap `Pengeluaran` + `Pengeluaran Operasional`)
```gs
=SUM(SUMIFS(Data_Agregat!E:E,Data_Agregat!C:C,{"Pengeluaran","Pengeluaran Operasional"},Data_Agregat!L:L,$A10,Data_Agregat!A:A,TODAY()))
```

**F10 (Profit)**
```gs
=IFERROR(B10-D10,0)
```

---

## 3) MONTHLY REPORT (kanan)

Letakkan di `L10`, `N10`, `P10` lalu tarik sampai baris 15.

**L10 (Pemasukan)**
```gs
=SUMIFS(Data_Agregat!E:E,Data_Agregat!C:C,"Pemasukan",Data_Agregat!L:L,$K10,
Data_Agregat!A:A,">="&EOMONTH(TODAY(),-1)+1,Data_Agregat!A:A,"<="&EOMONTH(TODAY(),0))
```

**N10 (Pengeluaran)**  
(menangkap `Pengeluaran` + `Pengeluaran Operasional`)
```gs
=SUM(SUMIFS(Data_Agregat!E:E,Data_Agregat!C:C,{"Pengeluaran","Pengeluaran Operasional"},Data_Agregat!L:L,$K10,
Data_Agregat!A:A,">="&EOMONTH(TODAY(),-1)+1,Data_Agregat!A:A,"<="&EOMONTH(TODAY(),0)))
```

**P10 (Profit)**
```gs
=IFERROR(L10-N10,0)
```

---

## 4) Top Metrics - DAILY (kiri)

Letakkan nilai di kolom B (baris A18:A21).

**B18 (Pengeluaran Terbesar Hari ini)**
```gs
=IFERROR(INDEX(SORT(FILTER({Data_Agregat!$G:$G,Data_Agregat!$D:$D,Data_Agregat!$E:$E},
REGEXMATCH(Data_Agregat!$C:$C,"Pengeluaran"),Data_Agregat!$A:$A=TODAY()),3,FALSE),1),"-")
```

**B19 (Pemasukan Terbesar Hari ini)**
```gs
=IFERROR(INDEX(SORT(FILTER({Data_Agregat!$G:$G,Data_Agregat!$D:$D,Data_Agregat!$E:$E},
Data_Agregat!$C:$C="Pemasukan",Data_Agregat!$A:$A=TODAY()),3,FALSE),1),"-")
```

**B20 (Pengeluaran Kantor Terbesar)**
```gs
=IFERROR(INDEX(SORT(FILTER({Data_Agregat!$G:$G,Data_Agregat!$D:$D,Data_Agregat!$E:$E},
REGEXMATCH(Data_Agregat!$C:$C,"Pengeluaran"),Data_Agregat!$D:$D="Operasional Kantor",Data_Agregat!$A:$A=TODAY()),3,FALSE),1),"-")
```

**B21 (Pengeluaran Rumah Tangga Terbesar)**
```gs
=0
```

---

## 5) Top Metrics - MONTHLY (kanan)

Letakkan nilai di kolom L (baris K18:K21).

**L18 (Pengeluaran Terbesar Bulan ini)**
```gs
=IFERROR(INDEX(SORT(FILTER({Data_Agregat!$G:$G,Data_Agregat!$D:$D,Data_Agregat!$E:$E},
REGEXMATCH(Data_Agregat!$C:$C,"Pengeluaran"),
Data_Agregat!$A:$A,">="&EOMONTH(TODAY(),-1)+1,Data_Agregat!$A:$A,"<="&EOMONTH(TODAY(),0)),3,FALSE),1),"-")
```

**L19 (Pemasukan Terbesar Bulan ini)**
```gs
=IFERROR(INDEX(SORT(FILTER({Data_Agregat!$G:$G,Data_Agregat!$D:$D,Data_Agregat!$E:$E},
Data_Agregat!$C:$C="Pemasukan",
Data_Agregat!$A:$A,">="&EOMONTH(TODAY(),-1)+1,Data_Agregat!$A:$A,"<="&EOMONTH(TODAY(),0)),3,FALSE),1),"-")
```

**L20 (Pengeluaran Kantor Terbesar Bulan ini)**
```gs
=IFERROR(INDEX(SORT(FILTER({Data_Agregat!$G:$G,Data_Agregat!$D:$D,Data_Agregat!$E:$E},
REGEXMATCH(Data_Agregat!$C:$C,"Pengeluaran"),Data_Agregat!$D:$D="Operasional Kantor",
Data_Agregat!$A:$A,">="&EOMONTH(TODAY(),-1)+1,Data_Agregat!$A:$A,"<="&EOMONTH(TODAY(),0)),3,FALSE),1),"-")
```

**L21 (Pengeluaran Rumah Tangga Terbesar)**
```gs
=0
```

---

## 6) NO HUTANG (kanan bawah)

Asumsi tabel Hutang (sheet `HUTANG`):
Kolom:
`A` No | `B` Tanggal | `C` Nominal | `D` Keterangan | `E` Yang Hutang | `F` Yang Dihutangi | `G` Status | `H` Tgl Lunas | `I` MessageID

Catatan:
- Hanya status `OPEN` yang ditampilkan di dashboard.

Letakkan output di `J24` (akan mengisi `J24:N`):
```gs
=ARRAYFORMULA(IFERROR(FILTER(
 {HUTANG!A2:A, HUTANG!D2:D, HUTANG!E2:E, HUTANG!F2:F, HUTANG!B2:B},
 HUTANG!G2:G="OPEN"
), ""))
```

---

## 7) Kolom Penyesuaian (kiri bawah)

Isi manual sesuai kebutuhan:
- `A27:A29` dompet
- `B27:B29` saldo seharusnya
