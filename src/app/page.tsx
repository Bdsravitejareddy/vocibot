"use client";

import { useEffect, useState } from "react";
import { AppShell } from "@/components/AppShell";
import { ConsultationSetup } from "@/components/ConsultationSetup";
import { ConsultationWorkspace } from "@/components/ConsultationWorkspace";
import { createConsultation, type ConsultationState } from "@/lib/consultations/api";
import { getRuntimeStatus, runtimePresentation, type RuntimeStatus } from "@/lib/runtime-status";

export default function HomePage() {
  const [consultation, setConsultation] = useState<ConsultationState | null>(null);
  const [showSetup, setShowSetup] = useState(false);
  const [runtime, setRuntime] = useState<RuntimeStatus | null>(null);
  useEffect(() => { void getRuntimeStatus().then(setRuntime).catch(() => setRuntime({ mode: "unknown", backend: { status: "unavailable" }, providers: {} })); }, []);
  const presentation = runtimePresentation(runtime ?? { mode: "unknown", providers: {} });
  return <AppShell>{consultation ? <ConsultationWorkspace initial={consultation} runtimeMode={runtime?.mode ?? "unknown"} /> : <div className="landing"><div className="landing-header"><div><div className="eyebrow">Documentation assistant</div><h1>Make the note while you stay present.</h1><p>VociBot turns a natural consultation into a grounded, reviewable clinical record.</p></div><div className="landing-badge">{presentation.modeLabel}</div></div>{showSetup ? <ConsultationSetup runtime={runtime} onStart={async (input) => setConsultation(await createConsultation(input))} /> : <div className="setup-card intro-card"><div className="intro-icon">✦</div><h2>Ready for a focused consultation?</h2><p>{presentation.modeLabel === "Local AI" ? "Start a local microphone consultation and review the evidence-grounded record." : presentation.modeLabel === "Demo mode" ? "Start a new record, then run the deterministic offline demo." : "Waiting for the backend runtime status."}</p><button className="primary-button" onClick={() => setShowSetup(true)} disabled={runtime === null}>New consultation</button></div>}</div>}</AppShell>;
}
