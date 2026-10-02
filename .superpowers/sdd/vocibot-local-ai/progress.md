# SDD ledger — plan: docs/superpowers/plans/2026-09-26-vocibot-local-ai-plan.md

Ruling: The existing repository is already an isolated worktree on feat/vocibot-mvp; implementation continues there.

Pre-flight: Tasks 1→2 share provider settings and adapter contracts; Tasks 2→3 share LocalAudioPipeline and diagnostics; Tasks 3→4 share the WebSocket protocol; Tasks 1→5 share explicit local-mode errors and the mock EMR boundary; no unresolved interface conflicts found.

Task 1: complete — `.venv/bin/pytest -q` → 17 passed.
Task 2: complete — `.venv/bin/pytest -q` → 22 passed.
Task 3: complete — `.venv/bin/pytest -q` → 26 passed.
Task 4: complete — `npm test`, `npm run typecheck`, `npm run lint`, and deterministic E2E → 7 frontend tests, typecheck/lint passed, 1 browser test passed.
Task 5: complete — local smoke on Apple Silicon M4 Pro/48 GB with faster-whisper small, Silero, and Ollama llama3.1:8b completed VAD/STT/extraction/mock EMR/approval/reopen; WhisperX/pyannote explicitly disabled due large checkpoint download and recorded in report.
Task 6: complete — `npm test` → 7 passed; `.venv/bin/pytest -q` → 28 passed; `npm run typecheck` passed; `npm run lint` passed; `npm run build` passed; `npm run test:e2e` → 1 passed; `git diff --check` clean.
