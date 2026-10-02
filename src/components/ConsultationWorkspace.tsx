"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Pause, Play, Square, Waves } from "lucide-react";
import type { ClinicalRecord } from "@/lib/domain/types";
import type { RuntimeMode } from "@/lib/runtime-status";
import { addSegment, approveConsultation, type ConsultationState, stopConsultation } from "@/lib/consultations/api";
import { BrowserSpeechToTextProvider } from "@/lib/speech/browser-provider";
import { DemoSpeechToTextProvider } from "@/lib/speech/demo-provider";
import { LocalWebSocketSpeechProvider } from "@/lib/speech/local-websocket-provider";
import type { SpeechToTextProvider } from "@/lib/speech/provider";
import { AuditTrail } from "./AuditTrail";
import { ClinicalRecordPanel } from "./ClinicalRecordPanel";
import { TranscriptPanel } from "./TranscriptPanel";

export function ConsultationWorkspace({ initial, runtimeMode, languageCode = "auto" }: { initial: ConsultationState; runtimeMode: RuntimeMode; languageCode?: string }) {
  const [consultation, setConsultation] = useState(initial);
  const [record, setRecord] = useState<ClinicalRecord>(initial.record);
  const [running, setRunning] = useState(false);
  const [paused, setPaused] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState("");
  const providerRef = useRef<SpeechToTextProvider | null>(null);
  const segmentQueue = useRef(Promise.resolve());
  const nextSegmentSequence = useRef(0);
  const startedAt = useRef(Date.now());
  useEffect(() => { if (!running || paused) return; const timer = setInterval(() => setElapsed(Math.floor((Date.now() - startedAt.current) / 1000)), 1000); return () => clearInterval(timer); }, [running, paused]);
  const statusLabel = consultation.status === "IN_PROGRESS" ? running ? paused ? "Paused" : "Recording" : "Ready" : consultation.status === "READY_FOR_REVIEW" ? "Ready for review" : "Approved";
  const formatElapsed = useMemo(() => `${String(Math.floor(elapsed / 60)).padStart(2, "0")}:${String(elapsed % 60).padStart(2, "0")}`, [elapsed]);

  function receiveSegment(segment: Parameters<SpeechToTextProvider["start"]>[0] extends (segment: infer T) => void ? T : never) {
    segmentQueue.current = segmentQueue.current.then(async () => {
      try { const sourceId = segment.id ?? crypto.randomUUID(); const normalized = { ...segment, id: `${consultation.id}-${sourceId}`, sequence_number: segment.sequence_number ?? nextSegmentSequence.current++ }; const response = await addSegment(consultation.id, normalized); if (!response.duplicate) { setConsultation(response.consultation); setRecord(response.consultation.record); } } catch (err) { setError(err instanceof Error ? err.message : "Transcript update failed."); }
    });
  }
  async function startProvider(kind: "demo" | "microphone") { setError(""); const provider = kind === "demo" ? new DemoSpeechToTextProvider() : runtimeMode === "local" ? new LocalWebSocketSpeechProvider(consultation.id, languageCode) : new BrowserSpeechToTextProvider(); if (runtimeMode === "unknown" && kind !== "demo") { setError("Backend runtime status is unavailable; local microphone mode is disabled."); return; } providerRef.current = provider; providerRef.current.onError = setError; try { await provider.start(receiveSegment); setRunning(true); setPaused(false); if (elapsed === 0) startedAt.current = Date.now(); } catch (err) { provider.stop(); setError(err instanceof Error ? err.message : "Microphone unavailable. Local mode did not fall back to demo."); } }
  function togglePause() { if (!providerRef.current) return; if (paused) { void providerRef.current.start(receiveSegment); setPaused(false); } else { providerRef.current.pause(); setPaused(true); } }
  async function stop() { try { await providerRef.current?.stop(); setRunning(false); setPaused(false); await segmentQueue.current; const next = await stopConsultation(consultation.id); setConsultation(next); setRecord(next.record); } catch (err) { setError(err instanceof Error ? err.message : "Unable to stop consultation."); } }
  async function approve() { try { const next = await approveConsultation(consultation.id, record); setConsultation(next); setRecord(next.record); } catch (err) { setError(err instanceof Error ? err.message : "Unable to approve consultation."); } }
  function edit(key: keyof ClinicalRecord, value: unknown) { setRecord((current) => ({ ...current, [key]: value })); }

  const runtimeLabel = runtimeMode === "local" ? "Local AI" : runtimeMode === "demo" ? "Demo mode" : "Runtime unavailable";
  const runtimeDetail = runtimeMode === "local" ? "Microphone and inference stay on this machine" : runtimeMode === "demo" ? "Deterministic scripted consultation" : "Backend status unavailable";

  return <div className="workspace"><header className="consultation-masthead" data-testid="consultation-masthead"><div><div className="eyebrow">Live consultation</div><h1>Patient {consultation.patient.patient_identifier}</h1><p>{consultation.patient.name || "Unnamed patient"} <span>·</span> {consultation.patient.age} years <span>·</span> {consultation.patient.sex}</p></div><div className="masthead-status"><div className={`status-pill ${running && !paused ? "recording" : ""}`}><i /> {statusLabel}</div><div className="timer">{formatElapsed}</div></div></header><div className="control-strip"><div className="mode-note"><Waves size={17} /><span><strong>{runtimeLabel}</strong><small>{runtimeDetail}</small></span></div><div className="controls">{runtimeMode === "local" && <button className="primary-button microphone-button" onClick={() => void startProvider("microphone")} disabled={running || consultation.status !== "IN_PROGRESS"}><Waves size={15} /> Start local AI</button>}<button className="secondary-button" onClick={() => void startProvider("demo")} disabled={running || consultation.status !== "IN_PROGRESS"}><Play size={15} /> Start demo</button>{runtimeMode !== "local" && <button className="secondary-button" disabled><Waves size={15} /> Microphone unavailable</button>}<button className="icon-button" onClick={togglePause} disabled={!running} aria-label={paused ? "Resume" : "Pause"}>{paused ? <Play size={16} /> : <Pause size={16} />}</button><button className="stop-button" onClick={() => void stop()} disabled={!running}><Square size={14} /> Stop</button></div></div>{error && <div className="warning-banner">{error}</div>}<div className="workspace-grid"><TranscriptPanel transcript={consultation.transcript} listening={running && !paused} /><ClinicalRecordPanel record={record} updates={consultation.updates} onChange={edit} disabled={consultation.status === "APPROVED"} /></div><AuditTrail updates={consultation.updates} />{consultation.status === "READY_FOR_REVIEW" && <div className="review-banner"><div><strong>Review before saving</strong><span>Confirm the transcript and edit any field that needs correction.</span></div><button className="primary-button" onClick={() => void approve()}>Approve & Save</button></div>}{consultation.status === "APPROVED" && <div className="approved-banner"><strong>Approved and saved</strong><span>This consultation is now part of the linked history.</span></div>}</div>;
}
