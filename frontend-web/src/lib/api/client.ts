import type { ApiEnvelope } from '../types/api'

export class ApiError extends Error {
  code: string
  status: number

  constructor(message: string, code: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.status = status
  }
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
  })

  const text = await response.text()
  const json = text ? (JSON.parse(text) as Partial<ApiEnvelope<T>> & { code?: string; message?: string }) : null

  if (!response.ok) {
    throw new ApiError(json?.message ?? '请求失败', json?.code ?? 'HTTP_ERROR', response.status)
  }

  if (!json || json.code !== 'OK' || json.data === undefined) {
    throw new ApiError(json?.message ?? '接口返回异常', json?.code ?? 'INVALID_ENVELOPE', response.status)
  }

  return json.data as T
}

export function buildQuery(params: Record<string, string | number | undefined | null>) {
  const search = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') {
      return
    }
    search.set(key, String(value))
  })
  const query = search.toString()
  return query ? `?${query}` : ''
}
