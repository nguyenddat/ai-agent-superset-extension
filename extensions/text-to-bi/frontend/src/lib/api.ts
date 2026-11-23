export const EXTENSION_API = "/extensions/text-to-bi/superset-text-to-bi"
const CSRF_TOKEN_API = "/api/v1/security/csrf_token/"

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message)
  }
}

// The extension answers `{code, message}`; Flask-AppBuilder's own 401/403 answers `{msg}`.
export async function errorFrom(response: Response, fallback: string) {
  const body = await response.json().catch(() => null)
  return new ApiError(response.status, body?.message || body?.msg || fallback)
}

export async function csrfToken() {
  const response = await fetch(CSRF_TOKEN_API, { credentials: "same-origin", headers: { Accept: "application/json" } })
  if (!response.ok) throw await errorFrom(response, `Không lấy được CSRF token (${response.status}).`)
  const body = await response.json()
  const token = body?.result ?? body?.csrf_token
  if (typeof token !== "string") throw new ApiError(response.status, "Không nhận được CSRF token.")
  return token
}

// Requests ride on the Superset session cookie; anything but a GET also needs Superset's CSRF token.
export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = init.method ?? "GET"
  const headers: Record<string, string> = { Accept: "application/json" }
  if (init.body) headers["Content-Type"] = "application/json"
  if (method !== "GET") headers["X-CSRFToken"] = await csrfToken()
  let response: Response
  try {
    response = await fetch(`${EXTENSION_API}${path}`, { ...init, credentials: "same-origin", headers })
  } catch {
    throw new ApiError(0, "Không kết nối được tới Superset.")
  }
  if (!response.ok) throw await errorFrom(response, "Đã xảy ra lỗi khi gọi API.")
  return response.status === 204 ? (undefined as T) : response.json()
}
