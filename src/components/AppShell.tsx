"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Activity, Clock3, FileText, LogOut, ShieldCheck, UserCog, Users } from "lucide-react";
import { AuthGate, useSession } from "./AuthGate";

function Sidebar() {
  const pathname = usePathname();
  const { user, signOut } = useSession();
  const link = (href: string, label: string, icon: React.ReactNode) => <Link className={`nav-link ${pathname === href || (href !== "/" && pathname.startsWith(href)) ? "active" : ""}`} href={href}>{icon} {label}</Link>;
  return <aside className="sidebar" data-testid="editorial-sidebar">
    <div className="brand"><div className="brand-mark"><Activity size={18} /></div><div><strong>VociBot</strong><span>Clinical notes, grounded</span></div></div>
    <nav className="side-nav">{link("/", "Consultation", <FileText size={17} />)}{link("/history", "Consultation history", <Clock3 size={17} />)}{user.role === "admin" && link("/admin", "Users & security", <Users size={17} />)}</nav>
    <div className="account-card" data-testid="account-card"><div><strong>{user.display_name}</strong><span>{user.username} · {user.role === "admin" ? "Administrator" : "Clinician"}</span></div><div className="account-actions"><Link href="/account" aria-label="Account settings"><UserCog size={15} /> Account</Link><button type="button" onClick={() => void signOut()}><LogOut size={15} /> Sign out</button></div></div>
    <div className="privacy-card"><ShieldCheck size={18} /><div><strong>Local-first</strong><span>Data stays on this clinic&apos;s machine. Only you can see your patients.</span></div></div>
  </aside>;
}

export function AppShell({ children }: { children: React.ReactNode }) {
  return <AuthGate><div className="app-shell"><Sidebar /><main className="main-shell">{children}</main></div></AuthGate>;
}
