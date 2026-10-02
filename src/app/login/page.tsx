"use client";

import { useHydrated } from "@/lib/use-hydrated";
import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Activity, LogIn } from "lucide-react";
import { getAuthStatus, signIn } from "@/lib/auth/api";

function safeNext(value: string | null) {
  // Only same-site paths: never redirect to another site after sign-in.
  return value && value.startsWith("/") && !value.startsWith("//") && !value.startsWith("/login") ? value : "/";
}

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const hydrated = useHydrated();
  useEffect(() => { void getAuthStatus().then((status) => { if (status.setup_required) router.replace("/setup"); else if (status.user) router.replace(safeNext(params.get("next"))); }).catch(() => setError("The VociBot server is not reachable.")); }, [params, router]);
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    // Read the fields at submit time: typing before the page finished loading still counts.
    const form = event.currentTarget;
    const fields = new FormData(form);
    setBusy(true);
    setError("");
    try {
      const { user } = await signIn(String(fields.get("username") ?? ""), String(fields.get("password") ?? ""));
      router.replace(user.must_change_password ? "/account?required=1" : safeNext(params.get("next")));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign-in failed.");
      const passwordInput = form.elements.namedItem("password") as HTMLInputElement | null;
      if (passwordInput) passwordInput.value = "";
    } finally { setBusy(false); }
  }
  return <form method="post" className="auth-card" onSubmit={(event) => void submit(event)}>
    <div className="brand auth-brand"><div className="brand-mark"><Activity size={18} /></div><div><strong>VociBot</strong><span>Clinical notes, grounded</span></div></div>
    <h1>Sign in</h1><p className="lead">Use the account your clinic administrator gave you.</p>
    <label>Username<input name="username" autoComplete="username" autoFocus required /></label>
    <label>Password<input name="password" type="password" autoComplete="current-password" required /></label>
    {error && <div className="form-error" role="alert">{error}</div>}
    <button className="primary-button wide" type="submit" disabled={busy || !hydrated}><LogIn size={15} /> {busy ? "Signing in…" : "Sign in"}</button>
  </form>;
}

export default function LoginPage() {
  return <div className="auth-page"><Suspense fallback={<div className="loading-state">Loading…</div>}><LoginForm /></Suspense></div>;
}
