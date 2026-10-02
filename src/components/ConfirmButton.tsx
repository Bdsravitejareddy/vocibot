"use client";

import { useState, type ReactNode } from "react";

/** Two-step action: the first click asks, the second runs it. */
export function ConfirmButton({ label, icon, question, busyLabel, onConfirm, tone = "danger", disabled = false }: { label: string; icon: ReactNode; question: string; busyLabel: string; onConfirm: () => Promise<void>; tone?: "danger" | "neutral"; disabled?: boolean }) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function confirm() {
    setBusy(true);
    setError("");
    try { await onConfirm(); setConfirming(false); } catch (err) { setError(err instanceof Error ? err.message : `Unable to ${label.toLowerCase()}.`); } finally { setBusy(false); }
  }
  const className = `discard-button ${tone === "neutral" ? "neutral" : ""}`;
  if (!confirming) return <button type="button" className={className} onClick={() => setConfirming(true)} disabled={disabled}>{icon} {label}</button>;
  return <span className={`discard-confirm ${tone === "neutral" ? "neutral" : ""}`} role="group" aria-label={`Confirm ${label.toLowerCase()}`}><span>{error || question}</span><button type="button" className={`${className} danger`} onClick={() => void confirm()} disabled={busy}>{busy ? busyLabel : "Confirm"}</button><button type="button" className="discard-cancel" onClick={() => { setConfirming(false); setError(""); }} disabled={busy}>Cancel</button></span>;
}
