import { useEffect } from "react";
import { getConsultation, type ConsultationState } from "./api";

export const PROCESSING_ACTIVE = new Set(["queued", "transcribing", "writing_note"]);

export function isProcessing(consultation: Pick<ConsultationState, "processing"> | null | undefined) {
  return Boolean(consultation?.processing && PROCESSING_ACTIVE.has(consultation.processing.status));
}

/** While the final transcript or note is being prepared, refresh the consultation every 2 s. */
export function useProcessingPoll(consultation: ConsultationState | null, onUpdate: (next: ConsultationState) => void) {
  const active = isProcessing(consultation);
  const id = consultation?.id;
  useEffect(() => {
    if (!active || !id) return;
    let cancelled = false;
    const timer = setInterval(() => {
      getConsultation(id).then((next) => { if (!cancelled) onUpdate(next); }).catch(() => undefined);
    }, 2000);
    return () => { cancelled = true; clearInterval(timer); };
  }, [active, id, onUpdate]);
}

export function processingMessage(consultation: ConsultationState): string {
  const processing = consultation.processing;
  const ahead = processing.jobs_ahead ? ` ${processing.jobs_ahead} consultation${processing.jobs_ahead === 1 ? "" : "s"} ahead of yours.` : "";
  switch (processing.status) {
    case "queued": return `Waiting to prepare the final transcript and note.${ahead}`;
    case "transcribing": return "Finalising the transcript from the recording…";
    case "writing_note": return "Writing the clinical note…";
    default: return "";
  }
}
