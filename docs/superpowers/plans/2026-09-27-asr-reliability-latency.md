# VociBot ASR Reliability and Latency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Improve measured local ASR reliability, live latency, final reconciliation, and cross-segment evidence extraction without weakening fail-closed clinical grounding.

**Architecture:** Preserve browser PCM capture, backend decode/resample, Silero VAD, faster-whisper, transcript commit, Ollama extraction, and evidence validation. Add explicit benchmark/diagnostic boundaries, asynchronous provisional/final transcript state, and a bounded complete-audio final pass at Stop.

**Tech Stack:** FastAPI/WebSocket, NumPy/SciPy, Silero VAD, faster-whisper, Ollama, SQLAlchemy/SQLite, React/Next.js, pytest, Playwright.

**Spec:** User request in the current conversation, especially the latest `test-100` Dolo 650 regression.

## Global Constraints

- Do not add authentication, production EMR integration, analytics, billing, RAG, or diarization work.
- Do not change the application default Whisper model until same-WAV measurements justify it.
- Preserve raw ASR text and evidence IDs; never infer absent clinical facts.
- Keep deterministic demo mode and real-model/hardware tests separate.
- Physical microphone acceptance remains explicitly distinct from fake-browser CI input.

## Review Focus

- The original `test-100` WAV may not contain the full persisted consultation; report capture/session mismatch rather than masking it.
- Soft speech must be distinguishable as missing from WAV, VAD rejection, Whisper omission, or delayed UI delivery.
- Overlap and out-of-order windows must not duplicate or reorder evidence.
- Final reconciliation must not overwrite reliable live evidence with lower-confidence text.
- Medication normalization must preserve uncertainty for `$650`/`Dolo 650` ambiguity.

### Task 1: Verify and preserve the primary regression fixture

**Files:**
- Create: `scripts/analyze_asr_fixture.py`
- Create: `docs/superpowers/reports/2026-09-27-test-100-asr-analysis.json`
- Test: `backend/tests/test_fixture_analysis.py`

- [ ] Add read-only fixture analysis for consultation metadata, WAV duration, RMS/peak/clipping/silence, debug windows, VAD decisions, ASR output, and capture-duration mismatch.
- [ ] Run it against consultation `738e3ddc-df81-48a2-b730-8294edd5de18` and preserve the original WAV unchanged.

### Task 2: Make streaming state explicit and measurable

**Files:**
- Modify: `backend/app/providers/streaming.py`
- Modify: `backend/app/api/audio.py`
- Modify: `backend/app/schemas.py`
- Modify: `src/lib/domain/types.ts`
- Modify: `src/lib/speech/local-websocket-provider.ts`
- Modify: `src/components/TranscriptPanel.tsx`
- Test: `backend/tests/test_streaming.py`, `backend/tests/test_audio_websocket.py`, `tests/browser/runtime-mode.spec.ts`

- [ ] Write failing tests for provisional/final transcript events, late/out-of-order windows, overlap replacement, and dropped chunks.
- [ ] Add a bounded rolling buffer with configurable window/overlap, immediate capture status, provisional transcript events, and finalized events.
- [ ] Ensure final segments are committed once and preserve relative timing/evidence boundaries.
- [ ] Measure first-text and finalization latency in debug reports; do not claim targets without measurements.

### Task 3: Add complete-audio final reconciliation

**Files:**
- Create: `backend/app/providers/reconciliation.py`
- Modify: `backend/app/api/audio.py`
- Modify: `backend/app/services/consultations.py`
- Modify: `scripts/manual_acceptance_report.py`
- Test: `backend/tests/test_reconciliation.py`, `backend/tests/test_audio_websocket.py`

- [ ] Write failing tests proving Stop performs one bounded final pass over the captured WAV and exposes live/final differences.
- [ ] Implement final ASR using the configured local provider, with explicit diagnostics and no demo fallback.
- [ ] Ensure final extraction consumes final transcript segments only, while preserving live diagnostics.

### Task 4: Support cross-segment clinical evidence

**Files:**
- Modify: `backend/app/providers/ollama_extraction.py`
- Modify: `backend/app/services/consultations.py`
- Modify: `backend/app/services/evidence.py`
- Test: `backend/tests/test_consultation_flow.py`, `backend/tests/test_evidence_validator.py`, `backend/tests/test_extraction.py`

- [ ] Add failing tests for `"I've had it for"` + `"Two weeks"`, multi-symptom adjacent segments, negative statements, and unsupported facts.
- [ ] Pass a bounded rolling transcript context to extraction and require candidates to cite all supporting segment IDs.
- [ ] Preserve NEEDS_REVIEW/REJECTED behavior when any required support is absent.

### Task 5: General clinical terminology uncertainty handling

**Files:**
- Create: `backend/app/services/clinical_normalization.py`
- Modify: `backend/app/services/evidence.py`
- Modify: `backend/app/providers/ollama_extraction.py`
- Test: `backend/tests/test_clinical_normalization.py`, `backend/tests/test_evidence_validator.py`

- [ ] Add failing tests for `Dolo 650`, `$650`, unrelated numeric amounts, and ambiguous medication context.
- [ ] Implement conservative context-aware candidates that retain raw text and mark uncertain normalization NEEDS_REVIEW.
- [ ] Never convert a number to a medication without transcript/context support.

### Task 6: Same-WAV benchmark and manual acceptance reporting

**Files:**
- Modify: `scripts/benchmark_whisper_models.py`
- Modify: `scripts/manual_acceptance_report.py`
- Create: `docs/superpowers/reports/2026-09-27-test-100-benchmark.json`
- Test: `backend/tests/test_benchmark_metrics.py`

- [ ] Add metrics for first-text latency, finalized latency, RTF, speech/silence, omissions, duplication, boundary errors, and clinical entity recall.
- [ ] Benchmark the currently available model and stronger locally compatible models on the same verified WAV; report unavailable models exactly.
- [ ] Add physical microphone acceptance instructions for close, desk-distance, soft, normal, background, and code-switched tests.

### Task 7: Full verification

- [ ] Run backend unit/integration tests, frontend tests, typecheck, lint, build, and browser E2E.
- [ ] Run the local browser microphone path and record actual latency/results separately from fake-device CI.
- [ ] Report remaining limitations and do not label the system production-ready without physical acceptance evidence.
