import numpy as np
import pytest

from app.services.voice_profile import best_match, build_profile, judge, voice_labels


def unit(vector) -> np.ndarray:
    vector = np.asarray(vector, dtype=float)
    return vector / np.linalg.norm(vector)


def doctor_samples(count: int = 6, seed: int = 1) -> list[np.ndarray]:
    rng = np.random.default_rng(seed)
    base = rng.normal(size=192)
    return [unit(base + rng.normal(scale=0.4, size=192)) for _ in range(count)]


def test_the_threshold_comes_from_the_doctors_own_samples() -> None:
    profile = build_profile(doctor_samples())
    assert 0.40 <= profile["threshold"] <= 0.55
    assert profile["outliers"] == []
    assert len(profile["embedding"]) == 192


def test_a_sample_in_another_voice_is_reported_for_re_recording() -> None:
    samples = doctor_samples()
    samples[2] = unit(np.random.default_rng(9).normal(size=192))
    assert build_profile(samples)["outliers"] == [2]


def test_at_least_five_sentences_are_needed() -> None:
    with pytest.raises(ValueError):
        build_profile(doctor_samples(4))


def test_judging_a_line() -> None:
    assert judge(0.60, 0.50) == "DOCTOR"
    assert judge(0.45, 0.50) is None  # unsure: the content decides
    assert judge(0.20, 0.50) == "PATIENT"


def test_the_closest_enrolled_doctor_is_used() -> None:
    first, second = unit([1.0, 0.0]), unit([0.0, 1.0])
    profiles = [{"embedding": list(first), "threshold": 0.5}, {"embedding": list(second), "threshold": 0.5}]
    assert best_match(unit([0.1, 0.9]), profiles)[0] > 0.9


class FakeEncoder:
    """Lines spoken at 0.5 amplitude are the doctor; at 0.1 someone else."""

    def speech_only(self, audio):
        return audio

    def embed(self, audio):
        return unit([1.0, 0.0]) if float(np.abs(audio).mean()) > 0.3 else unit([0.0, 1.0])


def test_each_line_is_judged_from_its_own_stretch_of_audio() -> None:
    audio = np.concatenate([np.full(16_000 * 3, 0.5), np.full(16_000 * 3, 0.1), np.full(8_000, 0.5)]).astype(np.float32)
    profiles = [{"embedding": [1.0, 0.0], "threshold": 0.5}]
    # Lines at 0 s and 3 s; the last starts at 6 s and has only 0.5 s of audio.
    assert voice_labels(audio, [0.0, 3.0, 6.0, None], profiles, FakeEncoder()) == ["DOCTOR", "PATIENT", None, None]


def test_enrolment_keeps_only_the_fingerprint(monkeypatch) -> None:
    import base64

    from fastapi.testclient import TestClient

    from app.api import voice_profiles
    from app.main import app

    class Encoder:
        def speech_only(self, audio):
            return audio

        def embed(self, audio):
            return unit(np.ones(192) + float(np.abs(audio).mean()))

    monkeypatch.setattr(voice_profiles, "encoder", lambda: Encoder())
    sentence = lambda level: base64.b64encode(np.full(48_000 * 2, level, dtype="<f4").tobytes()).decode()
    with TestClient(app) as client:
        before = {profile["id"] for profile in client.get("/api/voice-profiles").json()["profiles"]}
        too_few = client.post("/api/voice-profiles", json={"name": "Dr Ravi", "sample_rate": 48_000, "samples": [sentence(0.1)] * 3})
        assert too_few.status_code == 422 and "at least 5" in too_few.json()["detail"]
        short = client.post("/api/voice-profiles", json={"name": "Dr Ravi", "sample_rate": 48_000, "samples": [sentence(0.1)] * 5 + [base64.b64encode(np.zeros(4_800, dtype="<f4").tobytes()).decode()]})
        assert short.status_code == 422 and "Sentence 6" in short.json()["detail"]
        created = client.post("/api/voice-profiles", json={"name": "Dr Ravi", "sample_rate": 48_000, "samples": [sentence(0.1 + index / 100) for index in range(6)]})
        assert created.status_code == 200, created.text
        profile = created.json()
        assert profile["name"] == "Dr Ravi" and profile["samples"] == 6 and "embedding" not in profile
        listed = client.get("/api/voice-profiles").json()["profiles"]
        assert profile["id"] in {item["id"] for item in listed}
        assert client.delete(f"/api/voice-profiles/{profile['id']}").status_code == 204
        assert {item["id"] for item in client.get("/api/voice-profiles").json()["profiles"]} == before
