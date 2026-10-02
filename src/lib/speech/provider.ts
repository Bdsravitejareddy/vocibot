import type { TranscriptDraft } from "../domain/types";

export interface SpeechToTextProvider {
  start(onSegment: (segment: TranscriptDraft) => void): Promise<void>;
  pause(): void;
  stop(): Promise<void>;
  onError?: (message: string) => void;
}
