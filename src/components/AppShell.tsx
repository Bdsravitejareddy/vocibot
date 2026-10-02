import Link from "next/link";
import { Activity, Clock3, FileText, ShieldCheck } from "lucide-react";

export function AppShell({ children }: { children: React.ReactNode }) {
  return <div className="app-shell">
    <aside className="sidebar" data-testid="editorial-sidebar">
      <div className="brand"><div className="brand-mark"><Activity size={18} /></div><div><strong>VociBot</strong><span>Clinical notes, grounded</span></div></div>
      <nav className="side-nav"><Link className="nav-link active" href="/"><FileText size={17} /> Consultation</Link><Link className="nav-link" href="/history"><Clock3 size={17} /> Consultation history</Link></nav>
      <div className="privacy-card"><ShieldCheck size={18} /><div><strong>Local-first</strong><span>Patient data stays in your workspace.</span></div></div>
    </aside>
    <main className="main-shell">{children}</main>
  </div>;
}
