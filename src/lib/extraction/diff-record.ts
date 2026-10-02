import type { ClinicalRecord } from "../domain/types";

export type RecordFieldChange = {
  field_name: keyof ClinicalRecord;
  previous_value: unknown;
  new_value: unknown;
  source_segment_ids: string[];
};

export function diffClinicalRecord(
  current: ClinicalRecord,
  proposed: ClinicalRecord,
  evidence: Partial<Record<keyof ClinicalRecord, string[]>>,
  doctorEditedFields: Set<keyof ClinicalRecord> = new Set(),
): RecordFieldChange[] {
  return (Object.keys(proposed) as Array<keyof ClinicalRecord>).flatMap((fieldName) => {
    const next = proposed[fieldName];
    if (doctorEditedFields.has(fieldName) || next === null || (Array.isArray(next) && next.length === 0) || (typeof next === "object" && !Array.isArray(next) && Object.keys(next as object).length === 0)) return [];
    if (JSON.stringify(current[fieldName]) === JSON.stringify(next)) return [];
    return [{ field_name: fieldName, previous_value: current[fieldName], new_value: next, source_segment_ids: evidence[fieldName] ?? [] }];
  });
}
