"use client";

import { useEffect, useRef, useState } from "react";
import { Mic, RotateCcw, Square, Trash2, UserRound } from "lucide-react";
import { deleteVoiceProfile, enrolVoice, listVoiceProfiles, SentenceRecorder, type VoiceProfile } from "@/lib/voice-profiles";

// A mix of the doctor's usual phrases in English and Telugu, 3-5 s each.
export const SENTENCES = [
  "Good morning, please sit down. What brings you in today?",
  "How many days have you had the fever and the cough?",
  "Let me check your blood pressure and your temperature.",
  "Take this tablet twice a day after food, for five days.",
  "నమస్కారం అండి, కూర్చోండి. చెప్పండి, ఏం ఇబ్బంది ఉంది?",
  "జ్వరం ఎన్ని రోజుల నుంచి ఉంది? దగ్గు కూడా ఉందా?",
  "ఈ మాత్రలు రోజుకు రెండు సార్లు, భోజనం తర్వాత వేసుకోండి.",
  "రిపోర్టులు వచ్చాక మళ్ళీ వచ్చి కలవండి.",
];
const MINIMUM = 5;

export function VoiceEnrolment() {
  const [available, setAvailable] = useState<boolean | null>(null);
  const [profiles, setProfiles] = useState<VoiceProfile[]>([]);
  const [enrolling, setEnrolling] = useState(false);
  const [name, setName] = useState("");
  const [recordings, setRecordings] = useState<Array<Float32Array | null>>(() => SENTENCES.map(() => null));
  const [active, setActive] = useState<number | null>(null);
  const [sampleRate, setSampleRate] = useState(48_000);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const recorder = useRef<SentenceRecorder | null>(null);
  const load = () => listVoiceProfiles().then((loaded) => { setAvailable(loaded.available); setProfiles(loaded.profiles); }).catch((err) => setError(err instanceof Error ? err.message : "Unable to load voice profiles."));
  useEffect(() => { void load(); }, []);
  const recorded = recordings.filter(Boolean).length;

  async function toggle(index: number) {
    setError("");
    if (active === index) {
      const current = recorder.current!;
      const audio = await current.stop();
      setSampleRate(current.sampleRate);
      recorder.current = null;
      setActive(null);
      if (audio.length < current.sampleRate * 1.5) setError("That was too short; read the whole sentence.");
      setRecordings((current) => current.map((item, position) => position === index ? audio : item));
      return;
    }
    if (active !== null) return;
    try {
      recorder.current = new SentenceRecorder();
      await recorder.current.start();
      setActive(index);
    } catch {
      recorder.current = null;
      setError("The microphone is not available. Allow VociBot to use it and try again.");
    }
  }

  async function save() {
    setBusy(true); setError("");
    try {
      const profile = await enrolVoice(name.trim(), sampleRate, recordings.filter((item): item is Float32Array => item !== null));
      setMessage(`${profile.name}'s voice is saved. New consultations will mark their lines as Doctor.`);
      setEnrolling(false); setName(""); setRecordings(SENTENCES.map(() => null));
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to save the voice.");
    } finally {
      setBusy(false);
    }
  }

  async function remove(profile: VoiceProfile) {
    await deleteVoiceProfile(profile.id).catch(() => undefined);
    setMessage(`${profile.name}'s voice was removed.`);
    await load();
  }

  return <section className="settings-card voice-card" data-testid="voice-enrolment">
    <div className="voice-heading"><div><h2><UserRound size={17} /> Doctor voice</h2><p>Record the doctor reading a few sentences once. After each consultation VociBot compares every line with this voice: lines in the doctor&apos;s voice are marked Doctor, anyone else (the patient, a relative, an attendant) Patient. Only a voice fingerprint is kept, not the recordings.</p></div></div>
    {error && <div className="warning-banner" role="alert">{error}</div>}
    {message && <div className="notice-banner" role="status">{message}</div>}
    {available === false && <p className="muted">The voice model is not installed on this computer, so doctor and patient are recognised from what is said only.</p>}
    {profiles.length > 0 && <ul className="voice-list">{profiles.map((profile) => <li key={profile.id}><span><strong>{profile.name}</strong><small>{profile.samples} sentences · enrolled {new Date(profile.created_at).toLocaleDateString()}</small></span><button type="button" className="secondary-button" onClick={() => void remove(profile)} aria-label={`Remove ${profile.name}'s voice`}><Trash2 size={14} /> Remove</button></li>)}</ul>}
    {available && !enrolling && <button type="button" className="primary-button" onClick={() => { setEnrolling(true); setMessage(""); }}><Mic size={14} /> {profiles.length ? "Add another doctor" : "Record the doctor's voice"}</button>}
    {available && enrolling && <div className="enrolment">
      <label className="enrol-name">Doctor&apos;s name<input id="voice-doctor-name" value={name} onChange={(event) => setName(event.target.value)} placeholder="e.g. Dr Ravi" /></label>
      <p className="muted">Use the microphone you use in clinic, in a quiet room. Read each sentence naturally; record at least {MINIMUM}.</p>
      <ol className="sentence-list">{SENTENCES.map((sentence, index) => <li key={sentence} className={recordings[index] ? "done" : ""}><span lang={/[ఀ-౿]/.test(sentence) ? "te" : "en"}>{sentence}</span><button type="button" className={active === index ? "stop-button" : "secondary-button"} onClick={() => void toggle(index)} disabled={busy || (active !== null && active !== index)} aria-label={active === index ? `Stop recording sentence ${index + 1}` : recordings[index] ? `Record sentence ${index + 1} again` : `Record sentence ${index + 1}`}>{active === index ? <><Square size={13} /> Stop</> : recordings[index] ? <><RotateCcw size={13} /> Again</> : <><Mic size={13} /> Record</>}</button></li>)}</ol>
      <div className="settings-actions"><button type="button" className="primary-button" onClick={() => void save()} disabled={busy || active !== null || recorded < MINIMUM || !name.trim()}>{busy ? "Saving…" : `Save voice (${recorded}/${SENTENCES.length} recorded)`}</button><button type="button" className="secondary-button" onClick={() => { void recorder.current?.stop(); recorder.current = null; setActive(null); setEnrolling(false); setRecordings(SENTENCES.map(() => null)); }} disabled={busy}>Cancel</button></div>
    </div>}
  </section>;
}
