"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getLanguageSettings, type Language } from "@/lib/languages";
import type { RuntimeStatus } from "@/lib/runtime-status";
import { runtimePresentation } from "@/lib/runtime-status";

export function ConsultationSetup({ onStart, runtime }: { onStart: (input: { patient_id: string; patient_name?: string; age: number; sex: string; language_code: string }) => Promise<void>; runtime: RuntimeStatus | null }) {
  const [patientId, setPatientId] = useState("");
  const [name, setName] = useState("");
  const [age, setAge] = useState("");
  const [sex, setSex] = useState("Female");
  const [languageCode, setLanguageCode] = useState("auto");
  const [languages, setLanguages] = useState<Language[]>([]);
  const [primaryName, setPrimaryName] = useState<string | null>(null);
  useEffect(() => { getLanguageSettings().then((settings) => { setLanguages(settings.available.filter((language) => settings.enabled.includes(language.code))); setPrimaryName(settings.available.find((language) => language.code === settings.primary)?.name.replace(/ \(.*\)$/, "") ?? null); }).catch(() => setLanguages([])); }, []);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!patientId || !age || !sex) return setError("Patient ID, age and sex are required.");
    setBusy(true); setError("");
    try { await onStart({ patient_id: patientId, patient_name: name || undefined, age: Number(age), sex, language_code: languageCode }); } catch (err) { setError(err instanceof Error ? err.message : "Unable to start consultation."); } finally { setBusy(false); }
  }

  const presentation = runtimePresentation(runtime ?? { mode: "unknown", providers: {} });
  const providerStatus = (name: string) => runtime?.providers[name]?.status === "ready" ? "Ready" : runtime?.providers[name]?.status === "disabled" ? "Disabled" : runtime?.providers[name]?.error ?? "Unavailable";

  return <section className="setup-card consultation-setup-card" data-testid="consultation-intake-card">
    <div className="eyebrow">New consultation</div><h1>Start with the patient in front of you.</h1><p className="lead">Capture the conversation naturally. Gaya will keep the note grounded in what was actually said.</p>
    <form onSubmit={submit} className="setup-form">
      <label>Patient ID<input aria-label="Patient ID" value={patientId} onChange={(event) => setPatientId(event.target.value)} placeholder="e.g. PT-10482" /></label>
      <label>Patient name <span className="optional">optional</span><input aria-label="Patient name" value={name} onChange={(event) => setName(event.target.value)} placeholder="Name for this visit" /></label>
      <div className="form-grid"><label>Age<input aria-label="Age" type="number" min="0" max="130" value={age} onChange={(event) => setAge(event.target.value)} placeholder="42" /></label><label>Sex<select aria-label="Sex" value={sex} onChange={(event) => setSex(event.target.value)}><option>Female</option><option>Male</option><option>Intersex</option><option>Prefer not to say</option></select></label></div>
      <label>Conversation language<select aria-label="Conversation language" value={languageCode} onChange={(event) => setLanguageCode(event.target.value)}><option value="auto">{languages.length > 1 ? `Auto-detect (${languages.map((language) => language.name.replace(/ \(.*\)$/, "")).join(", ")}${primaryName ? `; usually ${primaryName}` : ""})` : "Auto-detect"}</option>{languages.map((language) => <option key={language.code} value={language.code}>{language.name}</option>)}</select><span className="field-hint">Only languages enabled in <Link href="/settings">Settings</Link> are offered.</span></label>
      {error && <div className="form-error">{error}</div>}
      <button className="primary-button wide" disabled={busy}>{busy ? "Starting…" : "Start consultation"}</button>
    </form>
    <div className="demo-callout"><span className="demo-dot" /><div><strong>{presentation.modeLabel}</strong><p><b>{presentation.providerLabel}</b> · {presentation.modeLabel === "Local AI" ? "Microphone audio stays local and is processed by the configured backend pipeline." : presentation.modeLabel === "Demo mode" ? "Stream a scripted fever consultation without microphone or patient data." : "Waiting for the backend runtime status."}</p>{runtime?.mode === "local" && <div className="provider-status-grid"><span>Backend <b>{runtime.backend?.status === "connected" ? "Connected" : "Unavailable"}</b></span><span>Ollama <b>{providerStatus("ollama")}</b></span><span>Speech model ({runtime.providers.speech_to_text?.engine ?? "unknown"}) <b>{providerStatus("speech_to_text")}</b></span><span>Silero VAD <b>{providerStatus("silero_vad")}</b></span><span>WhisperX <b>{providerStatus("whisperx")}</b></span><span>pyannote <b>{providerStatus("pyannote")}</b></span></div>}</div></div>
  </section>;
}
