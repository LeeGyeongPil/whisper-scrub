"""Markdown and JSON reports that say why each segment was flagged."""

from __future__ import annotations

from typing import Any

from ._version import __version__
from .model import KEEP, REMOVE, SUSPECT, RuleHit, ScrubResult, Segment

REPORT_VERSION = 1


def shared_meta_groups(segments: list[Segment], min_len: int = 3) -> list[dict[str, Any]]:
    """Consecutive segments with identical Whisper meta values.

    Whisper computes these per 30 s decoding window, so identical values across
    several segments mean the meta signals cannot tell those segments apart.
    """
    groups: list[dict[str, Any]] = []
    cur: list[Segment] = []

    def key(s: Segment):
        return (s.no_speech_prob, s.avg_logprob, s.compression_ratio)

    def flush() -> None:
        if len(cur) >= min_len:
            groups.append(
                {
                    "segments": [s.index for s in cur],
                    "no_speech_prob": cur[0].no_speech_prob,
                    "avg_logprob": cur[0].avg_logprob,
                    "compression_ratio": cur[0].compression_ratio,
                }
            )

    for s in segments:
        if None in key(s):
            flush()
            cur = []
            continue
        if cur and key(s) == key(cur[-1]):
            cur.append(s)
        else:
            flush()
            cur = [s]
    flush()
    return groups


def _hit(h: RuleHit) -> dict[str, Any]:
    return {"rule_id": h.rule_id, "value": h.value, "threshold": h.threshold, "note": h.note, "effect": h.effect}


def json_report(result: ScrubResult) -> dict[str, Any]:
    rows = []
    for seg, v in zip(result.segments, result.verdicts):
        rows.append(
            {
                "index": seg.index,
                "start": seg.start,
                "end": seg.end,
                "text": seg.text,
                "action": v.action,
                "confidence": v.confidence,
                "rules": [_hit(h) for h in v.rules],
            }
        )
    return {
        "report_version": REPORT_VERSION,
        "tool": f"whisper-scrub {__version__}",
        "source": result.source,
        "format": result.format,
        "summary": {
            "segments": len(result.segments),
            "removed": len(result.removed),
            "suspect": len(result.suspects),
            "kept": len(result.segments) - len(result.removed) - len(result.suspects),
            "flagged_ratio": round(result.flagged_ratio, 4),
            "repeat_runs": len(result.repeat_runs),
        },
        "audio_duration": result.audio_duration,
        "speech_intervals": None if result.speech is None else len(result.speech),
        "warnings": list(result.warnings),
        "shared_meta_groups": shared_meta_groups(result.segments),
        "thresholds": result.config.thresholds(),
        "segments": rows,
    }


def _cell(text: str, limit: int = 60) -> str:
    t = " ".join(text.split())
    if len(t) > limit:
        t = t[: limit - 1] + "…"
    return t.replace("|", "\\|")


def markdown_report(result: ScrubResult) -> str:
    n = len(result.segments)
    rem, sus = len(result.removed), len(result.suspects)
    lines = ["# whisper-scrub report", ""]
    lines.append(f"- input: {result.source or '(in memory)'}" + (f" ({result.format})" if result.format else ""))
    lines.append(f"- segments: {n} (removed {rem}, suspect {sus}, kept {n - rem - sus})")
    if result.audio_duration is not None:
        lines.append(f"- audio duration: {result.audio_duration:g} s")
    lines.append(
        "- speech intervals: " + ("not provided" if result.speech is None else str(len(result.speech)))
    )
    lines.append(f"- tool: whisper-scrub {__version__} (report_version {REPORT_VERSION})")
    for w in result.warnings:
        lines.append(f"- WARNING: {w}")
    lines.append("")

    flagged = [(s, v) for s, v in zip(result.segments, result.verdicts) if v.action != KEEP]
    if not flagged:
        lines += ["No segments were flagged.", ""]
    else:
        lines += [
            "| # | time (s) | action | confidence | rules | text |",
            "|---|---|---|---|---|---|",
        ]
        for s, v in flagged:
            rules = ", ".join(dict.fromkeys(h.rule_id for h in v.rules))
            lines.append(
                f"| {s.index} | {s.start:.2f}-{s.end:.2f} | {v.action} | {v.confidence} | {rules} | {_cell(s.text)} |"
            )
        lines += ["", "## Evidence", ""]
        for s, v in flagged:
            for h in v.rules:
                lines.append(f"- #{s.index} {v.action}: `{h.rule_id}` value={h.value} threshold={h.threshold} - {h.note}")
        lines.append("")

    groups = shared_meta_groups(result.segments)
    if groups:
        lines += ["## Shared meta values", ""]
        for g in groups:
            ids = g["segments"]
            lines.append(
                f"- segments {ids[0]}-{ids[-1]} ({len(ids)} segments) have the same meta values: "
                f"no_speech_prob={g['no_speech_prob']}, avg_logprob={g['avg_logprob']}, "
                f"compression_ratio={g['compression_ratio']}. Whisper computes them per decoding window, "
                "so meta signals cannot tell these segments apart."
            )
        lines.append("")

    lines += ["## Thresholds", ""]
    th = result.config.thresholds()
    lines.append(", ".join(f"{k}={v}" for k, v in th.items()))
    lines.append("")
    return "\n".join(lines)
