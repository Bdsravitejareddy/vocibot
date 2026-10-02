from app.providers.speech import TranscriptDraft
from app.providers.streaming import select_live_commits, TranscriptCommitter


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


def _draft(text, start_ms, end_ms):
    from app.providers.speech import TranscriptDraft
    return TranscriptDraft(text=text, timestamp="", start_ms=start_ms, end_ms=end_ms)


def test_live_commits_settle_all_but_an_unfinished_last_segment() -> None:
    decision = select_live_commits(
        [_draft("Good morning everyone.", 0, 2_000), _draft("Over the past", 2_100, 3_900)],
        buffer_start_ms=0, buffer_end_ms=4_000, holdback_ms=1_200, max_buffer_ms=12_000,
    )
    assert [draft.text for draft in decision.committed] == ["Good morning everyone."]
    assert [draft.text for draft in decision.tentative] == ["Over the past"]
    assert decision.commit_until_ms == 2_000


def test_live_commits_settle_last_segment_after_trailing_silence() -> None:
    decision = select_live_commits(
        [_draft("Welcome.", 1_000, 2_000)],
        buffer_start_ms=1_000, buffer_end_ms=3_500, holdback_ms=1_200, max_buffer_ms=12_000,
    )
    assert [draft.text for draft in decision.committed] == ["Welcome."]
    assert decision.tentative == []
    assert decision.commit_until_ms == 2_000


def test_live_commits_force_settle_an_overlong_buffer() -> None:
    decision = select_live_commits(
        [_draft("one very long run-on sentence", 0, 12_400)],
        buffer_start_ms=0, buffer_end_ms=12_500, holdback_ms=1_200, max_buffer_ms=12_000,
    )
    assert [draft.text for draft in decision.committed] == ["one very long run-on sentence"]
    assert decision.commit_until_ms == 12_400


def test_live_commits_keep_everything_tentative_while_speech_continues() -> None:
    decision = select_live_commits(
        [_draft("and a warm", 0, 1_900)],
        buffer_start_ms=0, buffer_end_ms=2_000, holdback_ms=1_200, max_buffer_ms=12_000,
    )
    assert decision.committed == []
    assert decision.commit_until_ms is None


def test_committer_keeps_indic_script_segments() -> None:
    committer = TranscriptCommitter()
    first = committer.add([_draft("नमस्ते! और काशी की इस पावन भोर में", 0, 3_000)])
    second = committer.add([_draft("इस समय हम अस्सी घाट की सीढ़ियों पर खड़े हैं।", 3_000, 6_000)])
    assert [draft.text for draft in first + second] == ["नमस्ते! और काशी की इस पावन भोर में", "इस समय हम अस्सी घाट की सीढ़ियों पर खड़े हैं।"]
    assert committer.add([_draft("सीढ़ियों पर खड़े हैं।", 4_000, 6_000)]) == []
