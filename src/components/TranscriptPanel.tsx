"use client";

import { useState } from "react";
import { Languages, MessageSquareText } from "lucide-react";
import type { TranscriptSegmentInput } from "@/lib/domain/types";

type TranslationLine = { id: string; text: string; timestamp: string; speaker?: string };

/** "Doctor" / "Patient" from a recognised role; "Speaker" when unknown. */
export function speakerName(speaker?: string) {
  return speaker === "DOCTOR" ? "Doctor" : speaker === "PATIENT" ? "Patient" : "Speaker";
}

export function TranscriptPanel({ transcript, listening, partial = "", translation = [], kicker = "Live transcript", title = "Conversation" }: { transcript: TranscriptSegmentInput[]; listening: boolean; partial?: string; translation?: TranslationLine[]; kicker?: string; title?: string }) {
  const [view, setView] = useState<"original" | "english">("original");
  const english = view === "english" && translation.length > 0;
  return <section className="panel transcript-panel paper-panel"><div className="panel-heading"><div><div className="section-kicker">{kicker}</div><h2>{title}</h2></div>{listening && <span className="listening-chip"><i /> Listening</span>}
    {translation.length > 0 && <div className="view-toggle" role="group" aria-label="Transcript language"><button type="button" aria-pressed={!english} onClick={() => setView("original")}>Original</button><button type="button" aria-pressed={english} onClick={() => setView("english")}><Languages size={13} /> English</button></div>}</div>
    {english && <p className="translation-note">English translation. The note is written from it; check important details against the original. Doctor and patient are recognised from what is said.</p>}
    <div className="transcript-list" data-testid={english ? "translation-list" : "transcript-list"}>{english ? translation.map((line) => <article className={`transcript-item ${(line.speaker ?? "unknown").toLowerCase()}`} key={line.id}><div className="transcript-meta"><span className="speaker-label">{speakerName(line.speaker)}</span><time>{line.timestamp}</time></div><p>“{line.text}”</p></article>) : transcript.length === 0 && !partial ? <div className="empty-state"><MessageSquareText size={28} /><strong>Your conversation will appear here</strong><span>Start Demo mode or connect your microphone to begin.</span></div> : transcript.map((segment) => <article className={`transcript-item ${segment.speaker.toLowerCase()}`} key={segment.id}><div className="transcript-meta"><span className="speaker-label">{speakerName(segment.speaker)}</span><time>{/^\d{2}:\d{2}:\d{2}$/.test(segment.timestamp) ? segment.timestamp : new Date(segment.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</time></div><p>“{segment.text}”</p></article>)}{!english && partial && <article className="transcript-item partial" aria-live="polite" data-testid="partial-transcript"><div className="transcript-meta"><span className="speaker-label">Speaker</span><time>listening…</time></div><p>“{partial}”</p></article>}</div>
  </section>;
}
