import type { TranscriptDraft } from "../domain/types";
import type { SpeechToTextProvider } from "./provider";

const DEMO_SCRIPT: Array<TranscriptDraft> = [
  { speaker: "DOCTOR", text: "What brings you in today?", timestamp: "2026-09-26T10:32:05Z" },
  { speaker: "PATIENT", text: "I've had fever for three days.", timestamp: "2026-09-26T10:32:09Z" },
  { speaker: "DOCTOR", text: "Any cough?", timestamp: "2026-09-26T10:32:14Z" },
  { speaker: "PATIENT", text: "Yes, a dry cough since yesterday.", timestamp: "2026-09-26T10:32:17Z" },
  { speaker: "DOCTOR", text: "Any breathing difficulty?", timestamp: "2026-09-26T10:32:22Z" },
  { speaker: "PATIENT", text: "No.", timestamp: "2026-09-26T10:32:25Z" },
  { speaker: "DOCTOR", text: "Are you taking any medication?", timestamp: "2026-09-26T10:32:30Z" },
  { speaker: "PATIENT", text: "Just paracetamol.", timestamp: "2026-09-26T10:32:34Z" },
];

export class DemoSpeechToTextProvider implements SpeechToTextProvider {
  private timer: ReturnType<typeof setInterval> | null = null;
  private index = 0;
  private sequence = 0;
  private paused = false;

  async start(onSegment: (segment: TranscriptDraft) => void) {
    this.paused = false;
    this.timer = setInterval(() => {
      if (this.paused || this.index >= DEMO_SCRIPT.length) return;
      const segment = DEMO_SCRIPT[this.index++];
      onSegment({ ...segment, id: `demo-${this.index}`, sequence_number: this.sequence++ });
      if (this.index >= DEMO_SCRIPT.length) this.stop();
    }, 450);
  }

  pause() { this.paused = true; }
  stop() { if (this.timer) { clearInterval(this.timer); this.timer = null; } }
}

export { DEMO_SCRIPT };
