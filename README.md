# VociBot

VociBot is a local-first clinical documentation assistant MVP. It captures a consultation transcript, extracts only evidence-grounded clinical facts, keeps a source-linked audit trail, and requires explicit doctor approval before saving the final record.

## Run locally (offline-capable)

```bash
cd /Users/raviteja/vocibot
npm install
python3 -m venv .venv
.venv/bin/pip install -e 'backend[test,local,desktop]'
cp .env.example .env
```

Install the front-end and Python dependencies while online, then explicitly provision the desired local models. Model setup is separate from running consultations so the app cannot silently fetch weights during offline use:

```bash
.venv/bin/python scripts/provision_local_models.py --engine mlx_whisper --model mlx-community/whisper-large-v3-turbo
.venv/bin/python scripts/provision_local_models.py --engine whisper --model small
ollama pull llama3.1:8b
```

On Apple Silicon, speech recognition runs Whisper large-v3-turbo on the GPU through MLX (`STT_PROVIDER=auto`, the default). Elsewhere, or with `STT_PROVIDER=whisper`, it falls back to faster-whisper on the CPU. Live text comes from re-transcribing the unsettled audio (at most `ASR_LIVE_MAX_BUFFER_SECONDS`) every `ASR_LIVE_STEP_SECONDS`; when Stop is pressed, one authoritative pass over the full recording replaces the live preview.

For Indian-language speech, the multilingual Whisper model can be selected using the conversation-language selector (English, Telugu, Hindi, Marathi, or Gujarati). If using AI4Bharat IndicConformer, install its compatible NeMo environment and provision a `.nemo` model explicitly:

```bash
.venv/bin/python scripts/provision_local_models.py --engine indic_conformer --model ai4bharat/indicconformer_stt_te_hybrid_ctc_rnnt_large --language te
```

Actual recognition quality depends on model, accent, recording, and hardware. It has not been validated per language against reference recordings in this workspace; clinician review remains required.

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

Demo mode uses deterministic scripted providers. Local mode uses configured on-device models, reports missing model/runtime states, and does not fall back to demo or cloud. It also runs offline after model provisioning.

## Run the real local AI pipeline

Install the local adapters and make sure Ollama is running with a local development model:

```bash
cd /Users/raviteja/vocibot
.venv/bin/pip install -e 'backend[local]'
ollama serve
ollama pull llama3.1:8b
```

For a real browser microphone consultation, use two terminals:

```bash
AI_MODE=local .venv/bin/uvicorn app.main:app --app-dir backend --reload --port 8000
```

```bash
NEXT_PUBLIC_AI_MODE=local NEXT_PUBLIC_API_URL=http://127.0.0.1:8000 npm run dev
```

Open http://127.0.0.1:3000, create a consultation, choose **Start local AI**, grant microphone access, then stop, edit, and approve the record. The browser streams local float32 audio over WebSocket; no raw audio is persisted.

Use `WHISPER_MODEL=small` for development on typical Apple Silicon hardware. Set `WHISPER_MODEL=large-v3` only when the machine has sufficient memory and patience for the larger download/runtime. WhisperX and pyannote are opt-in because their local checkpoints can be large: set `WHISPERX_ENABLED=true` and/or `DIARIZATION_ENABLED=true` when those models are available. `WHISPER_DEVICE`, `WHISPER_COMPUTE_TYPE`, `WHISPERX_MODEL`, `PYANNOTE_MODEL`, and `OLLAMA_MODEL` are configurable in `.env`.

The local smoke harness requires a 32-bit float PCM WAV fixture and records hardware, model status, stage execution, latency, unsupported facts, omissions, and exact failures:

```bash
AI_MODE=local .venv/bin/python scripts/local_smoke.py --audio /path/to/float32-consultation.wav --mode local
```

The generated report is written to `docs/superpowers/reports/2026-09-26-vocibot-local-smoke.json`. Missing local dependencies or models are reported explicitly; local mode never switches to demo mode.

## macOS desktop prototype

On macOS, after installing the desktop dependencies and provisioning models, build a managed `.app` bundle:

```bash
npm install
.venv/bin/pip install -e 'backend[local,desktop]'
npm run desktop:pack
```

The app starts only its own loopback API and standalone web child processes, stores SQLite data in the app's user-data directory, and disables Hugging Face downloads/telemetry during packaged inference. Open `dist/mac-arm64/VociBot.app`. Ollama is a separate local service; if it is unavailable, transcript review and manual note entry remain available without invented clinical facts.

For development, start the local API and frontend using the commands above, then run `npm run desktop:dev`.

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
