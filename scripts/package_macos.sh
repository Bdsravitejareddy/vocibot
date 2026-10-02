#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "The desktop prototype currently packages for macOS only." >&2
  exit 2
fi
if ! .venv/bin/python -m PyInstaller --version >/dev/null 2>&1; then
  echo "Install the backend desktop extra (PyInstaller) before packaging." >&2
  exit 2
fi

rm -rf .next
npm run build
rm -rf dist/runtime/web
mkdir -p dist/runtime/web dist/runtime/backend
if [[ -f dist/runtime/backend/vocibot-api ]]; then rm dist/runtime/backend/vocibot-api; fi
cp -R .next/standalone/. dist/runtime/web/
mkdir -p dist/runtime/web/.next
cp -R .next/static dist/runtime/web/.next/static
if [[ -d public ]]; then cp -R public dist/runtime/web/public; fi
.venv/bin/python -m PyInstaller --noconfirm --distpath dist/runtime/backend backend/VociBot.spec
if [[ ! -f dist/runtime/backend/vocibot-api/_internal/silero_vad/data/silero_vad.jit ]]; then
  echo "Packaged backend is missing the required Silero VAD model." >&2
  exit 2
fi
if [[ ! -f dist/runtime/backend/vocibot-api/_internal/faster_whisper/assets/silero_vad_v6.onnx ]]; then
  echo "Packaged backend is missing the required Faster-Whisper VAD model." >&2
  exit 2
fi
if .venv/bin/python -c "import mlx_whisper" >/dev/null 2>&1 && [[ ! -f dist/runtime/backend/vocibot-api/_internal/mlx/lib/mlx.metallib ]]; then
  echo "Packaged backend is missing the MLX Metal kernels." >&2
  exit 2
fi
npx electron-builder --mac dir
