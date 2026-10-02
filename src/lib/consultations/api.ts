import type { ClinicalRecord, Speaker, TranscriptSegmentInput } from "../domain/types";

export type ConsultationState = {
  id: string;
  status: "IN_PROGRESS" | "READY_FOR_REVIEW" | "APPROVED";
  started_at: string;
  ended_at: string | null;
  patient: { id: string; patient_identifier: string; name: string | null; age: number; sex: string };
  transcript: TranscriptSegmentInput[];
  record: ClinicalRecord;
  updates: Array<{ id: string; field_name: string; previous_value: unknown; new_value: unknown; source_segment_ids: string[]; updated_at: string; update_type: string }>;
  finalization_warnings?: string[];
};

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, { ...init, headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) } });
  if (!response.ok) throw new Error((await response.json().catch(() => null))?.detail ?? `Request failed: ${response.status}`);
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export function createConsultation(input: { patient_id: string; patient_name?: string; age: number; sex: string }) {
  return request<ConsultationState>("/api/consultations", { method: "POST", body: JSON.stringify(input) });
}

export function addSegment(consultationId: string, input: TranscriptSegmentInput) {
  return request<{ duplicate: boolean; consultation: ConsultationState }>(`/api/consultations/${consultationId}/segments`, { method: "POST", body: JSON.stringify(input) });
}

export function stopConsultation(consultationId: string, inferFinalRecord = false) {
  const query = inferFinalRecord ? "?infer_final_record=true" : "";
  return request<ConsultationState>(`/api/consultations/${consultationId}/stop${query}`, { method: "POST" });
}

export function approveConsultation(consultationId: string, record: ClinicalRecord) {
  return request<ConsultationState>(`/api/consultations/${consultationId}/approve`, { method: "POST", body: JSON.stringify({ record }) });
}

/** Permanently delete a consultation with its transcript, record and audit trail. */
export function discardConsultation(consultationId: string) {
  return request<void>(`/api/consultations/${consultationId}`, { method: "DELETE" });
}

export function listConsultations() {
  return request<ConsultationState[]>("/api/consultations");
}

export function getConsultation(consultationId: string) {
  return request<ConsultationState>(`/api/consultations/${consultationId}`);
}

export type { ClinicalRecord, Speaker };
