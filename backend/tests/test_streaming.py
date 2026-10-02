from app.providers.speech import TranscriptDraft
from app.providers.streaming import TranscriptCommitter


def draft(text: str, start: int, end: int) -> TranscriptDraft:
    return TranscriptDraft(text=text, timestamp=f"00:00:{start // 1000:02d}", start_ms=start, end_ms=end)


def test_overlap_deduplicates_repeated_words() -> None:
    committer = TranscriptCommitter()
    assert [item.text for item in committer.add([draft("the patient has", 0, 2500)])] == ["the patient has"]
    assert [item.text for item in committer.add([draft("patient has had a headache", 2250, 5000)])] == ["had a headache"]


def test_exact_overlap_is_committed_once() -> None:
    committer = TranscriptCommitter()
    segment = draft("there is no fever", 0, 2000)
    assert committer.add([segment]) == [segment]
    assert committer.add([draft("there is no fever", 1500, 3500)]) == []


def test_out_of_order_window_is_not_committed_to_live_evidence() -> None:
    committer = TranscriptCommitter()
    committer.add([draft("later audio", 2000, 3000)])

    assert committer.add([draft("late packet", 500, 1500)]) == []
    assert committer.out_of_order_count == 1
