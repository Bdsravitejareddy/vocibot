"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Clock3, FileText, Settings, ShieldCheck } from "lucide-react";
import { GayaMark } from "./GayaMark";

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const link = (href: string, label: string, icon: React.ReactNode) => <Link className={`nav-link ${pathname === href || (href !== "/" && pathname.startsWith(href)) ? "active" : ""}`} href={href}>{icon} {label}</Link>;
  return <div className="app-shell">
    <aside className="sidebar" data-testid="editorial-sidebar">
      <div className="brand"><div className="brand-mark"><GayaMark /></div><div><strong>Gaya</strong><span>Clinical notes, grounded</span></div></div>
      <nav className="side-nav">{link("/", "Consultation", <FileText size={17} />)}{link("/history", "Consultation history", <Clock3 size={17} />)}{link("/settings", "Settings", <Settings size={17} />)}</nav>
      <div className="privacy-card"><ShieldCheck size={18} /><div><strong>Local-first</strong><span>Patient data stays in your workspace.</span></div></div>
    </aside>
    <main className="main-shell">{children}</main>
  </div>;
}
