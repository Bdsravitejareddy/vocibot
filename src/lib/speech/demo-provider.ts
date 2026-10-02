import type { TranscriptDraft } from "../domain/types";
import type { SpeechToTextProvider } from "./provider";

const DEMO_SCRIPT: Array<TranscriptDraft> = [
  { speaker: "DOCTOR", text: "What brings you in today?", timestamp: "00:00:05" },
  { speaker: "PATIENT", text: "I've had fever for three days.", timestamp: "00:00:09" },
  { speaker: "DOCTOR", text: "Any cough?", timestamp: "00:00:14" },
  { speaker: "PATIENT", text: "Yes, a dry cough since yesterday.", timestamp: "00:00:17" },
  { speaker: "DOCTOR", text: "Any breathing difficulty?", timestamp: "00:00:22" },
  { speaker: "PATIENT", text: "No.", timestamp: "00:00:25" },
  { speaker: "DOCTOR", text: "Are you taking any medication?", timestamp: "00:00:30" },
  { speaker: "PATIENT", text: "Just paracetamol.", timestamp: "00:00:34" },
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
      onSegment({ ...segment, id: `demo-${this.index}`, timestamp: formatRelative(this.index * 450), sequence_number: this.sequence++ });
      if (this.index >= DEMO_SCRIPT.length) this.stop();
    }, 450);
  }

  pause() { this.paused = true; }
  async stop() { if (this.timer) { clearInterval(this.timer); this.timer = null; } }
}

export { DEMO_SCRIPT };

function formatRelative(milliseconds: number): string {
  const totalSeconds = Math.floor(milliseconds / 1000);
  return `00:${String(Math.floor(totalSeconds / 60)).padStart(2, "0")}:${String(totalSeconds % 60).padStart(2, "0")}`;
}
