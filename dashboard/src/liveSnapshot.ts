import type { DashboardSnapshot } from './snapshot'

export interface LiveSnapshotLoadOptions {
  endpoint?: string
  signal?: AbortSignal
  request?: typeof fetch
}

/** Fail closed: never substitute browser/demo data for authenticated finance. */
export function loadLiveSnapshot(options?: LiveSnapshotLoadOptions): Promise<DashboardSnapshot>
export function loadLiveSnapshot(url?: string, request?: typeof fetch): Promise<DashboardSnapshot>
export async function loadLiveSnapshot(
  urlOrOptions: string | LiveSnapshotLoadOptions = '/admin/api/snapshot.php',
  injectedRequest: typeof fetch = fetch,
): Promise<DashboardSnapshot> {
  const options = typeof urlOrOptions === 'string' ? undefined : urlOrOptions
  const url = typeof urlOrOptions === 'string' ? urlOrOptions : (options?.endpoint ?? '/admin/api/snapshot.php')
  const request = options?.request ?? injectedRequest
  const target = new URL(url, window.location.origin)
  if (target.origin !== window.location.origin) throw new Error('Snapshot harus same-origin.')
  const response = await request(target.pathname + target.search, {
    credentials: 'same-origin', cache: 'no-store', redirect: 'error',
    headers: { Accept: 'application/json' },
    ...(options?.signal ? { signal: options.signal } : {}),
  })
  if (!response.ok) throw new Error(`Snapshot unavailable (${response.status})`)
  if (!response.headers.get('content-type')?.includes('application/json')) {
    throw new Error('Respons snapshot bukan JSON.')
  }
  const data: unknown = await response.json()
  if (!data || typeof data !== 'object') throw new Error('Snapshot tidak valid.')
  const value = data as Record<string, unknown>
  if (value.version !== 'dashboard.snapshot.v1' || !value.meta || !value.overview ||
      !['wallets', 'transactions', 'debts', 'cash_trend', 'project_summaries'].every(key => Array.isArray(value[key]))) {
    throw new Error('Kontrak snapshot tidak cocok.')
  }
  return data as DashboardSnapshot
}
