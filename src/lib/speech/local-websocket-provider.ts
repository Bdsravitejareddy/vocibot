import type { Speaker, TranscriptDraft } from "../domain/types";
import type { SpeechToTextProvider } from "./provider";

type LocalTranscriptEvent = { type: "transcript"; id?: string; text: string; speaker?: string; timestamp?: string; sequence_number?: number; start_ms?: number; end_ms?: number; language_code?: string | null };

export function parseLocalEvent(payload: string): TranscriptDraft & { error?: string } | null {
  const event = JSON.parse(payload) as LocalTranscriptEvent | { type: string; message?: string };
  if (event.type === "error") return { text: "", timestamp: "", speaker: "UNKNOWN", error: (event as { message?: string }).message ?? "Local pipeline error" };
  if (event.type !== "transcript") return null;
  const transcript = event as LocalTranscriptEvent;
  return { id: transcript.id, text: transcript.text, speaker: (transcript.speaker ?? "UNKNOWN") as Speaker, timestamp: transcript.timestamp ?? formatRelative(transcript.start_ms ?? 0), sequence_number: transcript.sequence_number ?? 0, provisional: true, ...(transcript.start_ms === undefined ? {} : { start_ms: transcript.start_ms }), ...(transcript.end_ms === undefined ? {} : { end_ms: transcript.end_ms }), ...(transcript.language_code === undefined ? {} : { language_code: transcript.language_code }) };
}

function formatRelative(milliseconds: number): string {
  const totalSeconds = Math.max(0, Math.floor(milliseconds / 1000));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

function websocketUrl(): string {
  const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";
  return `${apiUrl.replace(/^http/, "ws")}/api/consultations`;
}

export class LocalWebSocketSpeechProvider implements SpeechToTextProvider {
  onError?: (message: string) => void;
  onPartial?: (text: string) => void;
  private socket: WebSocket | null = null;
  private stream: MediaStream | null = null;
  private context: AudioContext | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  private processor: ScriptProcessorNode | null = null;
  private sequence = 0;
  private stopping = false;
  private stopped = Promise.resolve();

  constructor(private readonly consultationId: string, private readonly language = "auto") {}

  async start(onSegment: (segment: TranscriptDraft) => void) {
    if (this.socket?.readyState === WebSocket.OPEN && this.context && this.processor) {
      this.processor.connect(this.context.destination);
      return;
    }
    this.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    this.context = new AudioContext();
    this.source = this.context.createMediaStreamSource(this.stream);
    this.processor = this.context.createScriptProcessor(4096, 1, 1);
    this.socket = new WebSocket(`${websocketUrl()}/${this.consultationId}/audio`);
    // Capture from the moment the microphone opens: the backend needs a moment
    // to load its model, and the clinician's first words must not be lost.
    const pending: ArrayBuffer[] = [];
    let streaming = false;
    this.processor.onaudioprocess = (event) => {
      const frame = event.inputBuffer.getChannelData(0).slice().buffer;
      if (streaming && this.socket?.readyState === WebSocket.OPEN) this.socket.send(frame);
      else if (!streaming) pending.push(frame);
    };
    this.source.connect(this.processor);
    this.processor.connect(this.context.destination);
    await new Promise<void>((resolve, reject) => {
      const socket = this.socket!;
      let ready = false;
      socket.onopen = () => { socket.send(JSON.stringify({ sample_rate: this.context?.sampleRate ?? 16_000, channels: 1, encoding: "pcm_f32le", mime_type: "audio/raw;encoding=pcm_f32le", language: this.language })); };
      socket.onerror = () => {
        const error = new Error("Unable to connect to local audio pipeline.");
        this.rejectStopped?.(error);
        reject(error);
      };
      socket.onclose = () => {
        if (!ready) reject(new Error("Local audio pipeline disconnected before it was ready."));
        const rejectStopped = this.rejectStopped;
        this.rejectStopped = undefined;
        this.resolveStopped = undefined;
        rejectStopped?.(new Error("Local audio pipeline disconnected before finalization completed."));
      };
      socket.onmessage = (message) => {
        try {
          const payload = JSON.parse(String(message.data)) as { type?: string; message?: string };
          if (payload.type === "ready") {
            ready = true;
            for (const frame of pending.splice(0)) socket.send(frame);
            streaming = true;
            resolve();
            return;
          }
          if (payload.type === "stopped") {
            const resolveStopped = this.resolveStopped;
            this.resolveStopped = undefined;
            this.rejectStopped = undefined;
            socket.close();
            resolveStopped?.();
            return;
          }
          if (payload.type === "partial") {
            if (!this.stopping) this.onPartial?.((payload as { text?: string }).text ?? "");
            return;
          }
          if (payload.type === "warning") {
            this.onError?.(payload.message ?? "Local finalization warning");
            return;
          }
          const event = parseLocalEvent(String(message.data));
          if (event?.error) {
            this.onError?.(event.error);
            if (!ready) reject(new Error(event.error));
          }
          else if (event?.text && !this.stopping) onSegment({ ...event, id: event.id ?? `local-${this.sequence}`, sequence_number: event.sequence_number ?? this.sequence++ });
        } catch (error) { this.onError?.(error instanceof Error ? error.message : "Invalid local pipeline event."); }
      };
    });
  }

  pause() { this.processor?.disconnect(); }

  private resolveStopped?: () => void;
  private rejectStopped?: (error: Error) => void;

  abort() {
    this.stopping = true;
    this.onPartial?.("");
    this.resolveStopped = undefined;
    this.rejectStopped = undefined;
    const socket = this.socket;
    this.processor?.disconnect(); this.source?.disconnect(); this.stream?.getTracks().forEach((track) => track.stop()); void this.context?.close();
    this.processor = null; this.source = null; this.stream = null; this.context = null; this.socket = null;
    // Closing without "stop" skips the final pass; nothing is persisted.
    socket?.close();
  }

  async stop() {
    const socket = this.socket;
    this.stopping = true;
    this.onPartial?.("");
    if (socket?.readyState === WebSocket.OPEN) {
      this.stopped = new Promise<void>((resolve, reject) => {
        this.resolveStopped = resolve;
        this.rejectStopped = reject;
      });
      try {
        socket.send(JSON.stringify({ type: "stop" }));
      } catch {
        this.rejectStopped?.(new Error("Unable to stop the local audio pipeline."));
      }
    }
    this.processor?.disconnect(); this.source?.disconnect(); this.stream?.getTracks().forEach((track) => track.stop()); void this.context?.close();
    this.processor = null; this.source = null; this.stream = null; this.context = null; this.socket = null;
    await this.stopped;
  }
}
