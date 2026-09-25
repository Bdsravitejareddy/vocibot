"use client";

import { useState } from "react";

export function ConsultationSetup({ onStart }: { onStart: (input: { patient_id: string; patient_name?: string; age: number; sex: string }) => Promise<void> }) {
  const [patientId, setPatientId] = useState("");
  const [name, setName] = useState("");
  const [age, setAge] = useState("");
  const [sex, setSex] = useState("Female");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!patientId || !age || !sex) return setError("Patient ID, age and sex are required.");
    setBusy(true); setError("");
    try { await onStart({ patient_id: patientId, patient_name: name || undefined, age: Number(age), sex }); } catch (err) { setError(err instanceof Error ? err.message : "Unable to start consultation."); } finally { setBusy(false); }
  }

  return <section className="setup-card">
    <div className="eyebrow">New consultation</div><h1>Start with the patient in front of you.</h1><p className="lead">Capture the conversation naturally. VociBot will keep the note grounded in what was actually said.</p>
    <form onSubmit={submit} className="setup-form">
      <label>Patient ID<input aria-label="Patient ID" value={patientId} onChange={(event) => setPatientId(event.target.value)} placeholder="e.g. PT-10482" /></label>
      <label>Patient name <span className="optional">optional</span><input aria-label="Patient name" value={name} onChange={(event) => setName(event.target.value)} placeholder="Name for this visit" /></label>
      <div className="form-grid"><label>Age<input aria-label="Age" type="number" min="0" max="130" value={age} onChange={(event) => setAge(event.target.value)} placeholder="42" /></label><label>Sex<select aria-label="Sex" value={sex} onChange={(event) => setSex(event.target.value)}><option>Female</option><option>Male</option><option>Intersex</option><option>Prefer not to say</option></select></label></div>
      {error && <div className="form-error">{error}</div>}
      <button className="primary-button wide" disabled={busy}>{busy ? "Starting…" : "Start consultation"}</button>
    </form>
    <div className="demo-callout"><span className="demo-dot" /><div><strong>Demo mode is ready</strong><p>Stream a scripted fever consultation without microphone or patient data.</p></div></div>
  </section>;
}
