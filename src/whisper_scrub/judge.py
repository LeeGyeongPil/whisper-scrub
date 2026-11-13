"""Combine rule hits into remove / suspect / keep verdicts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Optional, Union

from . import rules
from .config import Config
from .errors import ConfigError
from .i18n import fail
from .io import Document, load, segments_from_items
from .model import KEEP, REMOVE, SUSPECT, RuleHit, ScrubResult, Segment, Verdict
from .normalize import normalize
from .vad import Interval, energy_vad, load_speech_json, normalize_intervals, overlap_ratio

STAR_RULES = ("meta.no_speech", "audio.no_speech")


def _judge_one(
    seg: Segment,
    hits: list[RuleHit],
    speech: Optional[list[Interval]],
    isolated: Optional[RuleHit],
    cfg: Config,
) -> Verdict:
    if any(h.effect == "remove" for h in hits):
        return Verdict(seg.index, REMOVE, "high", hits)
    weak = next((h for h in hits if h.rule_id == "phrase.weak"), None)
    star = [h for h in hits if h.rule_id in STAR_RULES]
    if weak and star:
        return Verdict(seg.index, REMOVE, "medium", hits)
    if weak and not star:
        ratio = overlap_ratio(seg.start, seg.end, speech) if speech is not None else None
        # Evidence that somebody really spoke: Whisper itself says speech, or the audio overlaps.
        counter = seg.has_meta or ratio is not None
        if counter and not any(h.effect == "suspect" for h in hits):
            return Verdict(seg.index, KEEP, "none", hits)
        if isolated:
            hits = hits + [isolated]
        return Verdict(seg.index, SUSPECT, "low", hits)
    if star or any(h.effect == "suspect" for h in hits):
        return Verdict(seg.index, SUSPECT, "low", hits)
    return Verdict(seg.index, KEEP, "none", hits)


def scrub(
    segments: Union[Iterable[Any], Document],
    *,
    audio_duration: Optional[float] = None,
    speech: Optional[Iterable[Any]] = None,
    config: Optional[Config] = None,
) -> ScrubResult:
    """Judge every segment.

    ``segments``: dicts (openai-whisper, verbose_json, whisper.cpp entries),
    faster-whisper ``Segment`` objects, :class:`Segment`, or a loaded Document.
    ``speech``: optional speech intervals in seconds (``(start, end)`` pairs or
    ``{"start", "end"}`` dicts). ``audio_duration``: optional length of the audio
    in seconds, used by ``audio.beyond_end``.
    """
    cfg = config or Config()
    doc: Optional[Document] = segments if isinstance(segments, Document) else None
    segs = doc.segments if doc is not None else segments_from_items(segments)
    if audio_duration is None and doc is not None:
        audio_duration = doc.duration
    if audio_duration is not None and audio_duration <= 0:
        raise fail(ConfigError, "err.config.audio_duration", value=audio_duration)
    spans = normalize_intervals(speech) if speech is not None else None

    norms = [normalize(s.text) for s in segs]
    # Broken speech intervals (empty, wrong units, too-quiet recording) must never delete real speech.
    warnings: list[str] = []
    trusted = not rules.speech_intervals_untrustworthy(segs, norms, spans, cfg)
    if not trusted:
        warnings.append(rules.SPEECH_GUARD_WARNING)
    # untrusted intervals are ignored by every speech-interval rule (audio.no_speech and the speech counter-evidence; as if --speech was not given)
    rule_spans = spans if trusted else None
    runs = rules.repeat_runs(segs, norms, cfg)
    run_info: dict[int, tuple[int, int]] = {}
    for run in runs:
        for k, pos in enumerate(run[1:], 2):
            run_info[pos] = (k, len(run))

    verdicts: list[Verdict] = []
    for i, seg in enumerate(segs):
        norm = norms[i]
        hits: list[RuleHit] = []
        for h in (rules.phrase_hit(seg, norm, cfg),):
            if h:
                hits.append(h)
        if i in run_info:
            k, n = run_info[i]
            hits.append(
                RuleHit(
                    "repeat.run", f"copy {k} of {n}", f">= {cfg.repeat_min} in a row",
                    f"same sentence as the previous segment; the first of {n} copies is kept",
                    effect="remove",
                )
            )
        for h in (
            rules.repeat_loop(seg, norm, cfg),
            rules.meta_no_speech(seg, cfg),
            rules.meta_silent_window(seg, cfg),
            rules.audio_no_speech(seg, rule_spans, cfg),
            rules.audio_beyond_end(seg, audio_duration, cfg),
            rules.text_broken(seg),
        ):
            if h:
                hits.append(h)
        isolated = rules.segment_isolated(
            segs[i - 1] if i > 0 else None, seg, segs[i + 1] if i + 1 < len(segs) else None, norm, cfg
        )
        verdicts.append(_judge_one(seg, hits, rule_spans, isolated, cfg))

    return ScrubResult(
        segments=segs,
        verdicts=verdicts,
        config=cfg,
        audio_duration=audio_duration,
        speech=spans,
        source=doc.source if doc else None,
        format=doc.format if doc else None,
        document=doc,
        repeat_runs=runs,
        warnings=warnings,
    )


def scrub_file(
    path: Union[str, Path],
    out: Union[str, Path, None] = None,
    *,
    audio: Union[str, Path, None] = None,
    speech: Union[str, Path, Iterable[Any], None] = None,
    audio_duration: Optional[float] = None,
    report: Union[str, Path, None] = None,
    dry_run: bool = False,
    renumber: bool = False,
    config: Optional[Config] = None,
) -> ScrubResult:
    """Load a file, judge it, and optionally write the cleaned copy and a report.

    The input file is never modified. ``out`` is required unless ``dry_run``.
    ``report`` is written as JSON when it ends in ``.json``, otherwise Markdown.
    """
    src = Path(path)
    if not dry_run and out is None:
        raise fail(ConfigError, "err.config.need_out")
    if out is not None and Path(out).resolve() == src.resolve():
        raise fail(ConfigError, "err.config.same_out")
    doc = load(src)

    spans: Optional[list[Interval]] = None
    if audio is not None and speech is not None:
        raise fail(ConfigError, "err.config.audio_and_speech")
    if audio is not None:
        spans, wav_duration = energy_vad(audio)
        if audio_duration is None:
            audio_duration = wav_duration
    elif isinstance(speech, (str, Path)):
        spans = load_speech_json(speech)
    elif speech is not None:
        spans = normalize_intervals(speech)

    result = scrub(doc, audio_duration=audio_duration, speech=spans, config=config)
    if not dry_run:
        removed = {i for i, v in enumerate(result.verdicts) if v.action == REMOVE}
        Path(out).write_bytes(doc.render_bytes(removed, renumber))  # type: ignore[arg-type]
    if report is not None:
        text = (
            json.dumps(result.report_json(), ensure_ascii=False, indent=2) + "\n"
            if str(report).endswith(".json")
            else result.report_markdown()
        )
        Path(report).write_text(text, encoding="utf-8")
    return result
