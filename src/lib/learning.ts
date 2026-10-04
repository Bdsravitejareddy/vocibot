const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

export type CloudLevel = "off" | "knowledge" | "snippets";
export type Numbers = { medicines_in_note: number; medicines_total: number; wrong_medicines: number; note_facts: number; note_facts_total: number; note_false_facts: number; unresolved_recent?: number };
export type LearningReport = { started: string; finished?: string; reason: string; cloud_level: CloudLevel; decision: "accepted" | "rejected" | "no change" | "failed"; summary?: string; error?: string; before?: Numbers; after?: Numbers; steps: Array<Record<string, unknown> & { step: string }> };
export type LearningStatus = { enabled: boolean; cloud_level: CloudLevel; gemini_keys: number; running: boolean; active_tips: Record<string, unknown>; last_report: LearningReport | null };
export type AuditEntry = { time: string; purpose: string; level: string; model: string; sent: string; received_chars?: number; error?: string };

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, { cache: "no-store", ...init, headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) } });
  if (!response.ok) throw new Error((await response.json().catch(() => null))?.detail ?? `Request failed: ${response.status}`);
  return response.json() as Promise<T>;
}

export const getLearning = () => request<LearningStatus>("/api/learning");
export const saveLearning = (changes: { enabled?: boolean; cloud_level?: CloudLevel }) => request<LearningStatus>("/api/learning", { method: "PUT", body: JSON.stringify(changes) });
export const runLearning = () => request<{ started: boolean }>("/api/learning/run", { method: "POST" });
export const getAudit = () => request<AuditEntry[]>("/api/learning/audit");
