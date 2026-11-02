export const CANONICAL_WALLET_COMPANY_PAIRS = [
  { wallet: 'CV HB(101)', company: 'HOLLA' },
  { wallet: 'CV HB(101)', company: 'HOJJA' },
  { wallet: 'CV HB(101)', company: 'CV HB' },
  { wallet: 'TX SBY(216)', company: 'TEXTURIN-Surabaya' },
  { wallet: 'TX SBY(216)', company: 'TX SBY' },
  { wallet: 'TX BALI(087)', company: 'TEXTURIN-Bali' },
  { wallet: 'TX BALI(087)', company: 'TX BALI' },
] as const

export const PROJECT_WRITE_CATEGORIES = ['Operasi Kantor', 'Bahan Alat', 'Gaji', 'Lain-lain'] as const
export const OFFICE_WRITE_CATEGORIES = ['Gaji', 'ListrikAir', 'Konsumsi', 'Peralatan', 'Lain Lain'] as const

export function isCanonicalWalletCompanyPair(wallet: string, company: string) {
  return CANONICAL_WALLET_COMPANY_PAIRS.some((pair) => pair.wallet === wallet && pair.company === company)
}