/**
 * Typed fetch wrapper for the local JobPilot service.
 *
 * Everything is same-origin (the service serves this bundle), so there are no CORS or
 * base-URL concerns. Errors are normalized into `ApiError` with the server's `detail`
 * message intact, because those messages are written for the user to read.
 */

export class ApiError extends Error {
  status: number
  detail: string

  constructor(status: number, detail: string) {
    super(detail || `HTTP ${status}`)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

type Options = Omit<RequestInit, 'body'> & { body?: unknown }

async function request<T>(path: string, options: Options = {}): Promise<T> {
  const { body, headers, ...rest } = options
  const init: RequestInit = {
    // Same-origin, but the session cookie is HttpOnly + SameSite=Lax — it still needs
    // an explicit opt-in on fetch, otherwise the browser won't attach it.
    credentials: 'include',
    ...rest,
    headers: {
      ...(body !== undefined && !(body instanceof FormData)
        ? { 'Content-Type': 'application/json' }
        : {}),
      ...(headers ?? {}),
    },
  }
  if (body !== undefined) {
    init.body = body instanceof FormData ? body : JSON.stringify(body)
  }

  let res: Response
  try {
    res = await fetch(path, init)
  } catch {
    // A dead fetch here almost always means the service stopped, so say that rather
    // than surfacing "Failed to fetch".
    throw new ApiError(0, 'Cannot reach the JobPilot service. Is it still running?')
  }

  if (!res.ok) {
    let detail = `Request failed (${res.status})`
    try {
      const payload = await res.json()
      if (typeof payload?.detail === 'string') detail = payload.detail
      else if (typeof payload?.error === 'string') detail = payload.error
    } catch {
      /* non-JSON error body — keep the generic message */
    }
    throw new ApiError(res.status, detail)
  }

  if (res.status === 204) return undefined as T
  const text = await res.text()
  return (text ? JSON.parse(text) : undefined) as T
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) => request<T>(path, { method: 'POST', body }),
  put: <T>(path: string, body?: unknown) => request<T>(path, { method: 'PUT', body }),
  patch: <T>(path: string, body?: unknown) => request<T>(path, { method: 'PATCH', body }),
  del: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
  upload: <T>(path: string, form: FormData) =>
    request<T>(path, { method: 'POST', body: form }),
}

/** Build a query string, dropping empty values so URLs stay readable. */
export function qs(params: Record<string, unknown>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue
    if (Array.isArray(value)) {
      value.filter((v) => v !== '' && v != null).forEach((v) => search.append(key, String(v)))
    } else {
      search.set(key, String(value))
    }
  }
  const out = search.toString()
  return out ? `?${out}` : ''
}
