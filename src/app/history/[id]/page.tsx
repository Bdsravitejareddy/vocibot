"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ChevronLeft } from "lucide-react";
import { AppShell } from "@/components/AppShell";
import { AuditTrail } from "@/components/AuditTrail";
import { ClinicalRecordPanel } from "@/components/ClinicalRecordPanel";
import { DiscardButton } from "@/components/DiscardButton";
import { discardConsultation, getConsultation, type ConsultationState } from "@/lib/consultations/api";

export default function ConsultationDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const [consultation, setConsultation] = useState<ConsultationState | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { if (params.id) getConsultation(params.id).then(setConsultation).catch((err) => setError(err instanceof Error ? err.message : "Unable to load consultation.")); }, [params.id]);
  if (error) return <AppShell><div className="history-page"><div className="warning-banner">{error}</div></div></AppShell>;
  if (!consultation) return <AppShell><div className="history-page"><div className="loading-state">Loading consultation…</div></div></AppShell>;
  return <AppShell><div className="history-page"><Link className="back-link" href="/history"><ChevronLeft size={15} /> Consultation history</Link><div className="history-heading"><div><div className="eyebrow">Saved consultation</div><h1>{consultation.patient.patient_identifier}</h1><p>{new Date(consultation.started_at).toLocaleString()} · {consultation.patient.age} years · {consultation.patient.sex}</p></div><div className="history-actions"><div className="detail-status">{consultation.status === "APPROVED" ? "Approved record" : "Needs review"}</div><DiscardButton onDiscard={async () => { await discardConsultation(consultation.id); router.push("/history"); }} /></div></div><div className="detail-grid"><section className="panel detail-transcript"><div className="panel-heading"><div><div className="section-kicker">Complete transcript</div><h2>Conversation record</h2></div></div><div className="transcript-list">{consultation.transcript.map((segment) => <article className={`transcript-item ${segment.speaker.toLowerCase()}`} key={segment.id}><div className="transcript-meta"><span className="speaker-label">{segment.speaker[0] + segment.speaker.slice(1).toLowerCase()}</span><time>{new Date(segment.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</time></div><p>“{segment.text}”</p></article>)}</div></section><ClinicalRecordPanel record={consultation.record} updates={consultation.updates} onChange={() => undefined} disabled /><AuditTrail updates={consultation.updates} /></div></div></AppShell>;
}
