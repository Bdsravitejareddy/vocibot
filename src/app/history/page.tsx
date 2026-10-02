"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ArrowUpRight, ChevronLeft, Clock3 } from "lucide-react";
import { AppShell } from "@/components/AppShell";
import { DiscardButton } from "@/components/DiscardButton";
import { discardConsultation, listConsultations, type ConsultationState } from "@/lib/consultations/api";

export default function HistoryPage() {
  const [consultations, setConsultations] = useState<ConsultationState[]>([]);
  const [error, setError] = useState("");
  useEffect(() => { listConsultations().then(setConsultations).catch((err) => setError(err instanceof Error ? err.message : "Unable to load history.")); }, []);
  return <AppShell><div className="history-page"><Link className="back-link" href="/"><ChevronLeft size={15} /> Back to consultation</Link><div className="history-heading"><div><div className="eyebrow">Continuity of care</div><h1>Consultation history</h1><p>Every approved note remains linked to its original transcript and evidence.</p></div><div className="history-count"><strong>{consultations.length}</strong><span>saved visits</span></div></div>{error && <div className="warning-banner">{error}</div>}<section className="history-card"><div className="history-table-head"><span>Patient</span><span>Date</span><span>Chief complaint</span><span>Status</span><span /></div>{consultations.length === 0 ? <div className="history-empty"><Clock3 size={25} /><strong>No consultations saved yet</strong><span>Approved consultations will show up here.</span></div> : consultations.map((consultation) => <div className="history-row" key={consultation.id}><div><strong>{consultation.patient.patient_identifier}</strong><span>{consultation.patient.name || "Unnamed patient"}</span></div><span>{new Date(consultation.started_at).toLocaleDateString()}</span><span>{consultation.record.chief_complaint || "Not discussed"}</span><span className="history-status">{consultation.status === "APPROVED" ? "Approved" : "Needs review"}</span><div className="history-actions"><DiscardButton onDiscard={async () => { await discardConsultation(consultation.id); setConsultations((current) => current.filter((item) => item.id !== consultation.id)); }} /><Link aria-label="Open consultation" className="row-link" href={`/history/${consultation.id}`}>Open <ArrowUpRight size={14} /></Link></div></div>)}</section></div></AppShell>;
}
