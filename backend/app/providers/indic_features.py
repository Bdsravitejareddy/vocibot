"""Log-mel features exactly as IndicConformer was trained with (NeMo's
AudioToMelSpectrogramPreprocessor), in numpy so the app needs no NeMo.

16 kHz audio -> pre-emphasis 0.97 -> 25 ms Hann window every 10 ms
(512-point FFT, centred, reflect-padded) -> power -> 80 mel filters
-> log(x + 2^-24) -> per-filter mean/std normalisation.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

N_FFT = 512
HOP = 160
WIN = 400
PREEMPHASIS = 0.97
LOG_GUARD = 2.0 ** -24
STD_GUARD = 1e-5


class FeatureExtractor:
    def __init__(self, constants: Path) -> None:
        data = np.load(constants)
        window = data["window"].astype(np.float64)
        # torch.stft centres a shorter window inside the FFT frame.
        left = (N_FFT - len(window)) // 2
        self.window = np.zeros(N_FFT)
        self.window[left:left + len(window)] = window
        self.filterbank = data["filterbank"].astype(np.float64)  # 80 x 257

    def __call__(self, audio: np.ndarray) -> np.ndarray:
        """80 x frames float32 features for one utterance."""

        x = np.asarray(audio, dtype=np.float64)
        x = np.concatenate((x[:1], x[1:] - PREEMPHASIS * x[:-1]))
        pad = N_FFT // 2
        x = np.pad(x, (pad, pad), mode="reflect")
        frames = 1 + (len(x) - N_FFT) // HOP
        strides = (x.strides[0] * HOP, x.strides[0])
        windows = np.lib.stride_tricks.as_strided(x, shape=(frames, N_FFT), strides=strides) * self.window
        power = np.abs(np.fft.rfft(windows, n=N_FFT, axis=1)) ** 2  # frames x 257
        mel = np.log(power @ self.filterbank.T + LOG_GUARD).T  # 80 x frames
        valid = len(audio) // HOP + 1
        mel = mel[:, :valid]
        mean = mel.mean(axis=1, keepdims=True)
        std = mel.std(axis=1, ddof=1, keepdims=True) + STD_GUARD if valid > 1 else np.ones_like(mean)
        return ((mel - mean) / std).astype(np.float32)
