const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

export type Language = { code: string; name: string };
export type LanguageSettings = { enabled: string[]; available: Language[] };

async function request(init?: RequestInit): Promise<LanguageSettings> {
  const response = await fetch(`${API_URL}/api/settings/languages`, { cache: "no-store", ...init, headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) } });
  if (!response.ok) throw new Error((await response.json().catch(() => null))?.detail ?? `Request failed: ${response.status}`);
  return response.json() as Promise<LanguageSettings>;
}

/** The languages the clinic uses; auto-detect only chooses among these. */
export const getLanguageSettings = () => request();
export const saveEnabledLanguages = (enabled: string[]) => request({ method: "PUT", body: JSON.stringify({ enabled }) });
