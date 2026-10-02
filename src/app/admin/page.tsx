"use client";

import { useCallback, useEffect, useState } from "react";
import { KeyRound, ShieldAlert, UserPlus } from "lucide-react";
import { AppShell } from "@/components/AppShell";
import { useSession } from "@/components/AuthGate";
import { createUser, listSecurityEvents, listUsers, resetPassword, updateUser, type Role, type SecurityEvent, type User } from "@/lib/auth/api";

/** A readable temporary password the administrator can pass on; it must be changed at first sign-in. */
function temporaryPassword() {
  const words = ["amber", "cedar", "delta", "ember", "fjord", "harbor", "indigo", "juniper", "kestrel", "lumen", "meadow", "nimbus", "orchid", "quartz", "river", "summit", "tundra", "willow"];
  const pick = () => words[crypto.getRandomValues(new Uint32Array(1))[0] % words.length];
  return `${pick()}-${pick()}-${crypto.getRandomValues(new Uint32Array(1))[0] % 900 + 100}`;
}

const EVENT_LABELS: Record<string, string> = { login_succeeded: "Signed in", login_failed: "Failed sign-in", login_blocked: "Sign-in blocked", account_locked: "Account locked", logout: "Signed out", user_created: "Account created", user_updated: "Account changed", password_reset: "Password reset", password_changed: "Password changed", setup_completed: "Setup completed", consultation_discarded: "Consultation discarded" };

function AdminPanel() {
  const { user: me } = useSession();
  const [users, setUsers] = useState<User[]>([]);
  const [events, setEvents] = useState<SecurityEvent[]>([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [form, setForm] = useState({ display_name: "", username: "", role: "clinician" as Role, password: temporaryPassword() });
  const refresh = useCallback(() => Promise.all([listUsers().then(setUsers), listSecurityEvents().then(setEvents)]).catch((err) => setError(err instanceof Error ? err.message : "Unable to load accounts.")), []);
  useEffect(() => { void refresh(); }, [refresh]);
  const names = Object.fromEntries(users.map((user) => [user.id, user.username]));
  async function act(action: () => Promise<unknown>, message: string) {
    setError(""); setNotice("");
    try { await action(); setNotice(message); await refresh(); } catch (err) { setError(err instanceof Error ? err.message : "That did not work."); }
  }
  if (me.role !== "admin") return <div className="history-page"><div className="warning-banner">Administrator access is required.</div></div>;
  return <div className="history-page">
    <div className="history-heading"><div><div className="eyebrow">Administration</div><h1>Users & security</h1><p>Add doctors, reset passwords and review sign-in activity. Administrators cannot open other users&apos; consultations.</p></div><div className="history-count"><strong>{users.filter((user) => user.is_active).length}</strong><span>active accounts</span></div></div>
    {error && <div className="warning-banner" role="alert">{error}</div>}
    {notice && <div className="notice-banner" role="status">{notice}</div>}
    <form method="post" className="admin-card" onSubmit={(event) => { event.preventDefault(); void act(() => createUser({ ...form, must_change_password: true }), `Account ${form.username} created. Give them the temporary password: ${form.password}`).then(() => setForm({ display_name: "", username: "", role: "clinician", password: temporaryPassword() })); }}>
      <h2><UserPlus size={16} /> Add a user</h2>
      <div className="admin-form-grid">
        <label>Full name<input required value={form.display_name} onChange={(event) => setForm({ ...form, display_name: event.target.value })} /></label>
        <label>Username<input required autoComplete="off" value={form.username} onChange={(event) => setForm({ ...form, username: event.target.value })} /></label>
        <label>Role<select value={form.role} onChange={(event) => setForm({ ...form, role: event.target.value as Role })}><option value="clinician">Clinician</option><option value="admin">Administrator</option></select></label>
        <label>Temporary password<input required value={form.password} onChange={(event) => setForm({ ...form, password: event.target.value })} /></label>
      </div>
      <p className="muted">They must choose their own password the first time they sign in.</p>
      <button className="primary-button" type="submit">Create account</button>
    </form>
    <section className="history-card admin-users"><div className="admin-row admin-head"><span>User</span><span>Role</span><span>Status</span><span>Last sign-in</span><span /></div>
      {users.map((user) => <div className="admin-row" key={user.id} data-testid={`user-${user.username}`}><div><strong>{user.display_name}</strong><span className="session-code">{user.username}</span></div><span>{user.role === "admin" ? "Administrator" : "Clinician"}</span><span>{!user.is_active ? "Deactivated" : user.locked ? "Locked" : user.must_change_password ? "Temporary password" : "Active"}</span><span>{user.last_login_at ? new Date(user.last_login_at).toLocaleString() : "Never"}</span>
        <div className="history-actions">{user.id !== me.id && <>
          <button type="button" className="discard-button neutral" onClick={() => { const password = temporaryPassword(); void act(() => resetPassword(user.id, password), `Password for ${user.username} reset. Temporary password: ${password}`); }}><KeyRound size={14} /> Reset password</button>
          <button type="button" className="discard-button neutral" onClick={() => void act(() => updateUser(user.id, { role: user.role === "admin" ? "clinician" : "admin" }), `${user.username} is now ${user.role === "admin" ? "a clinician" : "an administrator"}.`)}>{user.role === "admin" ? "Make clinician" : "Make admin"}</button>
          <button type="button" className={`discard-button ${user.is_active ? "" : "neutral"}`} onClick={() => void act(() => updateUser(user.id, { is_active: !user.is_active }), `${user.username} ${user.is_active ? "deactivated and signed out" : "reactivated"}.`)}>{user.is_active ? "Deactivate" : "Reactivate"}</button>
        </>}</div></div>)}
    </section>
    <section className="history-card security-log"><h2><ShieldAlert size={16} /> Security log</h2>{events.length === 0 ? <p className="muted">No events yet.</p> : <div className="security-events">{events.map((event) => <div className="security-event" key={event.id}><time>{new Date(event.occurred_at).toLocaleString()}</time><strong>{EVENT_LABELS[event.event] ?? event.event}</strong><span>{event.username ?? ""}{event.actor_user_id && event.subject_user_id && event.actor_user_id !== event.subject_user_id ? ` · by ${names[event.actor_user_id] ?? "an administrator"}` : ""}</span><span className="muted">{event.ip_address ?? ""}{event.detail?.session_code ? ` · ${String(event.detail.session_code)}` : ""}</span></div>)}</div>}</section>
  </div>;
}

export default function AdminPage() {
  return <AppShell><AdminPanel /></AppShell>;
}
