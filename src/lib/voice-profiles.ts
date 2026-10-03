const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

export type VoiceProfile = { id: string; name: string; samples: number; created_at: string; threshold: number };

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, { cache: "no-store", ...init, headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) } });
  if (!response.ok) throw new Error((await response.json().catch(() => null))?.detail ?? `Request failed: ${response.status}`);
  return (response.status === 204 ? undefined : response.json()) as Promise<T>;
}

export const listVoiceProfiles = () => request<{ available: boolean; profiles: VoiceProfile[] }>("/api/voice-profiles");
export const deleteVoiceProfile = (id: string) => request<void>(`/api/voice-profiles/${id}`, { method: "DELETE" });

/** Only the voice fingerprint is kept; the recordings are not stored. */
export function enrolVoice(name: string, sampleRate: number, samples: Float32Array[]) {
  const encode = (samplesOfOne: Float32Array) => {
    const bytes = new Uint8Array(samplesOfOne.buffer, samplesOfOne.byteOffset, samplesOfOne.byteLength);
    let binary = "";
    for (let index = 0; index < bytes.length; index += 0x8000) binary += String.fromCharCode(...bytes.subarray(index, index + 0x8000));
    return btoa(binary);
  };
  return request<VoiceProfile>("/api/voice-profiles", { method: "POST", body: JSON.stringify({ name, sample_rate: sampleRate, samples: samples.map(encode) }) });
}

/** Records one sentence from the microphone as raw PCM. */
export class SentenceRecorder {
  private stream: MediaStream | null = null;
  private context: AudioContext | null = null;
  private processor: ScriptProcessorNode | null = null;
  private chunks: Float32Array[] = [];
  sampleRate = 48_000;

  async start() {
    this.chunks = [];
    this.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    this.context = new AudioContext();
    this.sampleRate = this.context.sampleRate;
    const source = this.context.createMediaStreamSource(this.stream);
    this.processor = this.context.createScriptProcessor(4096, 1, 1);
    this.processor.onaudioprocess = (event) => { this.chunks.push(new Float32Array(event.inputBuffer.getChannelData(0))); };
    source.connect(this.processor);
    this.processor.connect(this.context.destination);
  }

  async stop(): Promise<Float32Array> {
    this.processor?.disconnect();
    this.stream?.getTracks().forEach((track) => track.stop());
    await this.context?.close().catch(() => undefined);
    const total = this.chunks.reduce((sum, chunk) => sum + chunk.length, 0);
    const audio = new Float32Array(total);
    let offset = 0;
    for (const chunk of this.chunks) { audio.set(chunk, offset); offset += chunk.length; }
    return audio;
  }
}
