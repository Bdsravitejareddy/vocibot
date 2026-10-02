import { API_URL } from "./api-base";
export type RuntimeMode = "demo" | "local" | "unknown";

export type RuntimeStatus = {
  mode: RuntimeMode;
  backend?: { status: "connected" | "unavailable"; error?: string };
  providers: Record<string, { status: string; error?: string; engine?: string; model?: string }>;
};

export function runtimePresentation(status: Pick<RuntimeStatus, "mode" | "providers">) {
  if (status.mode === "local") {
    return { modeLabel: "Local AI", providerLabel: "Local microphone pipeline", microphoneEnabled: true };
  }
  if (status.mode === "demo") {
    return { modeLabel: "Demo mode", providerLabel: "Deterministic scripted provider", microphoneEnabled: false };
  }
  return { modeLabel: "Runtime unavailable", providerLabel: "Backend unavailable", microphoneEnabled: false };
}


export async function getRuntimeStatus(): Promise<RuntimeStatus> {
  const response = await fetch(`${API_URL}/api/runtime-status`, { cache: "no-store", credentials: "include" });
  if (!response.ok) throw new Error(`Runtime status unavailable (${response.status})`);
  return response.json() as Promise<RuntimeStatus>;
}
