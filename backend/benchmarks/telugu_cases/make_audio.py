"""Telugu test consultations spoken with macOS voices (Rishi:
Indian English doctor, Geeta: Telugu patient, some English words as
patients say them), 0.35 s between turns like a quick real conversation. Reference: the
line texts (English words in English, Hindi in Devanagari)."""
import json, subprocess, sys, tempfile
from pathlib import Path
import numpy as np, soundfile as sf
HERE = Path(__file__).parent
for case in json.loads((HERE / "cases.json").read_text()):
    out = HERE / f"{case['id']}.wav"
    if out.exists() and "--force" not in sys.argv:
        continue
    pieces = []
    with tempfile.TemporaryDirectory() as tmp:
        for index, (voice, text) in enumerate(case["lines"]):
            aiff = f"{tmp}/{index}.aiff"; wav = f"{tmp}/{index}.wav"
            subprocess.run(["say", "-v", voice, "-o", aiff, text], check=True)
            subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@16000", "-c", "1", aiff, wav], check=True)
            audio, _ = sf.read(wav, dtype="float32")
            pieces += [audio, np.zeros(5600, dtype=np.float32)]
    sf.write(out, np.concatenate(pieces), 16000)
    print(out.name, round(len(np.concatenate(pieces)) / 16000, 1), "s")
