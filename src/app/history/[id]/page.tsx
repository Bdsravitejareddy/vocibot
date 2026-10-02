"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { AudioLines, ChevronLeft, RefreshCw, Sparkles } from "lucide-react";
import { AppShell } from "@/components/AppShell";
import { AuditTrail } from "@/components/AuditTrail";
import { ClinicalRecordPanel } from "@/components/ClinicalRecordPanel";
import { TranscriptPanel } from "@/components/TranscriptPanel";
import { ConfirmButton } from "@/components/ConfirmButton";
import { DiscardButton } from "@/components/DiscardButton";
import type { ClinicalRecord } from "@/lib/domain/types";
import { approveConsultation, discardConsultation, getConsultation, reanalyseConsultation, recordingAudioUrl, retranscribeConsultation, type ConsultationState } from "@/lib/consultations/api";

const FORMAT_LABELS = { wav: "WAV · converting to FLAC", flac: "FLAC · lossless", opus: "Opus · compressed" } as const;

function formatSize(bytes: number) {
  return bytes >= 1_000_000 ? `${(bytes / 1_000_000).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1000))} KB`;
}

function formatDuration(milliseconds: number) {
  const seconds = Math.round(milliseconds / 1000);
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

export default function ConsultationDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const [consultation, setConsultation] = useState<ConsultationState | null>(null);
  const [record, setRecord] = useState<ClinicalRecord | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const show = (next: ConsultationState) => { setConsultation(next); setRecord(next.record); setNotice(next.finalization_warnings?.join(" ") ?? ""); };
  useEffect(() => { if (params.id) getConsultation(params.id).then(show).catch((err) => setError(err instanceof Error ? err.message : "Unable to load consultation.")); }, [params.id]);
  if (error) return <AppShell><div className="history-page"><div className="warning-banner">{error}</div></div></AppShell>;
  if (!consultation || !record) return <AppShell><div className="history-page"><div className="loading-state">Loading consultation…</div></div></AppShell>;
  const reviewing = consultation.status === "READY_FOR_REVIEW";
  const hasAudio = consultation.recordings.some((recording) => recording.available);
  const approve = async () => { try { show(await approveConsultation(consultation.id, record)); } catch (err) { setNotice(err instanceof Error ? err.message : "Unable to approve consultation."); } };
  return <AppShell><div className="history-page"><Link className="back-link" href="/history"><ChevronLeft size={15} /> Consultation history</Link>
    <div className="history-heading"><div><div className="eyebrow">Saved consultation</div><h1>{consultation.patient.patient_identifier}</h1><p>{new Date(consultation.started_at).toLocaleString()} · {consultation.patient.age} years · {consultation.patient.sex}</p><p className="session-code" data-testid="session-code">Session {consultation.session_code}</p></div>
      <div className="detail-actions"><div className="detail-status">{consultation.status === "APPROVED" ? "Approved record" : "Needs review"}</div>
        <ConfirmButton tone="neutral" label="Re-analyse note" icon={<Sparkles size={14} />} question={consultation.status === "APPROVED" ? "Refill the note? It will need approval again." : "Refill the note from the transcript?"} busyLabel="Re-analysing… (up to a minute)" onConfirm={async () => show(await reanalyseConsultation(consultation.id))} disabled={consultation.transcript.length === 0} />
        {hasAudio && <ConfirmButton tone="neutral" label="Re-transcribe" icon={<RefreshCw size={14} />} question={consultation.status === "APPROVED" ? "Re-transcribe the audio and refill the note? It will need approval again." : "Re-transcribe the audio and refill the note?"} busyLabel="Re-transcribing… (up to a minute)" onConfirm={async () => show(await retranscribeConsultation(consultation.id))} />}
        <DiscardButton onDiscard={async () => { await discardConsultation(consultation.id); router.push("/history"); }} /></div></div>
    {notice && <div className="warning-banner">{notice}</div>}
    <div className="detail-grid"><TranscriptPanel transcript={consultation.transcript} translation={consultation.translation ?? []} listening={false} kicker="Complete transcript" title="Conversation record" />
      <ClinicalRecordPanel record={record} updates={consultation.updates} onChange={(key, value) => setRecord((current) => current && ({ ...current, [key]: value }))} disabled={!reviewing} /><AuditTrail updates={consultation.updates} /></div>
    {reviewing && <div className="detail-review"><div><strong>Review before saving</strong><span>Check the transcript and edit any field that needs correction.</span></div><button className="primary-button" onClick={() => void approve()}>Approve & Save</button></div>}
    <section className="recordings-panel" data-testid="recordings"><div className="section-kicker">Session audio</div><h2><AudioLines size={16} /> Recordings</h2>{consultation.recordings.length === 0 ? <p className="muted">No audio was stored for this session. Audio is kept for sessions recorded with the local microphone.</p> : consultation.recordings.map((recording) => <div className="recording-item" key={recording.id}>{recording.available ? <audio controls preload="none" src={recordingAudioUrl(consultation.id, recording.id)} /> : <p className="muted">The audio file {recording.file_name} is missing.</p>}<div className="recording-meta"><span>{recording.file_name}</span><span>{formatDuration(recording.duration_ms)}</span><span>{FORMAT_LABELS[recording.format] ?? recording.format}</span>{recording.size_bytes > 0 && <span>{formatSize(recording.size_bytes)}</span>}{recording.language_code && <span>Language {recording.language_code}</span>}{recording.original_sha256 && <span title={`Original capture SHA-256: ${recording.original_sha256}\nStored file SHA-256: ${recording.sha256 ?? "unknown"}`}>Original SHA-256 <code>{recording.original_sha256.slice(0, 16)}…</code></span>}{recording.available && <a href={recordingAudioUrl(consultation.id, recording.id)} download={recording.file_name}>Download</a>}</div></div>)}</section>
  </div></AppShell>;
}
