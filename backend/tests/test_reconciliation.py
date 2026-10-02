import numpy as np

from app.providers.reconciliation import FinalReconciler
from app.providers.speech import AudioChunk, TranscriptDraft


def test_final_reconciliation_runs_once_on_complete_audio_and_keeps_relative_bounds() -> None:
    class FakeSTT:
        def __init__(self):
            self.calls = 0

        def transcribe_chunk(self, chunk, language=None):
            self.calls += 1
            return [TranscriptDraft(text="Two weeks", timestamp="00:00:01", start_ms=1000, end_ms=1800)]

    stt = FakeSTT()
    result = FinalReconciler().run(np.zeros(32_000, dtype=np.float32), stt, sample_rate=16_000)

    assert stt.calls == 1
    assert [draft.text for draft in result.transcripts] == ["Two weeks"]
    assert result.transcripts[0].start_ms == 1000
    assert result.transcripts[0].end_ms == 1800
