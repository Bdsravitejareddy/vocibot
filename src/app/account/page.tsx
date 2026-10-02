"use client";

import { useHydrated } from "@/lib/use-hydrated";
import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { KeyRound } from "lucide-react";
import { AppShell } from "@/components/AppShell";
import { useSession } from "@/components/AuthGate";
import { changePassword } from "@/lib/auth/api";

function AccountForm() {
  const router = useRouter();
  const required = useSearchParams().get("required") === "1";
  const { user } = useSession();
  const [form, setForm] = useState({ current: "", next: "", confirm: "" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const hydrated = useHydrated();
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (form.next !== form.confirm) return setError("The two new passwords do not match.");
    setBusy(true);
    setError("");
    try { await changePassword(form.current, form.next); router.replace("/login?changed=1"); } catch (err) { setError(err instanceof Error ? err.message : "Unable to change the password."); setBusy(false); }
  }
  const field = (key: keyof typeof form, label: string, autoComplete: string) => <label>{label}<input type="password" autoComplete={autoComplete} required value={form[key]} onChange={(event) => setForm({ ...form, [key]: event.target.value })} /></label>;
  return <div className="history-page"><div className="history-heading"><div><div className="eyebrow">Your account</div><h1>{user.display_name}</h1><p>{user.username} · {user.role === "admin" ? "Administrator" : "Clinician"}</p></div></div>
    {required && <div className="warning-banner">Your administrator set a temporary password. Choose your own password to continue.</div>}
    <form method="post" className="auth-card inline-card" onSubmit={(event) => void submit(event)}><h2>Change password</h2><p className="lead">Changing your password signs you out on every device.</p>
      {field("current", required ? "Temporary password" : "Current password", "current-password")}{field("next", "New password (at least 10 characters)", "new-password")}{field("confirm", "Confirm new password", "new-password")}
      {error && <div className="form-error" role="alert">{error}</div>}
      <button className="primary-button" type="submit" disabled={busy || !hydrated}><KeyRound size={15} /> {busy ? "Saving…" : "Change password"}</button></form></div>;
}

export default function AccountPage() {
  return <AppShell><Suspense fallback={<div className="loading-state">Loading…</div>}><AccountForm /></Suspense></AppShell>;
}
