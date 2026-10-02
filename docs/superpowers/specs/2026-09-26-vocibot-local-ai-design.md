# VociBot Local AI Pipeline Design

## Goal

Extend the VociBot MVP beyond deterministic demo mode so a local browser microphone can be processed by local speech activity detection, multilingual transcription, optional alignment and diarization, Ollama clinical extraction, evidence validation, doctor review, approval, and SQLite persistence. No paid or cloud AI APIs are introduced.

## Scope and constraints

- Runtime selection is controlled by `AI_MODE=demo|local`.
- Demo mode remains deterministic, offline, and unchanged for automated acceptance tests.
- Local mode uses Silero VAD, faster-whisper, optional WhisperX alignment, optional pyannote diarization, and Ollama.
- Whisper and Ollama model names, device, compute type, URLs, thresholds, and optional diarization settings are configurable through environment variables.
- Clinical extraction is conservative: every non-empty proposed field must reference transcript segment IDs; unsupported values are rejected; uncertainty is represented as `NEEDS_REVIEW`; absent information remains empty; assessment/diagnosis requires an explicit doctor statement.
- The requested mock EMR update is a local test boundary only. Authentication, production EMR integration, billing, insurance, analytics, diagnosis recommendations, and prescribing remain out of scope.

## Architecture

The browser local provider captures microphone PCM audio in short chunks and sends them to a local FastAPI WebSocket. The backend `LocalAudioPipeline` passes each chunk through VAD, faster-whisper, alignment, and diarization, then returns speaker-labelled transcript drafts. The existing consultation segment endpoint remains the persistence boundary.

After each accepted transcript segment, the consultation service selects the configured extraction provider. In local mode, Ollama receives the transcript and current record using a strict JSON contract. The evidence validator checks field values, source segment IDs, speaker attribution, uncertainty markers, and doctor-only fields before record diffing and audit persistence.

Provider loading is lazy so demo mode and unit tests do not require model packages or downloads. Missing local dependencies, model load failures, and unavailable Ollama are returned as explicit diagnostics/errors; local mode never silently changes to demo mode.

## Provider contracts

- `VoiceActivityDetector.detect(chunk) -> ActivityResult` reports speech probability and accepted/rejected status.
- `SpeechToTextProvider.transcribe(chunk) -> TranscriptDraft[]` returns multilingual text and timestamps.
- `WhisperXAligner.align(...) -> aligned segments` enriches timestamps when installed and configured.
- `DiarizationProvider.diarize(...) -> SpeakerTurn[]` maps turns to `DOCTOR`, `PATIENT`, or `UNKNOWN` using configured local labels; unsupported diarization remains explicit.
- `ClinicalExtractionProvider.extract(...) -> ExtractionResult` returns typed proposed fields, evidence segment IDs, and uncertainty state.
- `EvidenceValidator.validate(...) -> validated ExtractionResult` rejects unsupported evidence and prevents symptom-only diagnoses.

## Audio and API flow

1. Setup selects local mode and creates a consultation.
2. The browser requests microphone permission, converts captured audio to the configured PCM format, and streams chunks over a local WebSocket.
3. The backend emits pipeline status and transcript events; the client submits accepted transcript segments through the existing consultation API.
4. The backend performs extraction, validation, record diffing, and audit writes.
5. The doctor edits fields, stops the consultation, reviews the record, approves it, and reopens it from history.

The WebSocket protocol uses JSON envelopes with `type` values `ready`, `status`, `transcript`, `warning`, `error`, and `stopped`; binary audio frames are accompanied by sample-rate/channel metadata. The protocol is local-only and does not persist raw audio in the MVP.

## Failure handling and observability

The local pipeline records per-stage timing and structured error categories: VAD rejection, transcription error, speaker-attribution error, unsupported fact, omission, extraction error, and transport/model latency. These diagnostics are exposed in the local test report and shown as non-fatal warnings where the consultation can continue. Fatal initialization failures stop local mode with an actionable message.

## Verification

- Unit tests cover configuration, audio framing, VAD/STT/alignment/diarization adapters, Ollama JSON handling, evidence validation, and latency/error classification.
- Backend tests cover local pipeline orchestration and consultation persistence with injected fake local providers.
- Frontend tests cover local-mode selection, microphone fallback/error display, and transcript event handling.
- Existing lint, typecheck, unit, backend, build, and deterministic Playwright tests remain passing.
- A local smoke harness runs actual microphone or fixture audio through the configured providers, then executes mock EMR update, doctor edit, approval, persistence, and reopen. It records English and, when supported by the installed model/configuration, English plus an Indian-language/code-switched fixture. Hardware, dependency, model-download, and microphone limitations are reported separately.
