import type {
  CompanyId,
  FinanceDebt,
  FinanceProject,
  FinanceTransaction,
  FinanceWorkspace,
  OfficeCategory,
  ProjectStatus,
  TransactionDirection,
  WalletId,
} from './financeWorkspace'

export const DEMO_SNAPSHOT_AT = '2026-10-30T09:00:00.000Z'

const DEMO_COMPANY_WALLET: Record<CompanyId, WalletId> = {
  Holla: 'CV HB',
  Hojja: 'CV HB',
  'Texturin Surabaya': 'TX SBY',
  'Texturin Bali': 'TX Bali',
}

type ProjectRow = readonly [
  id: string,
  name: string,
  company: CompanyId,
  status: ProjectStatus,
  startedOn: string,
  completedOn: string | null,
  client: string,
  contractValue: number | null,
  notes: string,
]

const DEMO_PROJECT_ROWS: readonly ProjectRow[] = [
  ['p24-alamanda', 'Alamanda Atrium', 'Holla', 'completed', '2024-01-08', '2024-01-20', 'PT Alamanda Niaga', 48_000_000, 'Renovasi atrium dan area penerima tamu.'],
  ['p24-bentala', 'Bentala Heritage', 'Hojja', 'completed', '2024-02-12', '2024-03-03', 'Bentala Hospitality', 72_500_000, 'Penyegaran interior bangunan heritage.'],
  ['p24-cakrawala', 'Cakrawala Resort', 'Texturin Bali', 'completed', '2024-03-03', '2024-04-17', 'Cakrawala Leisure', 95_000_000, 'Tekstur kamar dan koridor resort.'],
  ['p24-darmaga', 'Darmaga Office', 'Texturin Surabaya', 'completed', '2024-04-11', '2024-06-26', 'PT Darmaga Logistik', 128_000_000, 'Fit-out kantor operasional.'],
  ['p24-ekakarsa', 'Ekakarsa Residence', 'Holla', 'completed', '2024-05-20', '2024-09-15', 'Keluarga Pradana', 185_000_000, 'Interior rumah tinggal tiga lantai.'],
  ['p24-flamboyan', 'Flamboyan Pavilion', 'Hojja', 'completed', '2024-06-07', '2024-07-11', 'Flamboyan Medika', 64_000_000, 'Paviliun rawat jalan.'],
  ['p24-ganesha', 'Ganesha Studio', 'Texturin Surabaya', 'completed', '2024-07-18', '2024-10-04', 'Ganesha Kreatif', 83_500_000, 'Studio produksi konten.'],
  ['p24-harapan', 'Harapan Bakery', 'Texturin Bali', 'completed', '2024-08-02', '2024-08-12', 'Harapan Pangan Bali', 31_000_000, 'Finishing gerai roti.'],
  ['p24-intan', 'Intan Gallery', 'Holla', 'completed', '2024-09-14', '2024-10-10', 'Intan Art House', 57_000_000, 'Galeri seni dan ruang kurasi.'],
  ['p24-jati', 'Jati Learning Hub', 'Hojja', 'completed', '2024-10-20', '2025-01-17', 'Yayasan Jati Cendekia', 142_000_000, 'Ruang belajar lintas tahun.'],
  ['p24-kemuning', 'Kemuning Beach Club', 'Texturin Bali', 'completed', '2024-11-04', '2025-03-20', 'Kemuning Bahari', 225_000_000, 'Fasad, tekstur, dan area komunal.'],
  ['p24-lazuardi', 'Lazuardi Clinic', 'Texturin Surabaya', 'completed', '2024-12-09', '2025-01-23', 'Klinik Lazuardi', 88_000_000, 'Ruang konsultasi dan farmasi.'],

  ['p25-manggala', 'Manggala Townhouse', 'Holla', 'completed', '2025-01-06', '2025-02-14', 'Manggala Properti', 156_000_000, 'Rumah contoh kawasan baru.'],
  ['p25-naraya', 'Naraya Flagship', 'Hojja', 'completed', '2025-02-17', '2025-03-02', 'Naraya Retailindo', 52_000_000, 'Gerai flagship dua lantai.'],
  ['p25-oceania', 'Oceania Villas', 'Texturin Bali', 'completed', '2025-03-10', '2025-06-28', 'Oceania Living', 245_000_000, 'Tiga unit vila tropis.'],
  ['p25-puspita', 'Puspita Showroom', 'Texturin Surabaya', 'completed', '2025-04-04', '2025-05-01', 'Puspita Otomotif', 76_000_000, 'Dinding aksen dan area display.'],
  ['p25-quantum', 'Quantum Workspace', 'Holla', 'completed', '2025-05-12', '2025-07-30', 'Quantum Teknologi', 132_500_000, 'Kantor kolaboratif perusahaan teknologi.'],
  ['p25-rengganis', 'Rengganis Spa', 'Hojja', 'completed', '2025-06-09', '2025-06-20', 'Rengganis Wellness', 43_000_000, 'Ruang perawatan bernuansa hangat.'],
  ['p25-savanna', 'Savanna Eco Lodge', 'Texturin Bali', 'completed', '2025-07-21', '2026-01-31', 'Savanna Nusantara', 310_000_000, 'Lodge lintas tahun dengan material alami.'],
  ['p25-tirta', 'Tirta Culinary Lab', 'Texturin Surabaya', 'completed', '2025-08-08', '2025-10-18', 'Akademi Kuliner Tirta', 118_000_000, 'Dapur pelatihan dan ruang demo.'],
  ['p25-umbara', 'Umbara Headquarters', 'Holla', 'active', '2025-09-15', null, 'Umbara Energi', 420_000_000, 'Pengerjaan bertahap kantor pusat.'],
  ['p25-vistara', 'Vistara Convention', 'Hojja', 'active', '2025-10-06', null, 'Vistara Events', 365_000_000, 'Penataan convention hall dan foyer.'],
  ['p25-wijaya', 'Wijaya Courtyard', 'Texturin Bali', 'completed', '2025-11-03', '2026-02-16', 'Wijaya Hospitality', 198_000_000, 'Courtyard hotel dan area sarapan.'],
  ['p25-xanadu', 'Xanadu Experience Center', 'Texturin Surabaya', 'active', '2025-12-01', null, 'Xanadu Elektronik', 275_000_000, 'Experience center regional.'],

  ['p26-yasmin', 'Yasmin Pop-up', 'Holla', 'completed', '2026-01-10', '2026-01-20', 'Yasmin Mode', 36_000_000, 'Pop-up store musim awal tahun.'],
  ['p26-zamrud', 'Zamrud Dental', 'Hojja', 'completed', '2026-02-01', '2026-02-25', 'Zamrud Dental Care', 69_000_000, 'Klinik gigi dua ruang tindakan.'],
  ['p26-andara', 'Andara Suites', 'Texturin Bali', 'completed', '2026-03-05', '2026-04-19', 'Andara Hospitality', 112_000_000, 'Suite hotel dan koridor privat.'],
  ['p26-baskara', 'Baskara Campus', 'Texturin Surabaya', 'completed', '2026-04-10', '2026-06-25', 'Institut Baskara', 174_000_000, 'Lobi kampus dan student lounge.'],
  ['p26-cempaka', 'Cempaka Clubhouse', 'Holla', 'completed', '2026-05-01', '2026-09-10', 'Cempaka Residence', 238_000_000, 'Clubhouse kawasan hunian.'],
  ['p26-dahayu', 'Dahayu Boutique Hotel', 'Hojja', 'active', '2026-07-01', null, 'Dahayu Hospitality', 286_000_000, 'Renovasi hotel butik berjalan.'],
  ['p26-elok', 'Elok Seaside Restaurant', 'Texturin Bali', 'active', '2026-08-15', null, 'Elok Boga Bahari', 164_000_000, 'Restoran tepi pantai.'],
  ['p26-fajar', 'Fajar Distribution Hub', 'Texturin Surabaya', 'active', '2026-09-15', null, 'Fajar Distribusi', 146_000_000, 'Area kantor dan penerimaan gudang.'],
  ['p26-griya', 'Griya Wellness Center', 'Holla', 'active', '2026-10-10', null, 'Griya Sehat Indonesia', 98_000_000, 'Wellness center fase konstruksi.'],
  ['p26-harmoni', 'Harmoni Kids Library', 'Hojja', 'active', '2026-10-21', null, 'Yayasan Harmoni Anak', 54_000_000, 'Perpustakaan anak tahap awal.'],
  ['p26-indrapura', 'Indrapura Co-living', 'Texturin Bali', 'planned', '2026-11-10', null, 'Indrapura Living', 330_000_000, 'Mobilisasi direncanakan November.'],
  ['p26-jenggala', 'Jenggala Innovation Lab', 'Texturin Surabaya', 'planned', '2026-12-05', null, 'Jenggala Inovasi', null, 'Menunggu finalisasi nilai kontrak.'],
]

type TransactionRow = readonly [
  id: string,
  projectId: string,
  date: string,
  direction: TransactionDirection,
  amount: number,
  notes: string,
]

const DEMO_TRANSACTION_ROWS: readonly TransactionRow[] = [
  ['t24-alamanda-01', 'p24-alamanda', '2024-01-08', 'income', 18_000_000, 'Uang muka Alamanda'],
  ['t24-alamanda-02', 'p24-alamanda', '2024-01-10', 'expense', 6_500_000, 'Material kayu atrium'],
  ['t24-alamanda-03', 'p24-alamanda', '2024-01-13', 'expense', 4_200_000, 'Tenaga lapangan atrium'],
  ['t24-alamanda-04', 'p24-alamanda', '2024-01-17', 'income', 16_000_000, 'Termin 1 Alamanda'],
  ['t24-alamanda-05', 'p24-alamanda', '2024-01-20', 'income', 14_000_000, 'Pelunasan Alamanda'],
  ['t24-bentala-01', 'p24-bentala', '2024-02-12', 'income', 28_000_000, 'Uang muka Bentala'],
  ['t24-bentala-02', 'p24-bentala', '2024-02-21', 'expense', 17_500_000, 'Material heritage Bentala'],
  ['t24-bentala-03', 'p24-bentala', '2024-03-03', 'income', 31_000_000, 'Pelunasan Bentala'],
  ['t24-cakrawala-01', 'p24-cakrawala', '2024-03-03', 'income', 22_000_000, 'Uang muka Cakrawala'],
  ['t24-cakrawala-02', 'p24-cakrawala', '2024-03-14', 'expense', 24_500_000, 'Material tekstur resort'],
  ['t24-cakrawala-03', 'p24-cakrawala', '2024-04-02', 'expense', 13_000_000, 'Tenaga lapangan resort'],
  ['t24-cakrawala-04', 'p24-cakrawala', '2024-04-17', 'expense', 6_500_000, 'Perbaikan akhir Cakrawala'],
  ['t24-darmaga-01', 'p24-darmaga', '2024-04-11', 'income', 51_000_000, 'Uang muka Darmaga'],
  ['t24-darmaga-02', 'p24-darmaga', '2024-06-26', 'expense', 34_000_000, 'Pelaksana fit-out Darmaga'],
  ['t24-ekakarsa-01', 'p24-ekakarsa', '2024-05-20', 'income', 60_000_000, 'Uang muka Ekakarsa'],
  ['t24-ekakarsa-02', 'p24-ekakarsa', '2024-06-18', 'expense', 25_000_000, 'Material lantai Ekakarsa'],
  ['t24-ekakarsa-03', 'p24-ekakarsa', '2024-08-01', 'income', 55_000_000, 'Termin 2 Ekakarsa'],
  ['t24-ekakarsa-04', 'p24-ekakarsa', '2024-09-15', 'expense', 31_000_000, 'Finishing Ekakarsa'],
  ['t24-flamboyan-01', 'p24-flamboyan', '2024-06-07', 'income', 24_000_000, 'Uang muka Flamboyan'],
  ['t24-harapan-01', 'p24-harapan', '2024-08-02', 'income', 18_000_000, 'Pembayaran Harapan Bakery'],
  ['t24-harapan-02', 'p24-harapan', '2024-08-10', 'expense', 7_500_000, 'Finishing gerai Harapan'],
  ['t24-intan-01', 'p24-intan', '2024-09-14', 'income', 22_000_000, 'Uang muka Intan Gallery'],
  ['t24-intan-02', 'p24-intan', '2024-09-25', 'expense', 11_000_000, 'Panel galeri Intan'],
  ['t24-intan-03', 'p24-intan', '2024-10-10', 'income', 20_000_000, 'Pelunasan Intan Gallery'],
  ['t24-jati-01', 'p24-jati', '2024-10-20', 'income', 48_000_000, 'Uang muka Jati'],
  ['t24-jati-02', 'p24-jati', '2024-11-19', 'expense', 26_000_000, 'Material ruang belajar'],
  ['t24-jati-03', 'p24-jati', '2024-12-20', 'income', 42_000_000, 'Termin lintas tahun Jati'],
  ['t24-jati-04', 'p24-jati', '2025-01-17', 'expense', 18_500_000, 'Penyelesaian Jati'],
  ['t24-kemuning-01', 'p24-kemuning', '2024-11-04', 'income', 75_000_000, 'Uang muka Kemuning'],
  ['t24-kemuning-02', 'p24-kemuning', '2025-01-08', 'expense', 51_000_000, 'Material area komunal'],
  ['t24-kemuning-03', 'p24-kemuning', '2025-03-20', 'income', 84_000_000, 'Pelunasan Kemuning'],
  ['t24-lazuardi-01', 'p24-lazuardi', '2024-12-09', 'income', 35_000_000, 'Uang muka Lazuardi'],
  ['t24-lazuardi-02', 'p24-lazuardi', '2025-01-23', 'expense', 21_000_000, 'Kabinet farmasi Lazuardi'],

  ['t25-manggala-01', 'p25-manggala', '2025-01-06', 'income', 52_000_000, 'Uang muka Manggala'],
  ['t25-manggala-02', 'p25-manggala', '2025-01-24', 'expense', 29_000_000, 'Material rumah contoh'],
  ['t25-manggala-03', 'p25-manggala', '2025-02-14', 'income', 48_000_000, 'Pelunasan Manggala'],
  ['t25-naraya-01', 'p25-naraya', '2025-02-17', 'income', 20_000_000, 'Uang muka Naraya'],
  ['t25-naraya-02', 'p25-naraya', '2025-03-02', 'expense', 12_500_000, 'Display flagship Naraya'],
  ['t25-oceania-01', 'p25-oceania', '2025-03-10', 'income', 82_000_000, 'Uang muka Oceania'],
  ['t25-oceania-02', 'p25-oceania', '2025-04-28', 'expense', 47_000_000, 'Tekstur vila pertama'],
  ['t25-oceania-03', 'p25-oceania', '2025-05-30', 'income', 76_000_000, 'Termin 2 Oceania'],
  ['t25-oceania-04', 'p25-oceania', '2025-06-28', 'expense', 39_000_000, 'Finishing tiga vila'],
  ['t25-puspita-01', 'p25-puspita', '2025-04-04', 'income', 29_000_000, 'Uang muka Puspita'],
  ['t25-puspita-02', 'p25-puspita', '2025-05-01', 'expense', 17_000_000, 'Dinding aksen showroom'],
  ['t25-quantum-01', 'p25-quantum', '2025-05-12', 'income', 44_000_000, 'Uang muka Quantum'],
  ['t25-quantum-02', 'p25-quantum', '2025-06-08', 'expense', 24_000_000, 'Partisi workspace Quantum'],
  ['t25-quantum-03', 'p25-quantum', '2025-07-30', 'income', 52_000_000, 'Pelunasan Quantum'],
  ['t25-rengganis-01', 'p25-rengganis', '2025-06-09', 'income', 16_000_000, 'Uang muka Rengganis'],
  ['t25-savanna-01', 'p25-savanna', '2025-07-21', 'income', 100_000_000, 'Uang muka Savanna'],
  ['t25-savanna-02', 'p25-savanna', '2025-09-15', 'expense', 58_000_000, 'Material alami Savanna'],
  ['t25-savanna-03', 'p25-savanna', '2025-12-12', 'income', 92_000_000, 'Termin lintas tahun Savanna'],
  ['t25-savanna-04', 'p25-savanna', '2026-01-31', 'expense', 46_000_000, 'Penyelesaian lodge Savanna'],
  ['t25-tirta-01', 'p25-tirta', '2025-08-08', 'income', 42_000_000, 'Uang muka Tirta'],
  ['t25-tirta-02', 'p25-tirta', '2025-09-11', 'expense', 28_000_000, 'Peralatan tetap culinary lab'],
  ['t25-tirta-03', 'p25-tirta', '2025-10-18', 'income', 39_000_000, 'Pelunasan Tirta'],
  ['t25-umbara-01', 'p25-umbara', '2025-09-15', 'income', 120_000_000, 'Uang muka Umbara'],
  ['t25-umbara-02', 'p25-umbara', '2026-02-02', 'expense', 63_000_000, 'Material fase satu Umbara'],
  ['t25-umbara-03', 'p25-umbara', '2026-08-18', 'income', 95_000_000, 'Termin 2 Umbara'],
  ['t25-vistara-01', 'p25-vistara', '2025-10-06', 'income', 110_000_000, 'Uang muka Vistara'],
  ['t25-vistara-02', 'p25-vistara', '2026-03-07', 'expense', 71_000_000, 'Pekerjaan foyer Vistara'],
  ['t25-wijaya-01', 'p25-wijaya', '2025-11-03', 'income', 64_000_000, 'Uang muka Wijaya'],
  ['t25-wijaya-02', 'p25-wijaya', '2026-01-12', 'expense', 37_000_000, 'Material courtyard Wijaya'],
  ['t25-wijaya-03', 'p25-wijaya', '2026-02-16', 'income', 70_000_000, 'Pelunasan Wijaya'],
  ['t25-xanadu-01', 'p25-xanadu', '2025-12-01', 'income', 90_000_000, 'Uang muka Xanadu'],
  ['t25-xanadu-02', 'p25-xanadu', '2026-05-20', 'expense', 48_000_000, 'Display interaktif Xanadu'],

  ['t26-yasmin-01', 'p26-yasmin', '2026-01-10', 'income', 15_000_000, 'Uang muka Yasmin'],
  ['t26-yasmin-02', 'p26-yasmin', '2026-01-20', 'expense', 8_000_000, 'Bongkar pasang pop-up Yasmin'],
  ['t26-zamrud-01', 'p26-zamrud', '2026-02-01', 'income', 26_000_000, 'Uang muka Zamrud'],
  ['t26-zamrud-02', 'p26-zamrud', '2026-02-25', 'expense', 15_000_000, 'Kabinet klinik Zamrud'],
  ['t26-andara-01', 'p26-andara', '2026-03-05', 'income', 38_000_000, 'Uang muka Andara'],
  ['t26-andara-02', 'p26-andara', '2026-03-26', 'expense', 22_000_000, 'Material suite Andara'],
  ['t26-andara-03', 'p26-andara', '2026-04-19', 'income', 41_000_000, 'Pelunasan Andara'],
  ['t26-baskara-01', 'p26-baskara', '2026-04-10', 'income', 58_000_000, 'Uang muka Baskara'],
  ['t26-baskara-02', 'p26-baskara', '2026-05-09', 'expense', 32_000_000, 'Material student lounge'],
  ['t26-baskara-03', 'p26-baskara', '2026-06-25', 'income', 61_000_000, 'Pelunasan Baskara'],
  ['t26-cempaka-01', 'p26-cempaka', '2026-05-01', 'income', 78_000_000, 'Uang muka Cempaka'],
  ['t26-cempaka-02', 'p26-cempaka', '2026-06-12', 'expense', 42_000_000, 'Material clubhouse Cempaka'],
  ['t26-cempaka-03', 'p26-cempaka', '2026-08-03', 'income', 70_000_000, 'Termin 2 Cempaka'],
  ['t26-cempaka-04', 'p26-cempaka', '2026-09-10', 'expense', 35_000_000, 'Finishing Cempaka'],
  ['t26-dahayu-01', 'p26-dahayu', '2026-07-01', 'income', 92_000_000, 'Uang muka Dahayu'],
  ['t26-dahayu-02', 'p26-dahayu', '2026-08-14', 'expense', 47_000_000, 'Material kamar Dahayu'],
  ['t26-dahayu-03', 'p26-dahayu', '2026-10-14', 'expense', 24_000_000, 'Tenaga lapangan Dahayu'],
  ['t26-elok-01', 'p26-elok', '2026-08-15', 'income', 54_000_000, 'Uang muka Elok'],
  ['t26-elok-02', 'p26-elok', '2026-09-09', 'expense', 29_000_000, 'Material area makan Elok'],
  ['t26-elok-03', 'p26-elok', '2026-10-25', 'income', 43_000_000, 'Termin 1 Elok'],
  ['t26-fajar-01', 'p26-fajar', '2026-09-15', 'income', 48_000_000, 'Uang muka Fajar'],
  ['t26-fajar-02', 'p26-fajar', '2026-10-18', 'expense', 26_000_000, 'Partisi hub Fajar'],
  ['t26-griya-01', 'p26-griya', '2026-10-10', 'income', 32_000_000, 'Uang muka Griya'],
  ['t26-griya-02', 'p26-griya', '2026-10-27', 'expense', 14_000_000, 'Material awal Griya'],
  ['t26-harmoni-01', 'p26-harmoni', '2026-10-21', 'income', 18_000_000, 'Uang muka Harmoni'],
]

const OFFICE_TRANSACTION_ROWS: readonly (readonly [string, string, WalletId, OfficeCategory, number, string])[] = [
  ['office-01', '2026-01-08', 'CV HB', 'Listrik & utilitas', 500_000, 'Listrik kantor Januari'],
  ['office-02', '2026-02-03', 'TX SBY', 'Peralatan kantor', 1_850_000, 'Printer dan tinta Surabaya'],
  ['office-03', '2026-03-05', 'TX Bali', 'Sewa & fasilitas', 6_500_000, 'Sewa ruang kerja Bali'],
  ['office-04', '2026-06-12', 'CV HB', 'Gaji & honor', 8_750_000, 'Honor administrasi semester satu'],
]

const DEMO_DEBTS: readonly FinanceDebt[] = [
  { id: 'demo-debt-1', date: '2026-02-14', borrower: 'TX Bali', lender: 'CV HB', amount: 25_000_000, repaid: 10_000_000, notes: 'Dukungan kas proyek Bali', created_at: '2026-02-14T08:00:00.000Z', updated_at: '2026-03-10T08:00:00.000Z' },
  { id: 'demo-debt-2', date: '2026-04-03', borrower: 'TX SBY', lender: 'CV HB', amount: 12_500_000, repaid: 12_500_000, notes: 'Pendanaan material sementara', created_at: '2026-04-03T08:00:00.000Z', updated_at: '2026-05-01T08:00:00.000Z' },
]

function createProjects(): FinanceProject[] {
  return DEMO_PROJECT_ROWS.map(([id, name, company, status, started_on, completed_on, client, contract_value, notes]) => ({
    id,
    name,
    company,
    wallet: DEMO_COMPANY_WALLET[company],
    status,
    started_on,
    completed_on,
    client,
    contract_value,
    notes,
    created_at: `${started_on}T08:00:00.000Z`,
    updated_at: `${completed_on ?? started_on}T08:00:00.000Z`,
  }))
}

function createProjectTransactions(projects: FinanceProject[]): FinanceTransaction[] {
  const projectMap = new Map(projects.map((project) => [project.id, project]))
  return DEMO_TRANSACTION_ROWS.map(([id, projectId, date, direction, amount, notes]) => {
    const project = projectMap.get(projectId)
    if (!project) throw new Error(`Unknown demo project ${projectId}`)
    return {
      id,
      date,
      direction,
      amount,
      scope: 'project',
      wallet: project.wallet,
      company: project.company,
      project_id: project.id,
      office_category: null,
      notes,
      created_at: `${date}T09:00:00.000Z`,
      updated_at: `${date}T09:00:00.000Z`,
    }
  })
}

function createOfficeTransactions(): FinanceTransaction[] {
  return OFFICE_TRANSACTION_ROWS.map(([id, date, wallet, office_category, amount, notes]) => ({
    id,
    date,
    direction: 'expense',
    amount,
    scope: 'office',
    wallet,
    company: null,
    project_id: null,
    office_category,
    notes,
    created_at: `${date}T08:00:00.000Z`,
    updated_at: `${date}T08:00:00.000Z`,
  }))
}

export function seedDemoFinanceWorkspace(): FinanceWorkspace {
  const projects = createProjects()
  return {
    version: 3,
    mode: 'demo',
    projects,
    transactions: [...createProjectTransactions(projects), ...createOfficeTransactions()],
    debts: DEMO_DEBTS.map((debt) => ({ ...debt })),
    audit: [],
    updated_at: DEMO_SNAPSHOT_AT,
  }
}
