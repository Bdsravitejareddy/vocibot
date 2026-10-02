"use client";

import { useState } from "react";
import { Trash2 } from "lucide-react";

/** Two-step delete: the first click asks, the second permanently discards. */
export function DiscardButton({ onDiscard, label = "Discard", disabled = false }: { onDiscard: () => Promise<void>; label?: string; disabled?: boolean }) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function confirm() {
    setBusy(true);
    setError("");
    try { await onDiscard(); } catch (err) { setError(err instanceof Error ? err.message : "Unable to discard."); setBusy(false); }
  }
  if (!confirming) return <button type="button" className="discard-button" onClick={() => setConfirming(true)} disabled={disabled}><Trash2 size={14} /> {label}</button>;
  return <span className="discard-confirm" role="group" aria-label="Confirm discard"><span>{error || "Delete permanently?"}</span><button type="button" className="discard-button danger" onClick={() => void confirm()} disabled={busy}>{busy ? "Discarding…" : "Confirm"}</button><button type="button" className="discard-cancel" onClick={() => setConfirming(false)} disabled={busy}>Cancel</button></span>;
}
