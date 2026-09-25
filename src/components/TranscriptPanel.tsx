import { MessageSquareText } from "lucide-react";
import type { TranscriptSegmentInput } from "@/lib/domain/types";

export function TranscriptPanel({ transcript, listening }: { transcript: TranscriptSegmentInput[]; listening: boolean }) {
  return <section className="panel transcript-panel"><div className="panel-heading"><div><div className="section-kicker">Live transcript</div><h2>Conversation</h2></div>{listening && <span className="listening-chip"><i /> Listening</span>}</div>
    <div className="transcript-list">{transcript.length === 0 ? <div className="empty-state"><MessageSquareText size={28} /><strong>Your conversation will appear here</strong><span>Start Demo mode or connect your microphone to begin.</span></div> : transcript.map((segment) => <article className={`transcript-item ${segment.speaker.toLowerCase()}`} key={segment.id}><div className="transcript-meta"><span className="speaker-label">{segment.speaker === "UNKNOWN" ? "Speaker" : segment.speaker[0] + segment.speaker.slice(1).toLowerCase()}</span><time>{new Date(segment.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</time></div><p>“{segment.text}”</p></article>)}</div>
  </section>;
}
