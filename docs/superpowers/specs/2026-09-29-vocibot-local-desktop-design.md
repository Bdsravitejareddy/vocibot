# VociBot Local Desktop Prototype Design

## Goal

Deliver a macOS-first desktop prototype of VociBot that captures consultation audio, performs speech transcription and conservative clinical-note extraction locally, and works without internet after installation and model provisioning. Keep the clinical workflow independent of any one healthcare SaaS or SAP form so a separately scoped connector can be added later.

## User intent and constraints

- The prototype is for local clinical conversation transcription and note drafting.
- Initial language evaluation set: Indian English, Telugu, Hindi, Marathi, and Gujarati. The design should permit expansion to all 22 scheduled Indian languages, without claiming that model coverage alone proves accuracy for all dialects, code-switching, or clinical vocabulary.
- Audio, transcripts, inference, and local persistence stay on the device. No cloud fallback.
- A clinician reviews and edits proposed notes before approval. The tool does not diagnose, prescribe, or submit to an external system.
- The immediate delivery target is a functional, locally installed macOS prototype. Public distribution, Windows packaging, and live SAP/healthcare SaaS connections are out of scope.
- Existing uncommitted changes in the repository are user work and must be preserved.

## Approaches considered

1. Keep the current local web app and add a one-click launcher. This is the smallest change, but offers weaker native packaging and lifecycle integration.
2. Replace the UI and inference stack with a native macOS app. This offers deep platform integration but duplicates substantial working product code.
3. Wrap the existing UI and FastAPI backend in a desktop shell with a managed local backend process. This reuses the current consultation workflow while providing an app-like launch and lifecycle. This is the recommended prototype path.

For ASR, a single faster-whisper model is simplest but does not establish Indian clinical accuracy. An Indic-only engine can target scheduled Indian languages but would narrow broad multilingual handling. The prototype will expose a common ASR provider interface and allow an Indic-focused provider and Whisper provider to be evaluated/routed by language. Provider selection must be based on supported models and recorded benchmarks, not assumed superiority. AI4Bharat IndicConformer advertises coverage for the 22 scheduled languages; faster-whisper provides multilingual Whisper inference. These are candidate engines, not performance guarantees.

## Architecture

- Keep the existing Next.js consultation UI and FastAPI local API. Package them in a macOS desktop shell that starts, health-checks, and stops the local backend; the shell must bind backend access to loopback only.
- Keep inference behind provider interfaces: audio preprocessing/VAD, ASR, optional local translation or language normalization, and local clinical extraction. Runtime/model selection is explicit and visible; provider failures are surfaced and never silently redirected to demo or cloud inference.
- Preserve original-language transcript text and script as the source of truth. If translation is used for extraction, retain it as a derived artifact and attach proposed note fields to evidence in the original transcript. Translation must not overwrite source transcript text.
- Continue the current conservative evidence validator and clinician review/approval boundary. Unsupported facts remain absent or marked for review; no diagnosis or prescription generation.
- Persist consultation records locally in the existing local database. Raw audio is not persisted by default. Any test-fixture import is explicit and remains local.
- Define a versioned, platform-neutral approved-note payload as the future integration boundary. No external login, form automation, API submission, or outbound network call is included in this prototype.
- Models and dependencies are provisioned before offline operation. The app reports missing assets and setup status; it does not attempt hidden downloads while offline.

## Desktop lifecycle and offline behavior

The desktop app launches the frontend and local API, waits for a health check, displays a clear setup/runtime error on failure, and shuts down only the process it started. It must not expose the backend to the LAN. First-run setup can download/install approved model assets when internet is available; after provisioning, a smoke test must demonstrate inference with network access disabled. Updates and model downloads are separate from consultation use.

## Language behavior and accuracy claims

- Provide explicit language selection and automatic detection as a convenience, not as ground truth. Permit correction before/during transcription.
- Preserve code-switching when supported by the selected engine; report uncertainty and low-confidence spans rather than silently treating them as reliable.
- Initial evaluation covers Indian English, Telugu, Hindi, Marathi, and Gujarati. The ASR provider interface and model manifest should make adding remaining scheduled languages possible.
- Publish per-language evaluation results (at minimum WER/CER where suitable, latency, and failure counts) from versioned reference audio. Do not claim “all languages work accurately” until representative recordings are evaluated. Medical use requires clinician review; the prototype is not a validated medical device.
- Regional-language note extraction is a separate measured capability from transcription. Any local translation/extraction path must retain provenance and fail closed to an editable transcript when its model is missing or uncertain.

## Security and privacy

All network listeners are loopback-only; no telemetry or cloud AI calls are added. Logs must not contain full patient transcripts by default. App data and model locations are documented, and deleting a consultation remains explicit user-controlled behavior. External form connectors require a later design covering authentication, patient identity matching, permissions, audit trail, and target-specific validation.

## Verification and acceptance

- Existing backend, frontend, typecheck, lint, build, and browser tests continue to pass.
- Desktop smoke test covers app launch, backend readiness, microphone permission, recording, pause/resume/stop, transcript review, extraction/evidence validation, clinician edit/approval, local persistence, and clean shutdown.
- Offline test disables network after provisioning and completes a short local transcription and extraction without network attempts.
- ASR tests use provider contract fakes plus versioned real audio/reference transcripts for each initial language. Report measured quality and runtime; do not substitute demo output for a local model test.
- Verify the built macOS artifact starts on the development machine. Signing/notarization and release distribution are separate unless explicitly added later.

## Scope decomposition

1. Local macOS desktop lifecycle and packaging around the existing local workflow.
2. Multilingual ASR provider integration, model provisioning, and measured initial-language acceptance; retain a clear extension path to all 22 scheduled languages.
3. Local multilingual note-extraction validation and benchmarks; improve only where representative data shows a gap.
4. Future, separately designed healthcare/SAP connector(s) consuming only clinician-approved note payloads.

The first implementation plan should identify dependencies between these stages and deliver a functional desktop prototype without representing unmeasured language performance as complete.
