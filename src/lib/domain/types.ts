export type ConsultationStatus = "IN_PROGRESS" | "READY_FOR_REVIEW" | "APPROVED";
export type RecordUpdateType = "AI_EXTRACTED" | "DOCTOR_EDITED" | "DOCTOR_APPROVED";
export type EvidenceStatus = "SUPPORTED" | "NEEDS_REVIEW" | "REJECTED" | "DOCTOR_EDITED" | "DOCTOR_APPROVED";
export type Speaker = "DOCTOR" | "PATIENT" | "UNKNOWN";

export type ClinicalRecord = {
  chief_complaint: string | null;
  duration: string | null;
  presenting_symptoms: string[];
  history_present_illness: string | null;
  relevant_negatives: string[];
  past_medical_history: string | null;
  medications: string[];
  allergies: string[];
  vitals: Record<string, string>;
  examination_findings: string[];
  assessment: string | null;
  plan: string | null;
  follow_up: string | null;
};

export type TranscriptSegmentInput = {
  id: string;
  speaker: Speaker;
  text: string;
  timestamp: string;
  sequence_number: number;
  language_code?: string | null;
  provisional?: boolean;
};

export type TranscriptDraft = Omit<TranscriptSegmentInput, "id" | "sequence_number"> & {
  id?: string;
  sequence_number?: number;
  start_ms?: number;
  end_ms?: number;
};

export type CandidateClinicalUpdate = {
  field_name: keyof ClinicalRecord;
  value: unknown;
  source_segment_ids: string[];
  speaker: Speaker;
  status: EvidenceStatus;
};

export type ExtractionResult = {
  proposed_record: ClinicalRecord;
  candidates: CandidateClinicalUpdate[];
};

export function createEmptyClinicalRecord(): ClinicalRecord {
  return {
    chief_complaint: null,
    duration: null,
    presenting_symptoms: [],
    history_present_illness: null,
    relevant_negatives: [],
    past_medical_history: null,
    medications: [],
    allergies: [],
    vitals: {},
    examination_findings: [],
    assessment: null,
    plan: null,
    follow_up: null,
  };
}
