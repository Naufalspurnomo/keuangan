import type { DashboardEnvelope, Overview, TransactionPage } from './types'

export class ApiError extends Error {
  status: number
  code: string

  constructor(status: number, code: string, message: string) {
    super(message)
    this.status = status
    this.code = code
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<DashboardEnvelope<T>> {
  const response = await fetch(`/api/dashboard/v1${path}`, {
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', ...init?.headers },
    ...init,
  })
  const payload = (await response.json().catch(() => null)) as DashboardEnvelope<T> | null
  if (!response.ok || !payload) {
    const code = payload?.error?.code ?? 'request_failed'
    const message = payload?.error?.message ?? 'Permintaan tidak dapat diselesaikan.'
    throw new ApiError(response.status, code, message)
  }
  return payload
}

export async function login(email: string, password: string) {
  return request<{ identity: { email: string; role: string } }>('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  })
}

export const dashboardApi = {
  me: () => request<{ identity: { email: string; role: string } }>('/auth/me'),
  overview: (query = '') => request<Overview>(`/overview${query}`),
  transactions: (query = '') => request<TransactionPage>(`/transactions${query}`),
  resource: (name: string, query = '') => request<Record<string, unknown>>(`/${name}${query}`),
}
