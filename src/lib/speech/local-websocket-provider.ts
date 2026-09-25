import type { Speaker, TranscriptDraft } from "../domain/types";
import type { SpeechToTextProvider } from "./provider";

type LocalTranscriptEvent = { type: "transcript"; id?: string; text: string; speaker?: string; timestamp?: string; sequence_number?: number; start_ms?: number; end_ms?: number };

export function parseLocalEvent(payload: string): TranscriptDraft & { error?: string } | null {
  const event = JSON.parse(payload) as LocalTranscriptEvent | { type: string; message?: string };
  if (event.type === "error") return { text: "", timestamp: "", speaker: "UNKNOWN", error: (event as { message?: string }).message ?? "Local pipeline error" };
  if (event.type !== "transcript") return null;
  const transcript = event as LocalTranscriptEvent;
  return { id: transcript.id, text: transcript.text, speaker: (transcript.speaker ?? "UNKNOWN") as Speaker, timestamp: transcript.timestamp ?? new Date().toISOString(), sequence_number: transcript.sequence_number ?? 0, ...(transcript.start_ms === undefined ? {} : { start_ms: transcript.start_ms }), ...(transcript.end_ms === undefined ? {} : { end_ms: transcript.end_ms }) };
}

function websocketUrl(): string {
  const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";
  return `${apiUrl.replace(/^http/, "ws")}/api/consultations`;
}

export class LocalWebSocketSpeechProvider implements SpeechToTextProvider {
  onError?: (message: string) => void;
  private socket: WebSocket | null = null;
  private stream: MediaStream | null = null;
  private context: AudioContext | null = null;
  private processor: ScriptProcessorNode | null = null;
  private sequence = 0;

  constructor(private readonly consultationId: string) {}

  async start(onSegment: (segment: TranscriptDraft) => void) {
    this.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    this.context = new AudioContext();
    const source = this.context.createMediaStreamSource(this.stream);
    this.processor = this.context.createScriptProcessor(4096, 1, 1);
    this.socket = new WebSocket(`${websocketUrl()}/${this.consultationId}/audio`);
    await new Promise<void>((resolve, reject) => {
      const socket = this.socket!;
      socket.onopen = () => { socket.send(JSON.stringify({ sample_rate: this.context?.sampleRate ?? 16_000, channels: 1 })); resolve(); };
      socket.onerror = () => reject(new Error("Unable to connect to local audio pipeline."));
      socket.onmessage = (message) => {
        try {
          const event = parseLocalEvent(String(message.data));
          if (event?.error) this.onError?.(event.error);
          else if (event?.text) onSegment({ ...event, id: event.id ?? `local-${this.sequence}`, sequence_number: event.sequence_number ?? this.sequence++ });
        } catch (error) { this.onError?.(error instanceof Error ? error.message : "Invalid local pipeline event."); }
      };
    });
    this.processor.onaudioprocess = (event) => { if (this.socket?.readyState === WebSocket.OPEN) this.socket.send(event.inputBuffer.getChannelData(0).buffer); };
    source.connect(this.processor);
    this.processor.connect(this.context.destination);
  }

  pause() { this.processor?.disconnect(); }

  stop() {
    if (this.socket?.readyState === WebSocket.OPEN) this.socket.send(JSON.stringify({ type: "stop" }));
    this.processor?.disconnect(); this.stream?.getTracks().forEach((track) => track.stop()); void this.context?.close(); this.socket?.close();
    this.processor = null; this.stream = null; this.context = null; this.socket = null;
  }
}
