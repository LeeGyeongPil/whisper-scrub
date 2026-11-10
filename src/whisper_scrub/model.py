"""Plain data classes shared by every module."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .config import Config
    from .io.document import Document

REMOVE = "remove"
SUSPECT = "suspect"
KEEP = "keep"


@dataclass
class Segment:
    """One transcript segment.

    ``index`` is the 1-based position in the input. The signal fields are
    ``None`` when the input format does not carry them (SRT, VTT, whisper.cpp).
    """

    index: int
    start: float
    end: float
    text: str
    no_speech_prob: Optional[float] = None
    avg_logprob: Optional[float] = None
    compression_ratio: Optional[float] = None
    temperature: Optional[float] = None
    raw: Any = field(default=None, repr=False, compare=False)

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    @property
    def has_meta(self) -> bool:
        """True when Whisper's own no-speech probability is available."""
        return self.no_speech_prob is not None


@dataclass
class RuleHit:
    """Evidence from one rule.

    ``effect`` says what the hit may do on its own: ``remove`` (enough to
    delete), ``suspect`` (enough to flag), ``support`` (only counts together
    with another signal).
    """

    rule_id: str
    value: Any
    threshold: Any
    note: str
    effect: str = "suspect"


@dataclass
class Verdict:
    index: int
    action: str  # "remove" | "suspect" | "keep"
    confidence: str  # "high" | "medium" | "low" | "none"
    rules: list[RuleHit] = field(default_factory=list)


@dataclass
class ScrubResult:
    """Outcome of :func:`whisper_scrub.scrub`."""

    segments: list[Segment]
    verdicts: list[Verdict]
    config: "Config"
    audio_duration: Optional[float] = None
    speech: Optional[list[tuple[float, float]]] = None
    source: Optional[str] = None
    format: Optional[str] = None
    document: Optional["Document"] = field(default=None, repr=False)
    # 0-based positions of every detected repeat run (first copy included)
    repeat_runs: list[list[int]] = field(default_factory=list)
    # human-readable problems with the inputs (e.g. speech intervals that look broken)
    warnings: list[str] = field(default_factory=list)

    def _pick(self, action: str) -> list[Segment]:
        return [s for s, v in zip(self.segments, self.verdicts) if v.action == action]

    @property
    def kept(self) -> list[Segment]:
        """Segments that stay in the cleaned transcript (``keep`` and ``suspect``)."""
        return [s for s, v in zip(self.segments, self.verdicts) if v.action != REMOVE]

    @property
    def removed(self) -> list[Segment]:
        return self._pick(REMOVE)

    @property
    def suspects(self) -> list[Segment]:
        return self._pick(SUSPECT)

    @property
    def flagged_ratio(self) -> float:
        if not self.segments:
            return 0.0
        return (len(self.removed) + len(self.suspects)) / len(self.segments)

    def report_markdown(self) -> str:
        from .report import markdown_report

        return markdown_report(self)

    def report_json(self) -> dict[str, Any]:
        from .report import json_report

        return json_report(self)
