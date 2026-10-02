/** API origin. Empty means the same origin as the page (packaged enterprise builds). */
export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

/** A readable message from a FastAPI error body (validation errors arrive as a list). */
function errorMessage(detail: unknown): string | undefined {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const messages = detail.map((item) => {
      const field = Array.isArray(item?.loc) ? item.loc[item.loc.length - 1] : undefined;
      return field && typeof item?.msg === "string" ? `${String(field).replaceAll("_", " ")}: ${item.msg}` : item?.msg;
    }).filter(Boolean);
    return messages.length ? messages.join("; ") : undefined;
  }
  return undefined;
}

/** JSON request carrying the sign-in cookie; a 401 sends the browser to the sign-in page. */
export async function apiRequest<T>(path: string, init?: RequestInit & { redirectOnUnauthorised?: boolean }): Promise<T> {
  const { redirectOnUnauthorised = true, ...options } = init ?? {};
  const response = await fetch(`${API_URL}${path}`, { ...options, credentials: "include", cache: "no-store", headers: { "Content-Type": "application/json", ...(options.headers ?? {}) } });
  if (response.status === 401 && redirectOnUnauthorised && typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
    window.location.assign(`/login?next=${encodeURIComponent(window.location.pathname + window.location.search)}`);
  }
  if (!response.ok) throw new ApiError(errorMessage((await response.json().catch(() => null))?.detail) ?? `Request failed: ${response.status}`, response.status);
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}
