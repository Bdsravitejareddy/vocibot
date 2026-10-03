from pathlib import Path
import importlib.util
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

backend_dir = Path(SPECPATH)
hidden = ["app.main", "app.providers.indic_conformer", "app.providers.indic_features"] + collect_submodules("onnxruntime") + collect_submodules("faster_whisper") + collect_submodules("silero_vad")
datas = collect_data_files("silero_vad") + collect_data_files("faster_whisper")
binaries = []
if importlib.util.find_spec("mlx_whisper") is not None:
    # Whisper on the Apple Silicon GPU.  MLX loads its Metal kernels
    # (mlx.metallib) from the directory of whichever libmlx.dylib is loaded, so
    # ship the kernels beside both possible copies of the library.
    mlx_lib = Path(importlib.util.find_spec("mlx").submodule_search_locations[0]) / "lib"
    hidden += collect_submodules("mlx") + collect_submodules("mlx_whisper") + collect_submodules("tiktoken_ext")
    datas += collect_data_files("mlx_whisper") + [(str(mlx_lib / "mlx.metallib"), "mlx/lib"), (str(mlx_lib / "mlx.metallib"), ".")]
    binaries += [(str(path), "mlx/lib") for path in mlx_lib.glob("*.dylib")]
a = Analysis(
    [str(backend_dir / "desktop_server.py")],
    pathex=[str(backend_dir)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["whisperx", "pyannote", "nemo", "pytest", "tensorflow", "sklearn", "pandas", "matplotlib"],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="vocibot-api", console=True, upx=False, clean=True)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="vocibot-api")
