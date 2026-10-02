import numpy as np
import pytest

from app.providers.audio import audio_metrics, decode_audio_payload, save_debug_wav
from app.providers.speech import AudioChunk
from app.providers.vad import SileroVoiceActivityDetector


def test_browser_float32_audio_is_decoded_mono_and_resampled() -> None:
    stereo = np.tile(np.array([[1.0, -1.0]], dtype="<f4"), (480, 1))

    decoded = decode_audio_payload(
        stereo.tobytes(),
        encoding="pcm_f32le",
        sample_rate=48_000,
        channels=2,
        target_sample_rate=16_000,
    )

    assert decoded.waveform.dtype == np.float32
    assert decoded.waveform.ndim == 1
    assert decoded.sample_rate == 16_000
    assert decoded.waveform.size == 160


def test_silero_receives_tensor_not_raw_browser_bytes() -> None:
    torch = pytest.importorskip("torch")
    received: dict[str, object] = {}

    def fake_silero(audio, sample_rate):
        received["audio"] = audio
        received["sample_rate"] = sample_rate
        return torch.tensor(0.9)

    payload = np.ones(512, dtype="<f4").tobytes()
    chunk = AudioChunk(
        audio=payload,
        sample_rate=16_000,
        timestamp_ms=0,
        encoding="pcm_f32le",
        channels=1,
    )

    result = SileroVoiceActivityDetector(model=fake_silero).detect(chunk)

    assert result.has_speech is True
    assert isinstance(received["audio"], torch.Tensor)
    assert received["audio"].dtype == torch.float32
    assert tuple(received["audio"].shape) == (512,)
    assert received["sample_rate"] == 16_000


def test_silero_reports_speech_frame_coverage() -> None:
    torch = pytest.importorskip("torch")

    def fake_silero(audio, sample_rate):
        return torch.tensor(0.9 if float(audio.abs().mean()) > 0.1 else 0.0)

    waveform = np.concatenate([np.ones(512, dtype=np.float32), np.zeros(512, dtype=np.float32)])
    result = SileroVoiceActivityDetector(model=fake_silero).detect(
        AudioChunk(audio=b"", sample_rate=16_000, timestamp_ms=0, waveform=waveform)
    )

    assert result.frame_count == 2
    assert result.speech_frame_count == 1
    assert result.speech_duration_ms == pytest.approx(32.0)


def test_audio_metrics_report_duration_rms_peak_clipping_and_silence() -> None:
    metrics = audio_metrics(np.array([0.0, 0.5, -1.0, 0.0], dtype=np.float32), sample_rate=2)

    assert metrics["duration_ms"] == 2_000
    assert metrics["rms"] == pytest.approx(0.559017, rel=1e-5)
    assert metrics["peak"] == pytest.approx(1.0)
    assert metrics["clipping_percent"] == pytest.approx(25.0)
    assert metrics["silence_percent"] == pytest.approx(50.0)


def test_debug_wav_is_playable_and_contains_decoded_browser_audio(tmp_path) -> None:
    sf = pytest.importorskip("soundfile")
    payload = np.array([0.0, 0.25, -0.25, 0.0], dtype="<f4").tobytes()
    output = tmp_path / "received.wav"

    save_debug_wav(output, payload, encoding="pcm_f32le", sample_rate=16_000, channels=1)

    samples, rate = sf.read(output, dtype="float32")
    assert rate == 16_000
    assert samples.shape == (4,)
    assert samples.tolist() == pytest.approx([0.0, 0.25, -0.25, 0.0])
