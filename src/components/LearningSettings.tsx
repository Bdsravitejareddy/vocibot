"use client";

import { useEffect, useState } from "react";
import { Play, Sparkles } from "lucide-react";
import { getAudit, getLearning, runLearning, saveLearning, type AuditEntry, type CloudLevel, type LearningStatus, type Numbers } from "@/lib/learning";

const LEVELS: Array<{ value: CloudLevel; label: string; detail: string }> = [
  { value: "off", label: "Off", detail: "Nothing leaves this computer. VociBot still learns from its own test set each night." },
  { value: "knowledge", label: "Knowledge only", detail: "Gemini is asked general questions (common Indian medicine brands and how they are said). No patient data is sent." },
  { value: "snippets", label: "De-identified snippets", detail: "Also sends a few words around a medicine VociBot could not recognise, with names, ages, phone numbers, dates and other numbers removed." },
];

const ROWS: Array<{ label: string; value: (numbers: Numbers) => string }> = [
  { label: "Medicines in the note", value: (n) => `${n.medicines_in_note}/${n.medicines_total}` },
  { label: "Wrong medicines", value: (n) => String(n.wrong_medicines) },
  { label: "English note facts", value: (n) => `${n.note_facts}/${n.note_facts_total}` },
  { label: "False facts", value: (n) => String(n.note_false_facts) },
  { label: "Unrecognised medicines in last week's notes", value: (n) => String(n.unresolved_recent ?? "—") },
];

const DECISIONS = { accepted: "Improvement found — switched on", rejected: "No meaningful improvement — kept the previous tips", "no change": "Nothing new to test", failed: "The run failed" };

export function LearningSettings() {
  const [status, setStatus] = useState<LearningStatus | null>(null);
  const [audit, setAudit] = useState<AuditEntry[] | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const load = () => getLearning().then(setStatus).catch((err) => setError(err instanceof Error ? err.message : "Unable to load learning settings."));
  useEffect(() => { void load(); }, []);
  useEffect(() => { if (!status?.running) return; const timer = setInterval(() => void load(), 15_000); return () => clearInterval(timer); }, [status?.running]);

  async function change(changes: { enabled?: boolean; cloud_level?: CloudLevel }) {
    setError(""); setMessage("");
    try { setStatus(await saveLearning(changes)); setMessage("Saved."); } catch (err) { setError(err instanceof Error ? err.message : "Unable to save."); }
  }
  async function run() {
    setError(""); setMessage("");
    try { await runLearning(); setMessage("Learning started. It takes about 15 minutes; this page updates when it finishes."); await load(); } catch (err) { setError(err instanceof Error ? err.message : "Unable to start."); }
  }
  const report = status?.last_report;
  return <section className="settings-card learning-card" data-testid="learning-settings">
    <div className="voice-heading"><div><h2><Sparkles size={17} /> Nightly learning</h2><p>At 11 pm (never during clinic hours, and never while a consultation is recording) VociBot tries to improve its tips, such as recognising misheard medicine names. Each change is tested on a fixed set of practice consultations, and switched on only if results improve and nothing gets worse. Every changed note field is still marked for the doctor to review.</p></div></div>
    {error && <div className="warning-banner" role="alert">{error}</div>}
    {message && <div className="notice-banner" role="status">{message}</div>}
    {status && <>
      <label className="language-option"><input type="checkbox" checked={status.enabled} onChange={(event) => void change({ enabled: event.target.checked })} /> Learn every night</label>
      <fieldset className="learning-levels" disabled={!status.enabled}><legend><strong>Gemini help</strong> (Google, free tier) — only during the nightly run, never during a consultation</legend>
        {LEVELS.map((level) => <label key={level.value} className="learning-level"><input type="radio" name="cloud-level" checked={status.cloud_level === level.value} onChange={() => void change({ cloud_level: level.value })} /><span><strong>{level.label}</strong><small>{level.detail}</small></span></label>)}
        {status.cloud_level !== "off" && <p className="muted">{status.gemini_keys ? `${status.gemini_keys} Gemini key${status.gemini_keys > 1 ? "s" : ""} found in the macOS Keychain; later keys are backups.` : "No Gemini key found in the macOS Keychain (service “vocibot-gemini”), so the nightly run stays on this computer."}</p>}
      </fieldset>
      <div className="settings-actions"><button type="button" className="primary-button" onClick={() => void run()} disabled={status.running}><Play size={14} /> {status.running ? "Learning…" : "Run now"}</button>{status.cloud_level !== "off" && <button type="button" className="secondary-button" onClick={() => getAudit().then(setAudit).catch(() => setAudit([]))}>What was sent to Gemini</button>}</div>
      {report && <div className="learning-report" data-testid="learning-report">
        <p><strong>Last run:</strong> {new Date(report.started).toLocaleString()} — {DECISIONS[report.decision]}{report.error ? ` (${report.error})` : ""}</p>
        {report.before && report.after && <table className="learning-table"><thead><tr><th></th><th>Before</th><th>With the new tips</th></tr></thead><tbody>{ROWS.map((row) => <tr key={row.label}><td>{row.label}</td><td>{row.value(report.before!)}</td><td>{row.value(report.after!)}</td></tr>)}</tbody></table>}
        <ul className="learning-steps">{report.steps.map((step, index) => <li key={index}><strong>{step.step}</strong>: {Object.entries(step).filter(([key]) => key !== "step").map(([key, value]) => `${key.replaceAll("_", " ")} ${Array.isArray(value) ? value.join(", ") || "none" : typeof value === "object" ? JSON.stringify(value) : String(value)}`).join(" · ")}</li>)}</ul>
      </div>}
      {audit && <div className="learning-audit"><h3>Sent to Gemini ({audit.length})</h3>{audit.length === 0 ? <p className="muted">Nothing has been sent.</p> : <ul>{audit.map((entry, index) => <li key={index}><small>{new Date(entry.time).toLocaleString()} · {entry.level} · {entry.purpose}{entry.error ? " · failed" : ""}</small><pre>{entry.sent}</pre></li>)}</ul>}</div>}
    </>}
  </section>;
}
