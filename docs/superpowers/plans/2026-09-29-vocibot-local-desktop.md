# VociBot Local Desktop Prototype Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and verify a macOS desktop prototype that runs VociBot's transcription and conservative note drafting locally, beginning with Indian English, Telugu, Hindi, Marathi, and Gujarati.

**Architecture:** Preserve the existing Next.js UI and FastAPI API. Add an Electron shell that manages a loopback-only local runtime, and keep ASR engines behind a Python provider contract so Whisper and an Indic-focused engine can be evaluated without changing the consultation API. Package the backend as a sidecar and store the SQLite database under the app's user-data directory. Model setup is explicit and separate from offline consultation use; future healthcare connectors consume approved-note data but are not part of this plan.

**Tech Stack:** Next.js 15, React 19, TypeScript, FastAPI, Python 3.11+, SQLite, Electron, faster-whisper, candidate AI4Bharat IndicConformer/NeMo ASR, Ollama.

**Spec:** `docs/superpowers/specs/2026-09-29-vocibot-local-desktop-design.md`

## Global Constraints

- Runtime selection is controlled by `AI_MODE=demo|local`.
- Audio, transcripts, inference, and local persistence stay on the device. No cloud fallback.
- A clinician reviews and edits proposed notes before approval. The tool does not diagnose, prescribe, or submit to an external system.
- The immediate delivery target is a functional, locally installed macOS prototype. Public distribution, Windows packaging, and live SAP/healthcare SaaS connections are out of scope.
- Existing uncommitted changes in the repository are user work and must be preserved.
- Raw audio is not persisted by default.
- Preserve original-language transcript text and script as the source of truth.
- All network listeners are loopback-only; no telemetry or cloud AI calls are added.
- Do not claim “all languages work accurately” until representative recordings are evaluated.

## Review Focus

- Missing ASR or extraction models must show setup/error state and never switch silently to demo or cloud; test runtime-status and transcription initialization failure.
- Explicit language selection and uncertain automatic detection must not discard or mislabel source speech; test language-hint propagation and confidence diagnostics.
- Hindi/English or other code-switching may produce mixed scripts; test source transcript preservation and uncertainty signaling.
- Desktop startup/shutdown must not kill unrelated processes or expose the API to LAN; test child-process ownership, loopback binding, and failed health-check cleanup.
- Offline mode after provisioning must not attempt network access and must complete inference; test with network calls blocked and local fixture models/audio.

---

## File Structure

- `desktop/main.cjs` — Electron main process; spawn/monitor packaged web and API processes, wait for health, open the renderer, and stop owned children.
- `desktop/preload.cjs` — minimal context-isolated bridge for app status and native microphone permission/device UX.
- `electron-builder.yml` — macOS app packaging configuration and sidecar/resource inclusion.
- `package.json` — desktop development/build/package scripts and pinned Electron packaging dependencies.
- `next.config.ts` — production standalone output for embedding the existing Next server.
- `backend/app/config.py` — ASR engine and selected-language settings.
- `backend/app/providers/speech.py` — stable provider protocol and existing Whisper adapter language hint.
- `backend/app/providers/indic_conformer.py` — lazy local IndicConformer adapter, isolated optional dependency.
- `backend/app/providers/factory.py` — configured ASR provider creation and actionable failure mapping.
- `backend/app/api/audio.py` — construct selected provider and pass explicit language from stream setup.
- `backend/app/providers/local_pipeline.py` — keep source text and language diagnostics through VAD/ASR/reconciliation.
- `backend/app/services/runtime_status.py` — model readiness and local engine diagnostics.
- `src/components/ConsultationSetup.tsx` — initial language choice and visible local-runtime readiness.
- `src/lib/speech/local-websocket-provider.ts` — include language preference in local stream initialization.
- `backend/tests/test_local_providers.py`, new `backend/tests/test_indic_conformer.py`, and `backend/tests/test_audio_websocket.py` — provider/language contract and failure behavior.
- `tests/browser/local-audio.spec.ts` and new `tests/browser/desktop-runtime.spec.ts` — local flow and renderer runtime behavior.
- `scripts/package_macos.sh` — reproducible macOS artifact build and smoke-test entrypoint.
- `README.md` — development, model provisioning, offline setup, privacy, and packaged-app verification instructions.

## Task 1: Prove Local Indic ASR Feasibility and Lock Provider Contract

**Files:**
- Modify: `backend/app/providers/speech.py`
- Modify: `backend/app/providers/factory.py`
- Modify: `backend/app/config.py`
- Create: `backend/app/providers/indic_conformer.py`
- Modify: `backend/pyproject.toml`
- Test: `backend/tests/test_provider_interfaces.py`
- Test: `backend/tests/test_local_providers.py`
- Test: `backend/tests/test_indic_conformer.py`

**Interfaces:**
- `SpeechToTextProvider.transcribe_chunk(chunk: AudioChunk, language: str | None = None) -> list[TranscriptDraft]` is the common contract; update Whisper to accept the optional language hint.
- `IndicConformerProvider(model_path: str, device: str = "auto")` loads lazily and returns the same transcript draft type plus `last_diagnostics` with language and confidence/status.
- Existing `stt_provider` setting (environment variable `STT_PROVIDER`) accepts `whisper` or `indic_conformer`; set its default to `whisper` so local mode preserves the current `FasterWhisperProvider` behavior (demo mode continues to bypass local ASR).

- [x] **Step 1: Add provider contract tests** asserting explicit-language forwarding to Whisper, lazy Indic provider loading, original script preservation, and an actionable missing-NeMo/model error.
- [x] **Step 2: Run the focused tests and verify the new cases fail for the missing contract/provider.** Run: `.venv/bin/pytest backend/tests/test_provider_interfaces.py backend/tests/test_indic_conformer.py -q`. Expected: new assertions fail before implementation.
- [x] **Step 3: Implement the optional language parameter and lazy provider adapter.** Keep NeMo in an optional `indic-asr` extra; do not import it in demo or Whisper-only mode. Use the existing `stt_provider` setting and a configured local checkpoint path.
- [x] **Step 4: Run focused provider tests and validate actual IndicConformer load/inference on this Mac if a local checkpoint is provisioned.** No checkpoint/runtime was available; inability is recorded as an unverified engine rather than a passing transcription result.
- [x] **Step 5: Commit only Task 1 files.** Intentionally not committed because task files overlap pre-existing uncommitted user changes; the index was left untouched.

## Task 2: Carry Language Choice Through Audio and Clinical Review

**Files:**
- Modify: `backend/app/api/audio.py`
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/models.py`
- Modify: `backend/app/db.py`
- Modify: `backend/app/services/consultations.py`
- Modify: `backend/app/providers/local_pipeline.py`
- Modify: `backend/app/services/runtime_status.py`
- Modify: `src/components/ConsultationSetup.tsx`
- Modify: `src/lib/speech/local-websocket-provider.ts`
- Modify: `src/lib/domain/types.ts`
- Test: `backend/tests/test_audio_websocket.py`
- Test: `backend/tests/test_local_pipeline.py`
- Create: `backend/tests/test_schema_migrations.py`
- Test: `tests/browser/local-audio.spec.ts`

**Interfaces:**
- WebSocket start envelope adds optional `language: string`; accepted codes initially `en`, `te`, `hi`, `mr`, `gu`, plus `auto`.
- `LocalAudioPipeline.process(chunk: AudioChunk, language: str | None = None) -> PipelineResult` passes the hint to ASR and reports detected language/probability in diagnostics.
- Transcript segments persist optional `language_code` so later extraction has language context; startup migration adds the column to existing SQLite databases without losing saved consultations.
- Runtime status reports selected engine, available model, and missing dependency/setup message without exposing local filesystem secrets.

- [x] **Step 1: Test that the browser sends selected language, backend validates supported codes, low-confidence detection remains visible without deleting a transcript, and startup migration preserves an existing database while adding nullable `language_code`.**
- [x] **Step 2: Run targeted Python and frontend tests; confirm failures are due to missing language propagation/status.** Run: `.venv/bin/pytest backend/tests/test_audio_websocket.py backend/tests/test_local_pipeline.py -q`; `npm test -- tests/local-provider.test.ts`.
- [x] **Step 3: Implement language preference propagation, initial language selector, `language_code` persistence/migration, and explicit runtime readiness/errors.** Preserve demo behavior and original-language transcript strings.
- [x] **Step 4: Run targeted tests, `npm run typecheck`, and `npm run lint`.**
- [x] **Step 5: Commit only Task 2 files.** Intentionally not committed due overlapping dirty user files; see ledger.

## Task 3: Make Local Note Extraction Reviewable Across the Initial Languages

**Files:**
- Modify: `backend/app/providers/ollama_extraction.py`
- Modify: `backend/app/services/evidence.py`
- Modify: `backend/app/services/clinical_normalization.py`
- Create: `backend/app/services/approved_note_export.py`
- Modify: `backend/app/services/runtime_status.py`
- Test: `backend/tests/test_extraction.py`
- Test: `backend/tests/test_evidence_validator.py`
- Test: `backend/tests/test_clinical_normalization.py`
- Create: `backend/tests/test_approved_note_export.py`
- Test: `backend/tests/test_consultation_flow.py`

**Interfaces:**
- Extractor input retains original transcript segments and their language metadata; any translation is derived, local-only, and never replaces source evidence.
- Existing typed `ExtractionResult` and source-segment IDs remain the only persistence contract.
- `ApprovedNotePayload` is versioned (`schema_version: "1"`), can be created only from an approved consultation, and contains the clinician-approved structured note plus provenance IDs; it performs no network I/O.

- [ ] **Step 1: Add tests for regional-language unsupported facts, translated text not being treated as original evidence, extractor failure leaving the transcript editable with no ungrounded update, and approved-note export rejecting non-approved consultations.**
- [ ] **Step 2: Run targeted backend tests and verify they fail on the missing provenance behavior.**
- [ ] **Step 3: Implement only the evidence/provenance behavior needed by the test and the versioned approved-note payload.** Do not add automatic diagnosis or prescription behavior; if a local language-capable extraction/translation model is unavailable, fail closed to transcript review.
- [ ] **Step 4: Run all backend tests and inspect the persisted audit/source segment IDs.**
- [ ] **Step 5: Commit only Task 3 files.**

## Task 4: Package the Existing App as a Managed macOS Desktop Runtime

**Files:**
- Create: `desktop/main.cjs`
- Create: `desktop/preload.cjs`
- Create: `desktop/runtime-manager.cjs`
- Create: `electron-builder.yml`
- Modify: `package.json`
- Modify: `next.config.ts`
- Modify: `backend/app/main.py`
- Modify: `backend/app/config.py`
- Create: `backend/VociBot.spec`
- Create: `scripts/package_macos.sh`
- Create: `tests/desktop/runtime-manager.test.ts`
- Create: `tests/browser/desktop-runtime.spec.ts`
- Test: `backend/tests/test_runtime_security.py`

**Interfaces:**
- `desktop/runtime-manager.cjs` exports `startRuntime({ spawn, appDataPath, resourcesPath }) -> Promise<{ stop(): Promise<void> }>`; it owns only its child processes and resolves only after `GET http://127.0.0.1:8000/health` succeeds.
- Packaged Next standalone server listens on `127.0.0.1:3000`; FastAPI binds to `127.0.0.1:8000`; `NEXT_PUBLIC_API_URL` remains `http://127.0.0.1:8000` in the packaged renderer.
- FastAPI database URL is set to a SQLite file under Electron `app.getPath("userData")`, never the app bundle or current working directory.
- Preload exposes only typed runtime status and native permission/device functions; renderer has `nodeIntegration: false`, `contextIsolation: true`, and no arbitrary shell execution.

- [ ] **Step 1: Add tests for loopback-only bind configuration, startup timeout cleanup, graceful app shutdown, owned-child-only termination, and app-data SQLite path.**
- [ ] **Step 2: Run the new tests and verify they fail before the desktop process manager/security configuration exists.** Run: `npm test -- tests/desktop/runtime-manager.test.ts` and `.venv/bin/pytest backend/tests/test_runtime_security.py -q`.
- [ ] **Step 3: Add Electron main/preload, production Next standalone build, and PyInstaller-packaged FastAPI sidecar launch.** Use fixed loopback ports 3000/8000 and actionable conflict errors; never expose API ports on LAN.
- [ ] **Step 4: Run package smoke tests and create the `.app` artifact under `dist/` on macOS.** Verify microphone permission, frontend/backend readiness, local persistence, and graceful shutdown.
- [ ] **Step 5: Commit only Task 4 files.**

## Task 5: Provision Models and Verify Truly Offline Inference

**Files:**
- Modify: `backend/app/services/runtime_status.py`
- Create: `scripts/provision_local_models.py`
- Modify: `README.md`
- Modify: `scripts/local_smoke.py`
- Test: `backend/tests/test_runtime_status.py`
- Test: `tests/browser/desktop-runtime.spec.ts`

**Interfaces:**
- `scripts/provision_local_models.py --engine <whisper|indic_conformer|ollama> --model <name> [--language <code>]` downloads only explicitly selected model assets when online, verifies expected files/model tags, and prints local storage paths.
- Runtime readiness is `ready`, `missing_model`, `missing_dependency`, or `service_unavailable`; no automatic cloud/demo fallback.
- Ollama is a separately installed local runtime. The desktop app may start it only when no Ollama service is already reachable and it can locate the executable; it stops only a daemon it started. Otherwise the UI provides a precise install/start/model instruction.

- [ ] **Step 1: Test missing model, missing dependency, available model, and Ollama unavailable states.**
- [ ] **Step 2: Run focused tests and confirm the readiness states fail before implementation.**
- [ ] **Step 3: Implement explicit model provisioning and actionable first-run setup guidance.** Keep models separate from the app bundle so users can provision only languages they need.
- [ ] **Step 4: Provision available target-language models; run the local audio smoke test with network disabled after provisioning.** Record model versions, engine, device, per-language WER/CER where reference transcripts exist, latency, and missing fixture languages. Never substitute demo output.
- [ ] **Step 5: Commit only Task 5 files.**

## Task 6: Full Acceptance and Handoff

**Files:**
- Modify: `README.md`
- Modify: `scripts/package_macos.sh`
- Create/update: `docs/superpowers/reports/local-desktop-acceptance.json`
- Tests: full existing backend/frontend/browser suites and packaged-app smoke test

- [ ] **Step 1: Run `.venv/bin/pytest -q`, `npm test`, `npm run typecheck`, `npm run lint`, `npm run build`, and `npm run test:e2e`.**
- [ ] **Step 2: Build the macOS app and run the package smoke flow end-to-end with no network after model provisioning.**
- [ ] **Step 3: Attach real de-identified recordings and reference transcripts for each initial language if available; report per-language measured quality separately.** If no reference audio is supplied, mark language accuracy as unvalidated rather than complete.
- [ ] **Step 4: Review `git status` and ensure no pre-existing user changes were staged or overwritten; commit only acceptance docs/scripts created by this task.**

## Self-Review Notes

- Spec coverage: Tasks 1–2 cover provider selection and language behavior; Task 3 covers provenance, clinician-approved export boundary, and conservative extraction; Task 4 covers desktop lifecycle, loopback security, and local database location; Task 5 covers provisioning and offline behavior; Task 6 covers regression and packaged acceptance.
- Runtime status follows the existing location `backend/app/services/runtime_status.py`; no separate API status module is introduced.
- The existing Next client compiles `NEXT_PUBLIC_API_URL` into the bundle, so the packaged prototype deliberately uses fixed loopback ports 3000 and 8000 and reports conflicts instead of selecting a dynamic API port.
- The IndicConformer/NeMo integration is a feasibility-sensitive task on macOS. A successful package build alone does not count as ASR inference; only actual local checkpoint inference plus reference-audio results can establish support.
- Transcript source metadata is currently only in ASR diagnostics; Task 2 adds optional persisted `language_code` so later extraction can receive it. This requires a backwards-compatible SQLite migration and an existing-database test.
- Real audio/reference transcripts are not currently part of the approved spec inputs; absent fixtures leave language quality explicitly unvalidated.
