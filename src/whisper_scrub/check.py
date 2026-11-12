"""Quality metrics that need no reference transcript."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from .i18n import translate
from .model import ScrubResult
from .normalize import normalize


@dataclass
class CheckReport:
    segments: int
    removed: int
    suspect: int
    flagged: int
    flagged_ratio: float
    repeat_runs: int
    speechless_char_ratio: Optional[float]  # None when no audio/speech information
    fast_segments: int  # characters per second above the configured maximum

    def summary_line(self, lang: str = "en") -> str:
        """One-line summary; English unless ``lang="ko"`` is passed."""
        speechless = (
            translate(lang, "out.na")
            if self.speechless_char_ratio is None
            else f"{self.speechless_char_ratio:.2f}"
        )
        return translate(
            lang,
            "check.summary",
            flagged=self.flagged,
            segments=self.segments,
            ratio=self.flagged_ratio,
            removed=self.removed,
            suspect=self.suspect,
            repeat_runs=self.repeat_runs,
            speechless=speechless,
            fast=self.fast_segments,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "segments": self.segments,
            "removed": self.removed,
            "suspect": self.suspect,
            "flagged": self.flagged,
            "flagged_ratio": round(self.flagged_ratio, 4),
            "repeat_runs": self.repeat_runs,
            "speechless_char_ratio": self.speechless_char_ratio,
            "fast_segments": self.fast_segments,
        }


def check_result(result: ScrubResult) -> CheckReport:
    n = len(result.segments)
    removed, suspect = len(result.removed), len(result.suspects)
    speechless: Optional[float] = None
    if result.speech is not None:
        total = sum(len(normalize(s.text)) for s in result.segments)
        bad = sum(
            len(normalize(s.text))
            for s, v in zip(result.segments, result.verdicts)
            if any(h.rule_id == "audio.no_speech" for h in v.rules)
        )
        speechless = bad / total if total else 0.0
    fast = sum(
        1
        for s in result.segments
        if s.duration > 0 and len(normalize(s.text)) / s.duration > result.config.max_chars_per_second
    )
    return CheckReport(
        segments=n,
        removed=removed,
        suspect=suspect,
        flagged=removed + suspect,
        flagged_ratio=(removed + suspect) / n if n else 0.0,
        repeat_runs=len(result.repeat_runs),
        speechless_char_ratio=speechless,
        fast_segments=fast,
    )
