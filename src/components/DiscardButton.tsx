"use client";

import { Trash2 } from "lucide-react";
import { ConfirmButton } from "./ConfirmButton";

/** Two-step delete: the first click asks, the second permanently discards. */
export function DiscardButton({ onDiscard, label = "Discard", disabled = false }: { onDiscard: () => Promise<void>; label?: string; disabled?: boolean }) {
  return <ConfirmButton label={label} icon={<Trash2 size={14} />} question="Delete permanently?" busyLabel="Discarding…" onConfirm={onDiscard} disabled={disabled} />;
}
