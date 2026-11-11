import { describe, expect, it } from 'vitest'

import {
  CANONICAL_WALLET_COMPANY_PAIRS,
  canonicalCompaniesForWallet,
  isCanonicalWalletCompanyPair,
  normalizeCanonicalPair,
} from './transactionMappings'

describe('canonical wallet and business-unit mapping', () => {
  it('models wallets as containers rather than duplicate business units', () => {
    expect(CANONICAL_WALLET_COMPANY_PAIRS).toEqual([
      { wallet: 'CV HB(101)', company: 'HOLLA' },
      { wallet: 'CV HB(101)', company: 'HOJJA' },
      { wallet: 'TX SBY(216)', company: 'TEXTURIN-Surabaya' },
      { wallet: 'TX BALI(087)', company: 'TEXTURIN-Bali' },
    ])
    expect(canonicalCompaniesForWallet('CV HB(101)').map(({ company }) => company)).toEqual(['HOLLA', 'HOJJA'])
    expect(canonicalCompaniesForWallet('TX SBY(216)').map(({ company }) => company)).toEqual(['TEXTURIN-Surabaya'])
  })

  it('rejects wallet aliases as writable business-unit identities', () => {
    expect(isCanonicalWalletCompanyPair('CV HB(101)', 'CV HB')).toBe(false)
    expect(isCanonicalWalletCompanyPair('TX SBY(216)', 'TX SBY')).toBe(false)
    expect(isCanonicalWalletCompanyPair('TX BALI(087)', 'TX BALI')).toBe(false)
  })

  it('normalizes unambiguous historical labels before a new write', () => {
    expect(normalizeCanonicalPair('TX SBY', 'TX SBY')).toEqual({ wallet: 'TX SBY(216)', company: 'TEXTURIN-Surabaya' })
    expect(normalizeCanonicalPair('TX Bali', 'TEXTURIN-Bali')).toEqual({ wallet: 'TX BALI(087)', company: 'TEXTURIN-Bali' })
    expect(normalizeCanonicalPair('CV HB', 'Holla')).toEqual({ wallet: 'CV HB(101)', company: 'HOLLA' })
    expect(normalizeCanonicalPair('CV HB(101)', 'CV HB')).toBeUndefined()
  })
})