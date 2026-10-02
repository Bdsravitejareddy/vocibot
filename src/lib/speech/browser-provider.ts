import type { TranscriptDraft } from "../domain/types";
import type { SpeechToTextProvider } from "./provider";

type Recognition = { continuous: boolean; interimResults: boolean; lang: string; start: () => void; stop: () => void; onresult: ((event: { results: ArrayLike<ArrayLike<{ isFinal: boolean; transcript: string; 0: { transcript: string } }>> }) => void) | null; onerror: ((event: { error: string }) => void) | null };

export class BrowserSpeechToTextProvider implements SpeechToTextProvider {
  private recognition: Recognition | null = null;
  private stream: MediaStream | null = null;
  private audioContext: AudioContext | null = null;
  private sequence = 0;
  private startedAt = 0;

  async start(onSegment: (segment: TranscriptDraft) => void) {
    this.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    this.startedAt = performance.now();
    this.audioContext = new AudioContext();
    const source = this.audioContext.createMediaStreamSource(this.stream);
    const analyser = this.audioContext.createAnalyser();
    source.connect(analyser); // Web Audio keeps the audio stream local; VAD/STT providers can consume this node later.
    const RecognitionClass = (window as Window & { SpeechRecognition?: new () => Recognition; webkitSpeechRecognition?: new () => Recognition }).SpeechRecognition ?? (window as Window & { webkitSpeechRecognition?: new () => Recognition }).webkitSpeechRecognition;
    if (!RecognitionClass) throw new Error("Browser speech recognition is unavailable");
    this.recognition = new RecognitionClass();
    this.recognition.continuous = true;
    this.recognition.interimResults = false;
    this.recognition.lang = "en-US";
    this.recognition.onresult = (event) => {
      for (const result of Array.from(event.results)) if (result[0].isFinal) onSegment({ speaker: "UNKNOWN", text: result[0].transcript, timestamp: formatRelative(performance.now() - this.startedAt), sequence_number: this.sequence++ });
    };
    this.recognition.start();
  }

  pause() { this.recognition?.stop(); }
  async stop() { this.recognition?.stop(); this.stream?.getTracks().forEach((track) => track.stop()); void this.audioContext?.close(); this.recognition = null; this.stream = null; this.audioContext = null; }
}

function formatRelative(milliseconds: number): string {
  const totalSeconds = Math.max(0, Math.floor(milliseconds / 1000));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}
