export const CANONICAL_DEBT_REGISTRY = {
  'CV HB(101)': {
    walletId: '34d6db17-e205-5dfa-a3b8-90f0e0a3ec6b',
    businessUnitId: 'd3261754-6ee5-5d37-b0e2-79614da60abb',
  },
  'TX SBY(216)': {
    walletId: 'c23a1506-50d2-55a9-9469-8744b18fd85b',
    businessUnitId: '9f91cd70-58b6-52c8-aeaa-55ebf3006d13',
  },
  'TX BALI(087)': {
    walletId: '07743a6c-1ad0-5c00-9d96-0beaee4b8e01',
    businessUnitId: '0e21a9d9-4bda-5cb2-965b-bc2202e981ce',
  },
} as const

export function canonicalDebtIdentity(wallet: string) {
  const identity = CANONICAL_DEBT_REGISTRY[wallet as keyof typeof CANONICAL_DEBT_REGISTRY]
  if (!identity) throw new Error('Dompet hutang tidak memiliki identitas canonical.')
  return identity
}