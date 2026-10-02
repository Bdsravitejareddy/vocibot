# PyInstaller build of the VociBot Enterprise server (Windows first; also runs
# on macOS/Linux for testing). Usage, from the repository root after
# `VOCIBOT_STATIC_EXPORT=1 NEXT_PUBLIC_API_URL= npx next build`:
#     python -m PyInstaller --noconfirm --distpath dist/enterprise backend/VociBotEnterprise.spec
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

backend_dir = Path(SPECPATH)
repo = backend_dir.parent
web = repo / "out"
if not (web / "index.html").is_file():
    raise SystemExit("Export the web app first: VOCIBOT_STATIC_EXPORT=1 NEXT_PUBLIC_API_URL= npx next build")

hidden = ["app.main"] + collect_submodules("app") + collect_submodules("faster_whisper") + collect_submodules("uvicorn") + ["onnxruntime", "cryptography"]
datas = collect_data_files("faster_whisper") + [(str(web), "web"), (str(repo / "deploy" / "profiles"), "profiles")]

a = Analysis(
    [str(backend_dir / "vocibot_server.py")],
    pathex=[str(backend_dir)],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Not needed by the enterprise server: GPU/MLX speech (Mac), PyTorch-based
    # research add-ons, and heavy scientific stacks they would pull in.
    excludes=["mlx", "mlx_whisper", "torch", "torchaudio", "torchvision", "silero_vad", "whisperx", "pyannote", "nemo", "tensorflow", "sklearn", "pandas", "matplotlib", "numba", "llvmlite", "transformers", "pytest", "IPython"],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="vocibot-server", console=True, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="vocibot-server")
