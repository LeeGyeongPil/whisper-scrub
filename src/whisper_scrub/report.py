"""Markdown and JSON reports that say why each segment was flagged."""

from __future__ import annotations

from typing import Any

from ._version import __version__
from .i18n import localize_warning, translate
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


def markdown_report(result: ScrubResult, lang: str = "en") -> str:
    """Markdown report. English by default; ``lang="ko"`` translates the labels (not the rule notes)."""

    def t(key: str, **params: Any) -> str:
        return translate(lang, key, **params)

    n = len(result.segments)
    rem, sus = len(result.removed), len(result.suspects)
    lines = [t("report.title"), ""]
    lines.append(
        t("report.input", source=result.source or t("report.in_memory"))
        + (t("report.input_format", format=result.format) if result.format else "")
    )
    lines.append(t("report.segments", total=n, removed=rem, suspect=sus, kept=n - rem - sus))
    if result.audio_duration is not None:
        lines.append(t("report.audio_duration", seconds=result.audio_duration))
    lines.append(
        t(
            "report.speech_intervals",
            value=t("report.not_provided") if result.speech is None else str(len(result.speech)),
        )
    )
    lines.append(t("report.tool", version=__version__, report_version=REPORT_VERSION))
    for w in result.warnings:
        lines.append(t("report.warning", text=localize_warning(w, lang)))
    lines.append("")

    flagged = [(s, v) for s, v in zip(result.segments, result.verdicts) if v.action != KEEP]
    if not flagged:
        lines += [t("report.none_flagged"), ""]
    else:
        lines += [
            t("report.table_header"),
            "|---|---|---|---|---|---|",
        ]
        for s, v in flagged:
            rules = ", ".join(dict.fromkeys(h.rule_id for h in v.rules))
            lines.append(
                f"| {s.index} | {s.start:.2f}-{s.end:.2f} | {v.action} | {v.confidence} | {rules} | {_cell(s.text)} |"
            )
        lines += ["", t("report.evidence_title"), ""]
        for s, v in flagged:
            for h in v.rules:
                lines.append(
                    t(
                        "report.evidence_line",
                        index=s.index,
                        action=v.action,
                        rule=h.rule_id,
                        value=h.value,
                        threshold=h.threshold,
                        note=h.note,
                    )
                )
        lines.append("")

    groups = shared_meta_groups(result.segments)
    if groups:
        lines += [t("report.shared_title"), ""]
        for g in groups:
            ids = g["segments"]
            lines.append(
                t(
                    "report.shared_line",
                    first=ids[0],
                    last=ids[-1],
                    count=len(ids),
                    no_speech_prob=g["no_speech_prob"],
                    avg_logprob=g["avg_logprob"],
                    compression_ratio=g["compression_ratio"],
                )
            )
        lines.append("")

    lines += [t("report.thresholds_title"), ""]
    th = result.config.thresholds()
    lines.append(", ".join(f"{k}={v}" for k, v in th.items()))
    lines.append("")
    return "\n".join(lines)
