"""Thresholds and options for :func:`whisper_scrub.scrub`."""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Any, Optional

from .errors import ConfigError
from .i18n import fail
from .phrases import PhraseBook


@dataclass
class Config:
    """Every threshold the rules use. Defaults are conservative.

    ``phrases`` is the dictionary to match against; ``None`` means the built-in
    ko/en/ja/zh dictionaries. To add your own entries use
    ``PhraseBook.builtin().merge(PhraseBook.from_file("my.tsv"))``.
    """

    # meta signals (Whisper segment fields)
    no_speech_threshold: float = 0.6  # meta.no_speech
    silent_no_speech: float = 0.8  # meta.silent_window: no_speech_prob >=
    silent_logprob: float = -1.0  # ... and avg_logprob <
    # repeats
    repeat_min: int = 3  # repeat.run: same sentence this many times in a row
    repeat_max_gap: float = 10.0  # seconds between neighbours still counted as one run
    loop_min: int = 4  # repeat.loop: n-gram repeated this many times inside a segment
    # audio
    speech_overlap_min: float = 0.1  # audio.no_speech: overlap ratio below this
    phantom_min_seconds: float = 1.0  # zero-overlap segments at least this long are removed
    beyond_end_slack: float = 0.5  # seconds a segment may run past the audio end
    # when the speech intervals look broken (empty, or covering almost no transcript) audio.no_speech
    # stops removing on its own and a warning is reported
    guard_speech_intervals: bool = True
    speech_guard_ratio: float = 0.8  # share of zero-overlap candidate segments that counts as broken
    # isolated segment helper
    isolated_gap: float = 2.0
    isolated_max_seconds: float = 3.0
    isolated_max_words: int = 3
    # text matching
    substring: bool = False  # phrase match inside longer text (off: false positives)
    substring_min_len: int = 6  # minimum normalised phrase length for substring matches
    lang: Optional[str] = None  # force a dictionary language instead of guessing
    phrases: Optional[PhraseBook] = field(default=None, repr=False)
    # check metrics
    max_chars_per_second: float = 30.0

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        for name in ("no_speech_threshold", "silent_no_speech", "speech_overlap_min", "speech_guard_ratio"):
            v = getattr(self, name)
            if not 0.0 <= v <= 1.0:
                raise fail(ConfigError, "err.config.range", name=name, value=v)
        if self.silent_logprob > 0:
            raise fail(ConfigError, "err.config.silent_logprob", value=self.silent_logprob)
        if self.repeat_min < 2:
            raise fail(ConfigError, "err.config.repeat_min", value=self.repeat_min)
        if self.loop_min < 2:
            raise fail(ConfigError, "err.config.loop_min", value=self.loop_min)
        for name in (
            "repeat_max_gap",
            "phantom_min_seconds",
            "beyond_end_slack",
            "isolated_gap",
            "isolated_max_seconds",
            "max_chars_per_second",
        ):
            if getattr(self, name) < 0:
                raise fail(ConfigError, "err.config.negative", name=name, value=getattr(self, name))
        if self.lang is not None and self.lang not in ("ko", "en", "ja", "zh"):
            raise fail(ConfigError, "err.config.lang", value=self.lang)

    def book(self) -> PhraseBook:
        if self.phrases is None:
            self.phrases = PhraseBook.builtin()
        return self.phrases

    def thresholds(self) -> dict[str, Any]:
        """Plain dict of thresholds for reports (the phrase book is left out)."""
        return {f.name: getattr(self, f.name) for f in fields(self) if f.name != "phrases"}
