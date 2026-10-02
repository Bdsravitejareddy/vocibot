# VociBot Enterprise — status and next steps

Hand-off notes for continuing the enterprise build. To resume with Claude Code,
open `~/vocibot-enterprise` (branch `enterprise`) and say:

> Read docs/ENTERPRISE_NEXT_STEPS.md and continue from "Remaining work", step 1.

## Goal (decisions already made by the owner)

- Multiple clinicians share one machine and one copy of the models; each signs
  in with username/password and sees only their own patients and consultations.
- Accounts are created by an administrator (first run creates the admin); no
  self sign-up.
- Target hardware: **Windows PC, 16 GB DDR4**, NVIDIA GPU optional ("not sure"
  → support both). Also report an **8 GB** comparison.
- Two named versions from one codebase:
  - **`vocibotenterpriseclinicserver`**: one Windows PC serves every doctor's
    browser over HTTPS on the clinic network.
  - **`vocibotenterpriseonecomputersamecell`**: one shared Windows PC (Electron
    app); doctors sign in and out in turn.
- The original single-user Mac version is preserved (see below) and must not
  be changed.

## Where things are

| What | Where |
|---|---|
| Original Mac version (frozen) | git branch + tag `vocibotoriginalmacversion` (= `main` at `43c4cd1`); built app archived at `~/vocibot-releases/vocibotoriginalmacversion/VociBot.app` |
| Enterprise code | branch `enterprise`, worktree `~/vocibot-enterprise` |
| `main` | untouched by enterprise work (still the original app) |
| GitHub | `Bdsravitejareddy/vocibot` (private) |

## Done (committed on `enterprise`)

1. **Accounts and privacy** — `a6ced83`, `8c687d2`
   - scrypt password hashes; lockout after 5 failures (15 min); 30-min idle /
     12-h absolute sessions; HttpOnly SameSite=Lax cookie, only its SHA-256
     stored; Secure flag under HTTPS.
   - First-run setup (once) claims pre-existing records for the admin.
   - Admin page: add user with temporary password (forced change at first
     sign-in), reset password, change role, deactivate (signs out everywhere),
     security log. Admins see only their own clinical records.
   - Every consultation endpoint and the audio websocket check ownership
     (other users' records → 404). Websocket checks Origin (allowed list or
     same origin). Patients are unique per clinician.
   - Login/setup/account forms POST and stay disabled until hydrated, so a
     submit can never put credentials in the URL.
   - History is paginated summaries with search (patient ID, name, session ID).
2. **Fixed RAM under load** — `f63d6e4`
   - `backend/app/services/inference.py`: one shared pipeline (one copy of each
     model) and one priority queue: live previews > final transcripts > batch.
   - `MAX_LIVE_SESSIONS` live slots; extra sessions are recorded and fully
     transcribed after Stop.
   - `backend/app/services/processing.py`: Stop returns immediately; final
     transcript (from the saved recording, ~30 s pieces cut at pauses) and note
     are background jobs, one at a time, persisted in the DB and resumed after a
     restart. Re-analyse / re-transcribe are queued too; approval waits.
   - UI shows "Finalising the transcript… / Writing the clinical note… (N ahead)".
3. **CPU / low-RAM optimisation** — `e77fa50`
   - Compact note prompt (s-numbered lines) and per-consultation context size
     (test13: 12.1k → 5.4k chars, ctx 16k → 4k); `OLLAMA_NUM_GPU`,
     `OLLAMA_NUM_THREAD`, `OLLAMA_KEEP_ALIVE`, `OLLAMA_MAX_CONTEXT`.
   - `FINAL_WHISPER_MODEL`: small for live, large-v3-turbo for the final pass.
   - Evidence check: negation is clause-scoped ("no chest pain, but I feel very
     tired" keeps "tired").
   - Benchmarks: `backend/benchmarks/clinical_note_cases.json` (6 cases, 70
     expected facts, must-not checks) + `note_quality.py`.
   - Profiles: `deploy/profiles/{windows-16gb,windows-8gb,mac-apple-silicon}.env`.
4. **Packaging (this commit, not yet run on Windows)**
   - Voice activity detection on ONNX (faster-whisper's Silero) by default:
     no PyTorch (≈ −700 MB install, −300 MB RAM) and 0/18 vs 14/18 false
     triggers on noise. `VAD_ENGINE=torch` keeps the old path.
   - Static web export (`VOCIBOT_STATIC_EXPORT=1`) served by the backend
     (`WEB_ROOT`): one process, one port, same origin. Detail page moved to
     `/history/view?id=…`.
   - `backend/vocibot_server.py`: `serve | provision | reset-admin-password`,
     `--edition clinic-server|one-computer`, data dir per edition
     (`%PROGRAMDATA%\VociBot\clinic-server`, `%LOCALAPPDATA%\VociBot`).
   - `backend/app/certificates.py`: local CA + server cert (397 days, auto
     renew, SANs = hostname/.local/LAN IPs); CA served at `/ca.crt`.
   - `backend/VociBotEnterprise.spec`: PyInstaller server bundle (254 MB on
     macOS, no torch/mlx). Verified on macOS: frozen one-computer edition ran
     a full CPU session (stop ack 0.4 s, transcript+note 29 s).
   - One-computer Electron shell: `desktop/enterprise/{main,server-runtime}.cjs`,
     `electron-builder-enterprise.yml` (Windows NSIS). Verified on macOS (dir
     build): launches the server, quits it on exit.
   - Clinic server scripts: `deploy/clinic-server/{install.ps1,uninstall.ps1,README-clinic-server.md}`
     (scheduled tasks as SYSTEM for VociBot and Ollama, ProgramData ACLs,
     firewall on Private/Domain only, `OLLAMA_MODELS` in ProgramData).
   - Benchmark tooling for Windows: `backend/benchmarks/make_tts_audio.ps1`
     (Windows voices speak the cases), `backend/benchmarks/server_e2e.py`
     (real-time sessions through the authenticated websocket; delay, accuracy,
     time to note, note quality, peak memory; `--concurrency N`).

Tests at this commit: backend 134 passed (2 skipped: need a packaged build),
frontend + desktop unit 16, Playwright 17 (last full run before packaging
changes; re-run), typecheck and lint clean.

## Measured so far (MacBook Pro M4 Pro, CPU-only, 4 threads — a proxy, not DDR4)

| | 16 GB profile | 8 GB profile |
|---|---|---|
| Speech models | small (live) + large-v3-turbo (final) | small |
| Note model | llama3.1:8b | qwen2.5:3b |
| Live accuracy (excl. names) / median delay | 97.8% / 1.4 s | 96.8% / 1.4 s |
| Final transcript accuracy (excl. names) | 99.4% | 99.4% |
| Stop → transcript / note (2-min session) | 32 s / 75 s | 9 s / 29 s |
| Note facts captured (70) / mistakes | 83% / 0 | 69% / 2 |
| Peak memory (server + note model) | 3.0 + 5.3 GB | 1.4 + 2.3 GB |

- 3 doctors at once (16 GB profile): memory flat (3.3 + 5.3 GB); live delay
  ~4 s; notes delivered sequentially at 66/119/178 s → `MAX_LIVE_SESSIONS=2`.
- Other LLMs tried: qwen2.5:7b 63% (1 mistake), llama3.2:3b 4% (ignores format).
- CPU Whisper (final pass, excl. names): small 97.2% @15× RT; medium 99.0% @4.4×;
  large-v3-turbo 99.8% @4.6× (2.3 GB).
- Expectation for real DDR4 (~40–50 GB/s): note model ~3–4× slower than above
  (≈1.5–2 min per note with llama3.1:8b on CPU). **Must be confirmed on Windows.**

## Remaining work

1. **Validate `server_e2e.py` locally** (was in progress). Generate case audio
   with macOS voices, serve the 16 GB profile on CPU, run:
   ```bash
   # audio (macOS stand-in for make_tts_audio.ps1)
   .venv/bin/python -c "import json,subprocess,os;cs=json.load(open('backend/benchmarks/clinical_note_cases.json'));[ (os.makedirs(f'/tmp/vb-tts/{c[\"id\"]}',exist_ok=True), [subprocess.run(['say','-v','Daniel' if i%2==0 else 'Samantha','--data-format=LEI16@16000','-o',f'/tmp/vb-tts/{c[\"id\"]}/{i:03d}.wav',l],check=True) for i,l in enumerate(c['lines'])]) for c in cs[:2]]"
   # server (CPU 16 GB profile) on :8010, then:
   PYTHONPATH=backend:backend/benchmarks .venv/bin/python backend/benchmarks/server_e2e.py --api http://127.0.0.1:8010 --audio /tmp/vb-tts --label mac-cpu
   ```
   Fix whatever breaks (it has never run yet).
2. **Windows CI** — create `.github/workflows/enterprise-windows.yml`
   (runs on push to `enterprise` and `workflow_dispatch` with a `benchmark` input):
   - Job `build-test` (`windows-latest`, 4 vCPU / 16 GB): Python 3.12, Node 22;
     `pip install -e "backend[test,local,server,desktop]" psutil websockets`;
     `npm ci`; pytest; `npx tsx --test tests/*.test.ts tests/desktop/*.test.ts`;
     typecheck; lint; `VOCIBOT_STATIC_EXPORT=1 NEXT_PUBLIC_API_URL= npx next build`;
     PyInstaller `backend/VociBotEnterprise.spec` → `dist/enterprise/vocibot-server`;
     smoke-test the exe (clinic-server over HTTPS with `--cacert`, and
     one-computer on 8765, `AI_MODE=demo`: /health, UI, setup, login,
     consultation); `npx electron-builder --config electron-builder-enterprise.yml --win nsis`;
     zip the clinic package (`vocibot-server/` + `deploy/clinic-server/*` +
     `deploy/profiles/` as `profiles/`) as
     `vocibotenterpriseclinicserver-<version>-win-x64.zip`; upload both artifacts.
   - Job `benchmark` (needs build-test; on dispatch): download artifact; install
     Ollama from `ollama-windows-amd64.zip`, start `ollama serve`; `provision`
     with each profile; `make_tts_audio.ps1`; run `server_e2e.py` for
     windows-16gb (single + `--concurrency 3`) and windows-8gb; write the
     summaries to `$GITHUB_STEP_SUMMARY` and upload JSON. Record CPU model and
     memory type (script reports `SMBIOSMemoryType`: 26 = DDR4, 34 = DDR5).
   - Known Windows fixes to expect: `backend/tests/conftest.py` builds
     `sqlite:///` from a temp path — use `Path(...).as_posix()`; `chmod` is a
     no-op (ACLs are set by install.ps1); `test_packaged_runtime.py` is
     mac-specific (skip on Windows); PowerShell needs `$env:VAR` syntax.
   - Windows minutes count double on private repos (~150–200 billed minutes per
     full run) — tell the owner before running the benchmark job repeatedly.
3. **Write `docs/ENTERPRISE.md`**: architecture (shared engine, job queue,
   editions), profiles, capacity guidance, measured Mac proxy + Windows
   results, security model, operations (backup, cert install, reset admin).
4. **Release**: once Windows CI is green, tag `vocibotenterpriseclinicserver`
   and `vocibotenterpriseonecomputersamecell`, attach the artifacts to a GitHub
   Release. Ask the owner before merging `enterprise` into `main` (main is the
   original Mac app).
5. **Open items to raise with the owner**
   - Windows installers are unsigned (SmartScreen warning) — needs a code-signing certificate.
   - Audio and database are not encrypted by VociBot (rely on BitLocker/FileVault).
   - No retention period / automatic deletion policy yet.
   - The 8B note model can file non-clinical words into fields on non-clinical
     input (e.g. "Kubernetes" as a medication); doctors must review every note.
   - Live speaker separation (doctor vs patient) is not implemented.

## Developer environment notes

- `~/vocibot-enterprise/.venv` and `node_modules` are **symlinks** to the
  original checkout's (`~/vocibot`). That venv has the *original* backend
  installed in editable mode, so standalone scripts must use
  `PYTHONPATH=backend` (or `--app-dir backend` for uvicorn) to import the
  enterprise code. Pytest is unaffected (`pythonpath = [".", "tests"]`).
- Added to the shared venv during this work: `cryptography`, `psutil`
  (`pip install -e "backend[local,server]"` on a fresh machine).
- Models cached on this Mac: Whisper small/medium/large-v3-turbo (faster-whisper,
  `~/.cache/huggingface`), MLX large-v3-turbo; Ollama: llama3.1:8b, qwen2.5:7b,
  qwen2.5:3b, llama3.2:3b.
- Useful commands:
  ```bash
  .venv/bin/python -m pytest backend/tests -q
  npx tsx --test tests/*.test.ts tests/desktop/*.test.ts
  npx playwright test
  npx tsc --noEmit && npx eslint .
  VOCIBOT_STATIC_EXPORT=1 NEXT_PUBLIC_API_URL= npx next build      # -> out/
  .venv/bin/python -m PyInstaller --noconfirm --distpath dist/enterprise --workpath build backend/VociBotEnterprise.spec
  PYTHONPATH=backend .venv/bin/python backend/benchmarks/note_quality.py --model llama3.1:8b --cpu-only --threads 4
  cd backend && VOCIBOT_DATA_DIR=/tmp/vb AI_MODE=demo ../.venv/bin/python vocibot_server.py serve --edition clinic-server
  ```
