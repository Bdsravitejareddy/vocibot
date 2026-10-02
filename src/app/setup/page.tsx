"use client";

import { useHydrated } from "@/lib/use-hydrated";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Activity, ShieldCheck } from "lucide-react";
import { completeSetup, getAuthStatus } from "@/lib/auth/api";

export default function SetupPage() {
  const router = useRouter();
  const [form, setForm] = useState({ display_name: "", username: "", password: "", confirm: "" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const hydrated = useHydrated();
  useEffect(() => { void getAuthStatus().then((status) => { if (!status.setup_required) router.replace("/login"); }).catch(() => setError("The VociBot server is not reachable.")); }, [router]);
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (form.password !== form.confirm) return setError("The two passwords do not match.");
    setBusy(true);
    setError("");
    try { await completeSetup({ display_name: form.display_name, username: form.username, password: form.password }); router.replace("/admin"); } catch (err) { setError(err instanceof Error ? err.message : "Setup failed."); } finally { setBusy(false); }
  }
  const field = (key: keyof typeof form, label: string, type = "text", autoComplete?: string) => <label>{label}<input type={type} autoComplete={autoComplete} required value={form[key]} onChange={(event) => setForm({ ...form, [key]: event.target.value })} /></label>;
  return <div className="auth-page"><form method="post" className="auth-card" onSubmit={(event) => void submit(event)}>
    <div className="brand auth-brand"><div className="brand-mark"><Activity size={18} /></div><div><strong>VociBot</strong><span>First-time setup</span></div></div>
    <h1>Create the administrator</h1><p className="lead">This account adds doctors, resets passwords and reviews the security log. It is created once; afterwards only the administrator can add accounts.</p>
    {field("display_name", "Your name")}{field("username", "Username", "text", "username")}{field("password", "Password (at least 10 characters)", "password", "new-password")}{field("confirm", "Confirm password", "password", "new-password")}
    {error && <div className="form-error" role="alert">{error}</div>}
    <button className="primary-button wide" type="submit" disabled={busy || !hydrated}><ShieldCheck size={15} /> {busy ? "Creating…" : "Create administrator"}</button>
  </form></div>;
}
