import re
from dataclasses import dataclass, field

from .speech import TranscriptDraft


# Split on whitespace and punctuation only, so Indic scripts (whose vowel
# signs are not \w characters) still produce words.
_WORD = re.compile(r"[^\s.,!?;:\"“”‘’()\[\]{}।॥\-–—]+")


def _words(text: str) -> list[str]:
    return [word.strip("'") for word in _WORD.findall(text.lower()) if word.strip("'")]


@dataclass
class TranscriptCommitter:
    """Commit final ASR segments once, removing overlap duplicates."""

    committed: list[TranscriptDraft] = field(default_factory=list)
    out_of_order_count: int = 0

    def add(self, drafts: list[TranscriptDraft]) -> list[TranscriptDraft]:
        emitted: list[TranscriptDraft] = []
        for draft in sorted(drafts, key=lambda item: (item.start_ms or 0, item.end_ms or 0)):
            text = draft.text.strip()
            if not text:
                continue
            candidate_words = _words(text)
            if not candidate_words:
                continue
            if self.committed and draft.end_ms is not None and self.committed[-1].start_ms is not None and draft.end_ms <= self.committed[-1].start_ms:
                self.out_of_order_count += 1
                continue
            previous_text = " ".join(item.text for item in self.committed[-3:])
            previous_words = _words(previous_text)
            if candidate_words == previous_words[-len(candidate_words):] or " ".join(candidate_words) in " ".join(previous_words):
                continue
            overlap = self._suffix_prefix_overlap(previous_words, candidate_words)
            if overlap >= 2:
                remaining = candidate_words[overlap:]
                if not remaining:
                    continue
                text = " ".join(remaining)
                draft = TranscriptDraft(
                    text=text,
                    timestamp=draft.timestamp,
                    speaker=draft.speaker,
                    start_ms=draft.start_ms,
                    end_ms=draft.end_ms,
                    language_code=draft.language_code,
                )
            self.committed.append(draft)
            emitted.append(draft)
        return emitted

    @staticmethod
    def _suffix_prefix_overlap(previous: list[str], current: list[str]) -> int:
        maximum = min(len(previous), len(current))
        for size in range(maximum, 1, -1):
            if previous[-size:] == current[:size]:
                return size
        return 0


@dataclass(frozen=True)
class LiveCommitDecision:
    committed: list[TranscriptDraft]
    tentative: list[TranscriptDraft]
    # Absolute capture time (ms) up to which audio is settled and can be dropped.
    commit_until_ms: int | None


def select_live_commits(
    drafts: list[TranscriptDraft],
    *,
    buffer_start_ms: int,
    buffer_end_ms: int,
    holdback_ms: int,
    max_buffer_ms: int,
) -> LiveCommitDecision:
    """Decide which segments of a rolling-buffer transcription are settled.

    Whisper re-transcribes the uncommitted audio each step.  A segment is
    settled once a later segment follows it, or once enough trailing audio has
    passed after it that Whisper will not revise it.  The final segment stays
    tentative while the speaker may still be mid-sentence, unless the buffer
    has grown past ``max_buffer_ms`` and must be trimmed to bound latency.
    """

    ordered = sorted(
        (draft for draft in drafts if draft.text.strip() and draft.start_ms is not None and draft.end_ms is not None),
        key=lambda draft: (draft.start_ms, draft.end_ms),
    )
    if not ordered:
        return LiveCommitDecision([], [], None)
    settled_before_ms = buffer_end_ms - holdback_ms
    committed: list[TranscriptDraft] = []
    for index, draft in enumerate(ordered):
        is_last = index == len(ordered) - 1
        if not is_last or draft.end_ms <= settled_before_ms:  # type: ignore[operator]
            committed.append(draft)
        else:
            break
    if not committed and buffer_end_ms - buffer_start_ms >= max_buffer_ms:
        committed = list(ordered)
    tentative = ordered[len(committed):]
    commit_until_ms = None
    if committed:
        commit_until_ms = min(buffer_end_ms, max(buffer_start_ms, max(draft.end_ms for draft in committed)))  # type: ignore[type-var]
    return LiveCommitDecision(committed, tentative, commit_until_ms)
