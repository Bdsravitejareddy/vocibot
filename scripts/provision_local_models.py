#!/usr/bin/env python3
"""Explicitly provision model artifacts while online; inference itself is offline."""
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", required=True, choices=("mlx_whisper", "whisper", "indic_conformer", "ollama"))
    parser.add_argument("--model", required=True, help="Whisper size, Hugging Face repository ID, or Ollama tag")
    parser.add_argument("--language", help="Optional language code for a monolingual IndicConformer model")
    args = parser.parse_args()

    if args.engine == "ollama":
        subprocess.run(["ollama", "pull", args.model], check=True)
        print(f"Ollama model provisioned: {args.model}")
        return 0

    if args.engine == "mlx_whisper":
        from huggingface_hub import snapshot_download

        local_path = Path(snapshot_download(repo_id=args.model)).resolve()
        if not any(local_path.glob("*.safetensors")) and not any(local_path.glob("*.npz")):
            raise SystemExit(f"Downloaded MLX Whisper model is incomplete: {local_path}")
        print(f"MLX Whisper model provisioned: {args.model} ({local_path})")
        return 0

    if args.engine == "whisper":
        from faster_whisper.utils import download_model

        local_path = Path(download_model(args.model)).resolve()
        if not (local_path / "model.bin").is_file():
            raise SystemExit(f"Downloaded Whisper model is incomplete: {local_path}")
        print(f"Set WHISPER_MODEL={local_path} for offline inference")
        return 0

    if args.engine == "indic_conformer":
        raise SystemExit("IndicConformer models are exported once with scripts/export_indicconformer.py (see its instructions).")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
