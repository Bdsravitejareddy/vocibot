# VociBot Local Smoke Test

Run on 2026-09-26 using the local `audio_health_check.wav` fixture available on this Mac.

## Hardware

- Apple Silicon: Apple M4 Pro, arm64
- RAM: 48 GB

## Models and execution

- Whisper: `small`, faster-whisper executed successfully.
- Ollama: `llama3.1:8b`, reachable and extraction executed successfully.
- Silero VAD: executed successfully.
- WhisperX: not executed; disabled by configuration because its configured Wav2Vec2 checkpoint attempted a 1.18 GB download.
- pyannote diarization: not executed; disabled by configuration. Speaker labels remained `UNKNOWN` for this run.

## Measurements

- VAD latency: approximately 424 ms.
- Transcription latency: approximately 2,229 ms.
- Ollama extraction latency: approximately 2,113 ms.

## Result

The real local path completed VAD → faster-whisper → Ollama extraction → evidence validation → mock EMR update → doctor review/edit → approval → SQLite persistence → reopen. The available fixture was not a full spoken English consultation; faster-whisper produced only `For`, so no unsupported clinical facts were promoted and the report records an omission for English clinical coverage.

The code-switched English/Indian-language consultation was not run because no suitable local recording or microphone capture was available in this environment. A real browser microphone run should be performed with `WHISPERX_ENABLED=true` and/or `DIARIZATION_ENABLED=true` when those checkpoints are intentionally installed.

Exact machine-readable output is in `2026-09-26-vocibot-local-smoke.json`.
