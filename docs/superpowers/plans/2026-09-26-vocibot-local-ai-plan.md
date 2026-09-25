# VociBot Local AI Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement an explicit `AI_MODE=demo|local` pipeline from browser microphone audio through local VAD, multilingual STT, alignment, diarization, Ollama extraction, evidence validation, doctor approval, and persistence.

**Architecture:** Preserve the existing consultation API and deterministic demo providers. Add a local FastAPI WebSocket audio pipeline with lazy-loaded Silero, faster-whisper, WhisperX, and pyannote adapters; accepted transcript events continue through the existing segment endpoint, which selects demo or Ollama extraction and validates evidence before persistence.

**Tech Stack:** FastAPI WebSockets, Pydantic, SQLAlchemy, faster-whisper, silero-vad, WhisperX, pyannote.audio, Ollama HTTP API, Next.js/React Web Audio, TypeScript, pytest, Node test runner, Playwright.

**Spec:** `docs/superpowers/specs/2026-09-26-vocibot-local-ai-design.md`

## Global Constraints

- Runtime selection is controlled by `AI_MODE=demo|local`.
- Demo mode remains deterministic, offline, and unchanged for automated acceptance tests.
- Local mode never silently falls back when a dependency, model, or Ollama is unavailable; expose exact diagnostics.
- Every non-empty clinical value must reference transcript segment IDs; unsupported values are rejected and ambiguity is `NEEDS_REVIEW`.
- Assessment/diagnosis requires an explicit DOCTOR statement and is never inferred from symptoms alone.
- Do not add authentication, production EMR integration, billing, insurance, analytics, diagnosis recommendations, or prescribing.

## Review Focus

- Local mode with a missing package/model must return the exact failure instead of selecting demo mode — configuration and adapter tests.
- Audio chunks that contain no speech must not create transcript rows — pipeline tests.
- Diarization unavailable or uncertain must preserve `UNKNOWN`, never fabricate DOCTOR/PATIENT attribution — diarization tests.
- Ollama output with nonexistent evidence IDs or symptom-only assessment must be rejected — evidence tests.
- Browser microphone denial must show a local-mode error and keep demo mode available — frontend/E2E tests.

---

### Task 1: Configuration, provider selection, and evidence contract

**Files:**
- Modify: `backend/app/config.py`, `backend/app/providers/extraction.py`, `backend/app/services/evidence.py`, `backend/app/services/consultations.py`
- Create: `backend/app/providers/factory.py`, `backend/tests/test_local_config.py`, `backend/tests/test_evidence_validator.py`
- Modify: `.env.example`

**Interfaces:**
- `Settings.ai_mode`, `whisper_model`, `whisper_device`, `whisper_compute_type`, `silero_threshold`, `ollama_model`, and local provider settings.
- `build_extraction_provider()` selects Demo or Ollama explicitly and raises `LocalProviderError` with the dependency/model detail on local failure.
- `EvidenceValidator.validate_extraction(result, transcript)` returns a validated `ExtractionResult` with invalid candidates rejected and uncertain candidates marked `NEEDS_REVIEW`.

- [ ] Write failing tests for `AI_MODE=local`, configurable `small` default model, explicit missing local dependency error, source-ID rejection, and symptom-only assessment rejection.
- [ ] Run the focused pytest tests and confirm they fail for missing settings/factory/validator behavior.
- [ ] Implement settings, provider selection, strict extraction validation, and consultation-service injection without changing demo defaults.
- [ ] Run focused tests and the existing backend extraction/consultation tests; expect all to pass.
- [ ] Commit `feat: add explicit local ai configuration and evidence gate`.

### Task 2: Real local audio adapters and pipeline orchestration

**Files:**
- Modify: `backend/app/providers/speech.py`, `backend/app/providers/vad.py`, `backend/app/providers/alignment.py`, `backend/app/providers/diarization.py`
- Create: `backend/app/providers/local_pipeline.py`, `backend/tests/test_local_providers.py`, `backend/tests/test_local_pipeline.py`

**Interfaces:**
- `ActivityResult(probability, has_speech, latency_ms)` and `SileroVoiceActivityDetector.detect(chunk)`.
- `FasterWhisperProvider.transcribe(chunk)` returns multilingual `TranscriptDraft` values with absolute timestamps.
- `WhisperXAligner.align(segments, audio, sample_rate)` and `PyannoteDiarizationProvider.diarize(audio, sample_rate)` are lazy and explicit about missing models/dependencies.
- `LocalAudioPipeline.process(chunk) -> PipelineResult` returns transcript drafts, stage timings, warnings, and structured error categories.

- [ ] Write failing tests with injected fake models for VAD filtering, multilingual transcription timestamps, alignment propagation, speaker-turn mapping, and latency/error diagnostics.
- [ ] Run focused tests and confirm the new adapter methods/pipeline do not exist.
- [ ] Implement lazy adapters, model configuration, optional alignment/diarization integration, and no-fallback error handling.
- [ ] Run focused tests and all backend tests; expect all to pass.
- [ ] Commit `feat: implement local audio inference providers`.

### Task 3: FastAPI WebSocket and mock EMR diagnostic boundary

**Files:**
- Modify: `backend/app/main.py`, `backend/app/api/consultations.py`
- Create: `backend/app/api/audio.py`, `backend/app/services/diagnostics.py`, `backend/tests/test_audio_websocket.py`, `backend/tests/test_diagnostics.py`

**Interfaces:**
- WebSocket `/api/consultations/{id}/audio` accepts a JSON metadata envelope then binary PCM frames and emits `ready`, `status`, `transcript`, `warning`, `error`, and `stopped` messages.
- `LocalPipelineDiagnostics` records stage timings and categories: VAD rejection, transcription error, speaker-attribution error, unsupported fact, omission, extraction error, transport/model latency.
- `MockEMRUpdater.update(record) -> MockEMRResult` is local-only and used by the smoke harness, not the consultation API.

- [ ] Write failing WebSocket tests for ready/status/transcript flow, silence filtering, exact missing-model error, and stopped event.
- [ ] Run focused tests and verify failure.
- [ ] Implement the WebSocket endpoint, injected pipeline factory, diagnostics, and mock EMR boundary.
- [ ] Run focused tests and backend suite; expect all to pass.
- [ ] Commit `feat: stream local audio through fastapi websocket`.

### Task 4: Browser local microphone provider and mode-aware UI

**Files:**
- Modify: `src/lib/speech/provider.ts`, `src/lib/speech/browser-provider.ts`, `src/components/ConsultationWorkspace.tsx`, `src/components/ConsultationSetup.tsx`, `src/app/globals.css`
- Create: `src/lib/speech/local-websocket-provider.ts`, `tests/local-provider.test.ts`
- Modify: `tests/browser/vocibot.spec.ts`

**Interfaces:**
- `LocalWebSocketSpeechProvider` implements the existing `SpeechToTextProvider`, captures microphone PCM frames, streams metadata/binary chunks, and maps transcript/error events to callbacks.
- UI derives mode from `NEXT_PUBLIC_AI_MODE`, labels local mode explicitly, shows exact local diagnostics, and retains Start demo in every mode.

- [ ] Write failing TypeScript tests for local event mapping, metadata framing, local error surfacing, and demo-provider preservation.
- [ ] Run focused tests and confirm failure.
- [ ] Implement AudioWorklet/ScriptProcessor-compatible PCM capture, WebSocket lifecycle, mode-aware provider selection, and UI diagnostics.
- [ ] Run focused tests, typecheck, lint, and deterministic browser tests; expect all to pass.
- [ ] Commit `feat: connect browser microphone to local ai mode`.

### Task 5: Local smoke harness and consultation reopen flow

**Files:**
- Create: `scripts/local_smoke.py`, `backend/tests/fixtures/english_consultation.wav`, `backend/tests/fixtures/code_switched_consultation.wav`, `docs/superpowers/reports/2026-09-26-vocibot-local-smoke.md`
- Modify: `README.md`, `.env.example`, `backend/pyproject.toml`, `package.json`

**Interfaces:**
- `scripts/local_smoke.py --audio <path> --mode local` runs fixture/microphone input through the actual configured adapters, mock EMR update, doctor edit, approval, persistence, and reopen; it emits JSON diagnostics and a Markdown report.
- The report records Mac hardware/architecture, available RAM, tested Whisper/Ollama models, whether Silero/WhisperX/pyannote executed, transcription/extraction latency, unsupported facts/omissions, and exact unavailable-component reasons.

- [ ] Write failing harness tests for report schema, mock EMR update, doctor edit/approval/reopen sequencing, and clear unavailable-model reporting.
- [ ] Run focused tests and confirm failure.
- [ ] Implement the harness and documentation with a practical default Whisper model and configurable `large-v3`/Ollama model.
- [ ] Run the actual local smoke test on this Mac, first with available installed models/dependencies and then with a fixture if microphone capture is unavailable; save the report and record every limitation.
- [ ] Commit `feat: add reproducible local ai smoke test`.

### Task 6: Full verification and handoff

- [ ] Run `npm test`, `.venv/bin/pytest -q`, `npm run typecheck`, `npm run lint`, `npm run build`, `npm run test:e2e`, and `git diff --check`.
- [ ] Re-run the local smoke command after the full suite and update the report if model/runtime behavior changed.
- [ ] Verify the exact local launch command in README, including backend/frontend environment variables and browser microphone permissions.
- [ ] Commit `docs: document local ai setup and smoke results`.
