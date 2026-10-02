"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ArrowUpRight, ChevronLeft, Clock3, Search } from "lucide-react";
import { AppShell } from "@/components/AppShell";
import { DiscardButton } from "@/components/DiscardButton";
import { discardConsultation, listConsultations, type ConsultationSummary } from "@/lib/consultations/api";

const PAGE_SIZE = 50;

export default function HistoryPage() {
  const [consultations, setConsultations] = useState<ConsultationSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    listConsultations({ limit: PAGE_SIZE, offset, q: search }).then((page) => { setConsultations(page.items); setTotal(page.total); }).catch((err) => setError(err instanceof Error ? err.message : "Unable to load history."));
  }, [offset, search]);
  const discard = async (id: string) => { await discardConsultation(id); setConsultations((current) => current.filter((item) => item.id !== id)); setTotal((count) => count - 1); };
  return <AppShell><div className="history-page"><Link className="back-link" href="/"><ChevronLeft size={15} /> Back to consultation</Link>
    <div className="history-heading"><div><div className="eyebrow">Continuity of care</div><h1>Consultation history</h1><p>Every approved note remains linked to its original transcript and evidence.</p></div><div className="history-count"><strong>{total}</strong><span>saved visits</span></div></div>
    <form className="history-search" role="search" onSubmit={(event) => { event.preventDefault(); setOffset(0); setSearch(query.trim()); }}><Search size={15} /><input aria-label="Search consultations" placeholder="Search by patient ID, name or session ID" value={query} onChange={(event) => setQuery(event.target.value)} /><button className="secondary-button" type="submit">Search</button></form>
    {error && <div className="warning-banner">{error}</div>}
    <section className="history-card"><div className="history-table-head"><span>Patient</span><span>Date</span><span>Chief complaint</span><span>Status</span><span /></div>{consultations.length === 0 ? <div className="history-empty"><Clock3 size={25} /><strong>{search ? "No consultations match your search" : "No consultations saved yet"}</strong><span>{search ? "Try a different patient ID, name or session ID." : "Approved consultations will show up here."}</span></div> : consultations.map((consultation) => <div className="history-row" key={consultation.id}><div><strong>{consultation.patient.patient_identifier}</strong><span>{consultation.patient.name || "Unnamed patient"}</span><span className="session-code">{consultation.session_code}</span></div><span>{new Date(consultation.started_at).toLocaleDateString()}</span><span>{consultation.chief_complaint || "Not discussed"}</span><span className="history-status">{consultation.status === "APPROVED" ? "Approved" : "Needs review"}</span><div className="history-actions"><DiscardButton onDiscard={() => discard(consultation.id)} /><Link aria-label="Open consultation" className="row-link" href={`/history/view?id=${encodeURIComponent(consultation.id)}`}>Open <ArrowUpRight size={14} /></Link></div></div>)}</section>
    {total > PAGE_SIZE && <div className="history-pager"><button className="secondary-button" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>Newer</button><span>{offset + 1}–{Math.min(offset + PAGE_SIZE, total)} of {total}</span><button className="secondary-button" disabled={offset + PAGE_SIZE >= total} onClick={() => setOffset(offset + PAGE_SIZE)}>Older</button></div>}
  </div></AppShell>;
}
