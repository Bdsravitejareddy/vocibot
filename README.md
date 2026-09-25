# VociBot

VociBot is a local-first clinical documentation assistant MVP. It captures a consultation transcript, extracts only evidence-grounded clinical facts, keeps a source-linked audit trail, and requires explicit doctor approval before saving the final record.

## Run locally

```bash
cd /Users/raviteja/vocibot
npm install
python3 -m venv .venv
.venv/bin/pip install -e 'backend[test]'
cp .env.example .env
```

Start the FastAPI backend:

```bash
.venv/bin/uvicorn app.main:app --app-dir backend --reload --port 8000
```

In another terminal, start the Next.js frontend:

```bash
npm run dev
```

Open http://127.0.0.1:3000 and choose **New consultation**. The default **Demo mode** streams the scripted fever consultation progressively without a microphone, local model, GPU, or internet connection.

## Provider architecture

Demo providers and local-model providers implement the same seams:

- `SpeechToTextProvider`: deterministic demo or configurable `FasterWhisperProvider`.
- `VoiceActivityDetector`: demo or optional Silero VAD.
- `DiarizationProvider`: demo or optional pyannote-compatible implementation.
- `WhisperXAligner`: optional local word-level alignment seam.
- `ClinicalExtractionProvider`: deterministic evidence-grounded extraction or configurable Ollama JSON extraction.

The MVP defaults to demo providers. To experiment locally, install the optional audio extras from `backend[test,local]`, set `STT_PROVIDER`, `OLLAMA_MODEL`, and the other provider configuration values, then add the concrete runtime wiring in the backend service. No paid/cloud AI provider is required.

## Safety behavior

AI updates are schema-validated and evidence-checked before persistence. Missing facts remain unset, ambiguous facts are not silently promoted to certainty, and assessment/plan fields require explicit doctor statements. Every AI update stores source transcript segment IDs. Doctor edits and approval are separate audit events.

This is a documentation assistant, not a diagnostic or prescribing system.

## Verification

```bash
npm run typecheck
npm run lint
npm test
.venv/bin/pytest
npm run build
npm run test:e2e
```

The Playwright config starts both local servers automatically for the demo acceptance flow.
