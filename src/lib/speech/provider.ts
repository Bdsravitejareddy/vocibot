import type { TranscriptDraft } from "../domain/types";

export interface SpeechToTextProvider {
  start(onSegment: (segment: TranscriptDraft) => void): Promise<void>;
  pause(): void;
  stop(): Promise<void>;
  onError?: (message: string) => void;
  /** Unsettled live text that may still be revised; empty string clears it. */
  onPartial?: (text: string) => void;
}
