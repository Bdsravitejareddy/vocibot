from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

backend_dir = Path(SPECPATH)
hidden = ["app.main", "app.providers.indic_conformer"] + collect_submodules("faster_whisper") + collect_submodules("silero_vad")
datas = collect_data_files("silero_vad") + collect_data_files("faster_whisper")
a = Analysis(
    [str(backend_dir / "desktop_server.py")],
    pathex=[str(backend_dir)],
    binaries=[],
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
