export const CANONICAL_WALLET_COMPANY_PAIRS = [
  { wallet: 'CV HB(101)', company: 'HOLLA' },
  { wallet: 'CV HB(101)', company: 'HOJJA' },
  { wallet: 'TX SBY(216)', company: 'TEXTURIN-Surabaya' },
  { wallet: 'TX BALI(087)', company: 'TEXTURIN-Bali' },
] as const

export type CanonicalWalletCompanyPair = typeof CANONICAL_WALLET_COMPANY_PAIRS[number]

export const CANONICAL_WALLETS = [...new Set(CANONICAL_WALLET_COMPANY_PAIRS.map(({ wallet }) => wallet))]

export function canonicalCompaniesForWallet(wallet: string) {
  return CANONICAL_WALLET_COMPANY_PAIRS.filter((pair) => pair.wallet === wallet)
}

export function canonicalPair(wallet: string, company: string) {
  return CANONICAL_WALLET_COMPANY_PAIRS.find((pair) => pair.wallet === wallet && pair.company === company)
}

export function normalizeCanonicalPair(wallet: string, company: string) {
  const walletKey = wallet.trim().toLocaleLowerCase('id-ID')
  const companyKey = company.trim().toLocaleLowerCase('id-ID').replaceAll('-', ' ')
  const canonicalWallet = walletKey === 'cv hb' || walletKey === 'cv hb(101)' ? 'CV HB(101)'
    : walletKey === 'tx sby' || walletKey === 'tx sby(216)' ? 'TX SBY(216)'
      : ['tx bali', 'tx bali(087)'].includes(walletKey) ? 'TX BALI(087)'
        : wallet
  const canonicalCompany = ['holla', 'hollawall'].includes(companyKey) ? 'HOLLA'
    : ['hojja', 'holja'].includes(companyKey) ? 'HOJJA'
      : ['texturin surabaya', 'tx sby'].includes(companyKey) ? 'TEXTURIN-Surabaya'
        : ['texturin bali', 'tx bali'].includes(companyKey) ? 'TEXTURIN-Bali'
          : company
  return canonicalPair(canonicalWallet, canonicalCompany)
}

export const PROJECT_WRITE_CATEGORIES = ['Operasi Kantor', 'Bahan Alat', 'Gaji', 'Lain-lain'] as const
export const OFFICE_WRITE_CATEGORIES = ['Gaji', 'ListrikAir', 'Konsumsi', 'Peralatan', 'Lain Lain'] as const

export function isCanonicalWalletCompanyPair(wallet: string, company: string) {
  return Boolean(canonicalPair(wallet, company))
}