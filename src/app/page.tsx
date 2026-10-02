"use client";

import { useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { ConsultationSetup } from "@/components/ConsultationSetup";
import { ConsultationWorkspace } from "@/components/ConsultationWorkspace";
import { createConsultation, type ConsultationState } from "@/lib/consultations/api";
import { getRuntimeStatus, runtimePresentation, type RuntimeStatus } from "@/lib/runtime-status";

export default function HomePage() {
  const [consultation, setConsultation] = useState<ConsultationState | null>(null);
  const [languageCode, setLanguageCode] = useState("auto");
  const [showSetup, setShowSetup] = useState(false);
  const [runtime, setRuntime] = useState<RuntimeStatus | null>(null);
  useEffect(() => { void getRuntimeStatus().then(setRuntime).catch(() => setRuntime({ mode: "unknown", backend: { status: "unavailable" }, providers: {} })); }, []);
  const presentation = runtimePresentation(runtime ?? { mode: "unknown", providers: {} });
  const startConsultation = async ({ language_code, ...input }: { language_code: string; patient_id: string; patient_name?: string; age: number; sex: string }) => {
    const created = await createConsultation(input);
    setLanguageCode(language_code);
    setConsultation(created);
  };

  return <AppShell>{consultation ? <ConsultationWorkspace key={consultation.id} initial={consultation} runtimeMode={runtime?.mode ?? "unknown"} languageCode={languageCode} onDiscarded={() => { setConsultation(null); setShowSetup(false); }} /> : <div className="landing">{showSetup ? <div className="onboarding-layout"><ConsultationSetup runtime={runtime} onStart={startConsultation} /><aside className="botanical-scene intake-botanical" aria-label="Local-first consultation workspace"><div className="scene-eyebrow">A calm start</div><h2>Keep the conversation human.</h2><p>VociBot keeps your local documentation ready for a careful review.</p></aside></div> : <div className="landing-hero"><section className="landing-copy"><div className="landing-header"><div><div className="eyebrow">Local clinical documentation</div><h1>Stay with the patient. Keep the note in view.</h1><p>Natural conversation, a reviewable clinical record, and local processing that stays on this machine.</p></div><div className="landing-badge">{presentation.modeLabel}</div></div><div className="landing-action"><button className="primary-button" onClick={() => setShowSetup(true)} disabled={runtime === null}>New consultation</button><span>{presentation.modeLabel === "Local AI" ? "Ready for private, on-device documentation" : presentation.modeLabel === "Demo mode" ? "Explore a deterministic offline example" : "Checking the local runtime"}</span></div></section><aside className="botanical-scene landing-botanical" data-testid="botanical-scene"><div className="scene-eyebrow">Made for focus</div><h2>Quiet technology for a more present consultation.</h2><div className="scene-markers"><span>Local processing</span><span>Multilingual speech</span><span>Reviewable note</span></div></aside></div>}</div>}</AppShell>;
}
