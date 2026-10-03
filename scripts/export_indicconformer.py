"""Export AI4Bharat IndicConformer languages for VociBot (ONNX, no NeMo at runtime).

Needs AI4Bharat's NeMo fork in a separate Python 3.11 environment, only for
this one-off export (it does not install on the app's Python, and its
`triton` dependency is Linux-only):

    uv venv -p 3.11 /tmp/nemo-ai4b
    git clone -b nemo-v2 https://github.com/AI4Bharat/NeMo.git /tmp/ai4b-nemo
    cd /tmp/ai4b-nemo && grep -hv -iE "^#|triton|nvidia|apex|megatron" requirements/requirements.txt \\
        requirements/requirements_asr.txt requirements/requirements_common.txt > /tmp/reqs.txt
    VIRTUAL_ENV=/tmp/nemo-ai4b uv pip install -r /tmp/reqs.txt "numpy<2" "torch==2.4.1" "torchaudio==2.4.1" \\
        "pytorch-lightning==2.2.5" "lightning==2.2.5" "transformers==4.40.2" "huggingface_hub==0.23.2" \\
        "hydra-core==1.3.2" "omegaconf==2.3.0" torchmetrics webdataset wandb "setuptools<70" "pyarrow<15" "datasets==2.19.2"
    VIRTUAL_ENV=/tmp/nemo-ai4b uv pip install --no-deps -e /tmp/ai4b-nemo

Checkpoints (MIT licence, public):
    https://objectstore.e2enetworks.net/indicconformer/models/indicconformer_stt_<lang>_hybrid_rnnt_large.nemo

    /tmp/nemo-ai4b/bin/python scripts/export_indicconformer.py --checkpoints DIR --out \\
        "~/Library/Application Support/vocibot/models/indicconformer" te hi

Writes <out>/<lang>/model.onnx (features -> per-frame log-probs over the
language's 256 tokens + blank, from the CTC head), <out>/<lang>/vocab.json
and <out>/features.npz (window and mel filterbank for app/providers/indic_features.py).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("languages", nargs="+")
    parser.add_argument("--checkpoints", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    logging.disable(logging.WARNING)
    import numpy as np
    import torch
    import nemo.collections.asr as nemo_asr

    out = args.out.expanduser()
    out.mkdir(parents=True, exist_ok=True)
    for code in args.languages:
        model = nemo_asr.models.ASRModel.restore_from(str(args.checkpoints.expanduser() / f"indicconformer_stt_{code}_hybrid_rnnt_large.nemo"), map_location="cpu")
        model.eval()
        featurizer = model.preprocessor.featurizer
        np.savez(out / "features.npz", window=featurizer.window.numpy().astype(np.float32), filterbank=featurizer.fb[0].numpy().astype(np.float32))
        mask = model.ctc_decoder.language_masks[code]
        index = torch.tensor([i for i, keep in enumerate(mask) if keep])

        class Graph(torch.nn.Module):
            def __init__(self) -> None:
                super().__init__()
                self.encoder, self.ctc = model.encoder, model.ctc_decoder.decoder_layers
                self.register_buffer("index", index)

            def forward(self, features, length):
                encoded, encoded_length = self.encoder(audio_signal=features, length=length)
                logits = torch.index_select(self.ctc(encoded).transpose(1, 2), 2, self.index)
                return torch.log_softmax(logits, dim=-1), encoded_length

        target = out / code
        target.mkdir(exist_ok=True)
        with torch.inference_mode():
            torch.onnx.export(Graph().eval(), (torch.randn(1, 80, 801), torch.tensor([801])), str(target / "model.onnx"), input_names=["features", "length"], output_names=["logprobs", "frames"],
                              dynamic_axes={"features": {0: "batch", 2: "time"}, "length": {0: "batch"}, "logprobs": {0: "batch", 1: "frames_out"}, "frames": {0: "batch"}}, opset_version=17)
        tokenizer = model.tokenizer.tokenizers_dict[code]
        vocab = [tokenizer.ids_to_tokens([i])[0] for i in range(len(index) - 1)]
        (target / "vocab.json").write_text(json.dumps({"language": code, "vocab": vocab, "blank": len(vocab), "frame_seconds": 0.01 * model.cfg.encoder.subsampling_factor, "source": f"indicconformer_stt_{code}_hybrid_rnnt_large"}, ensure_ascii=False), encoding="utf-8")
        print(f"{code}: {os.path.getsize(target / 'model.onnx') // 2**20} MB -> {target}")


if __name__ == "__main__":
    main()
