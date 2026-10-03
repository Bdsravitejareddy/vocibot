import type { ClinicalRecord, Speaker, TranscriptSegmentInput } from "../domain/types";

export type Recording = { id: string; started_at: string; duration_ms: number; sample_rate: number; language_code: string | null; sha256: string | null; original_sha256: string | null; format: "wav" | "flac" | "opus"; size_bytes: number; file_name: string; available: boolean };

export type ConsultationState = {
  id: string;
  /** Human-readable unique session ID, e.g. VB-20261002-K7Q3MD. */
  session_code: string;
  recordings: Recording[];
  /** English translation (from the audio) of a non-English consultation; the note is written from it. */
  translation?: Array<{ id: string; text: string; timestamp: string; sequence_number: number; speaker?: string }>;
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

/** Save the doctor's edits so far; the note stays unapproved, waiting in History. */
export function reviewLater(consultationId: string, record: ClinicalRecord) {
  return request<ConsultationState>(`/api/consultations/${consultationId}/review-later`, { method: "POST", body: JSON.stringify({ record }) });
}

/** Permanently delete a consultation with its transcript, record and audit trail. */
export function discardConsultation(consultationId: string) {
  return request<void>(`/api/consultations/${consultationId}`, { method: "DELETE" });
}

/** Regenerate the AI-filled note from the saved transcript; doctor edits are kept. */
export function reanalyseConsultation(consultationId: string) {
  return request<ConsultationState>(`/api/consultations/${consultationId}/reanalyse`, { method: "POST" });
}

/** Re-transcribe the stored audio with the current speech model, then refill the note. */
export function retranscribeConsultation(consultationId: string) {
  return request<ConsultationState>(`/api/consultations/${consultationId}/retranscribe`, { method: "POST" });
}

export function recordingAudioUrl(consultationId: string, recordingId: string) {
  return `${API_URL}/api/consultations/${consultationId}/recordings/${recordingId}/audio`;
}

export function listConsultations() {
  return request<ConsultationState[]>("/api/consultations");
}

export function getConsultation(consultationId: string) {
  return request<ConsultationState>(`/api/consultations/${consultationId}`);
}

export type { ClinicalRecord, Speaker };
