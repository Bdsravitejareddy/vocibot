import re
from dataclasses import dataclass, field

from .speech import TranscriptDraft


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower())


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
