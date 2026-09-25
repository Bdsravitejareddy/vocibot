"use client";

import { useState } from "react";
import { AppShell } from "@/components/AppShell";
import { ConsultationSetup } from "@/components/ConsultationSetup";
import { ConsultationWorkspace } from "@/components/ConsultationWorkspace";
import { createConsultation, type ConsultationState } from "@/lib/consultations/api";

export default function HomePage() {
  const [consultation, setConsultation] = useState<ConsultationState | null>(null);
  const [showSetup, setShowSetup] = useState(false);
  return <AppShell>{consultation ? <ConsultationWorkspace initial={consultation} /> : <div className="landing"><div className="landing-header"><div><div className="eyebrow">Documentation assistant</div><h1>Make the note while you stay present.</h1><p>VociBot turns a natural consultation into a grounded, reviewable clinical record.</p></div><div className="landing-badge">Local-first · Demo ready</div></div>{showSetup ? <ConsultationSetup onStart={async (input) => setConsultation(await createConsultation(input))} /> : <div className="setup-card intro-card"><div className="intro-icon">✦</div><h2>Ready for a focused consultation?</h2><p>Start a new record, then choose the offline demo or microphone capture.</p><button className="primary-button" onClick={() => setShowSetup(true)}>New consultation</button></div>}</div>}</AppShell>;
}
