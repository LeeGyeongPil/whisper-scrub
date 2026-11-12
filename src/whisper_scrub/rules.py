"""The individual detection rules. Each returns a :class:`RuleHit` or ``None``.

Rule IDs are part of the public contract (they appear in reports):

==================== ================================================ ============
rule                 fires when                                        effect
==================== ================================================ ============
phrase.strict        text equals a ``strict`` dictionary phrase        remove
phrase.weak          text equals a ``weak`` dictionary phrase          support
repeat.run           same sentence 3+ times in a row (2nd.. copies)    remove
repeat.loop          an n-gram repeats 4+ times inside one segment     suspect
meta.no_speech       no_speech_prob >= 0.6                             support
meta.silent_window   no_speech_prob >= 0.8 and avg_logprob < -1.0      remove
audio.no_speech      speech overlap < 0.1 (0 and >= 1 s: remove)       support
audio.beyond_end     starts after the audio ends / ends > 0.5 s past   remove/suspect
text.broken          contains U+FFFD                                   suspect
segment.isolated     short segment far from its neighbours             support
==================== ================================================ ============

``support`` hits never delete on their own; the judge combines them.
"""

from __future__ import annotations

from typing import Optional, Sequence

from .config import Config
from .i18n import MESSAGES
from .model import RuleHit, Segment
from .normalize import detect_lang, normalize
from .vad import Interval, overlap_ratio

CJK = ("ko", "ja", "zh")


def phrase_hit(seg: Segment, norm: str, cfg: Config) -> Optional[RuleHit]:
    if not norm:
        return None
    book = cfg.book()
    detected = detect_lang(norm)
    langs = [cfg.lang] if cfg.lang else []
    if detected and detected not in langs:
        langs.append(detected)
    for lang in langs:
        entry = book.lookup(norm, lang)
        how = "exact"
        if entry is None and cfg.substring:
            entry = book.find_substring(norm, lang, cfg.substring_min_len)
            how = "substring"
        if entry is not None:
            src = f", source: {entry.source}" if entry.source else ""
            return RuleHit(
                f"phrase.{entry.level}",
                entry.phrase,
                how,
                f"{how} match of {lang} dictionary phrase {entry.phrase!r} ({entry.level}{src})",
                effect="remove" if entry.level == "strict" else "support",
            )
    return None


def repeat_runs(segments: Sequence[Segment], norms: Sequence[str], cfg: Config) -> list[list[int]]:
    """Runs of the same normalised sentence in consecutive segments.

    Returns lists of 0-based positions, each list at least ``repeat_min`` long.
    The caller keeps the first position and removes the rest.
    """
    runs: list[list[int]] = []
    cur: list[int] = []
    for i, norm in enumerate(norms):
        if (
            cur
            and norm
            and norm == norms[cur[-1]]
            and segments[i].start - segments[cur[-1]].end <= cfg.repeat_max_gap
        ):
            cur.append(i)
            continue
        if len(cur) >= cfg.repeat_min:
            runs.append(cur)
        cur = [i] if norm else []
    if len(cur) >= cfg.repeat_min:
        runs.append(cur)
    return runs


def find_repeat(seq: Sequence[str], min_reps: int, units: range) -> Optional[tuple[int, int, int]]:
    """First ``(start, unit, reps)`` where ``seq[start:start+unit]`` repeats ``min_reps``+ times."""
    n = len(seq)
    for unit in units:
        if unit * min_reps > n:
            break
        for i in range(0, n - unit * min_reps + 1):
            reps = 1
            while i + (reps + 1) * unit <= n and list(seq[i + reps * unit : i + (reps + 1) * unit]) == list(
                seq[i : i + unit]
            ):
                reps += 1
            if reps >= min_reps:
                return i, unit, reps
    return None


def repeat_loop(seg: Segment, norm: str, cfg: Config) -> Optional[RuleHit]:
    if not norm or len(norm) > 4000:
        return None
    if detect_lang(norm) in CJK:
        seq: Sequence[str] = list(norm)
        found = find_repeat(seq, cfg.loop_min, range(2, 13))
    else:
        seq = norm.split()
        found = find_repeat(seq, cfg.loop_min, range(1, 9))
    if not found:
        return None
    start, unit, reps = found
    piece = "".join(seq[start : start + unit]) if detect_lang(norm) in CJK else " ".join(seq[start : start + unit])
    return RuleHit(
        "repeat.loop",
        f"{piece!r} x{reps}",
        f">= {cfg.loop_min}",
        f"{piece!r} repeats {reps} times inside one segment",
    )


def meta_no_speech(seg: Segment, cfg: Config) -> Optional[RuleHit]:
    p = seg.no_speech_prob
    if p is not None and p >= cfg.no_speech_threshold:
        return RuleHit(
            "meta.no_speech", p, f">= {cfg.no_speech_threshold}",
            f"no_speech_prob {p} is at or above {cfg.no_speech_threshold}", effect="support",
        )
    return None


def meta_silent_window(seg: Segment, cfg: Config) -> Optional[RuleHit]:
    p, lp = seg.no_speech_prob, seg.avg_logprob
    if p is not None and lp is not None and p >= cfg.silent_no_speech and lp < cfg.silent_logprob:
        return RuleHit(
            "meta.silent_window",
            f"no_speech_prob={p}, avg_logprob={lp}",
            f"no_speech_prob >= {cfg.silent_no_speech} and avg_logprob < {cfg.silent_logprob}",
            "very likely silent and the decoder was unsure",
            effect="remove",
        )
    return None


# English text stored in ScrubResult.warnings; the CLI shows it in the display language.
SPEECH_GUARD_WARNING = MESSAGES["en"]["warn.speech_guard"]


def speech_intervals_untrustworthy(
    segments: Sequence[Segment], norms: Sequence[str], speech: Optional[list[Interval]], cfg: Config
) -> bool:
    """True when the speech intervals look broken rather than informative.

    Broken means: empty, or (with 3+ candidate segments) at least
    ``speech_guard_ratio`` of the text segments long enough to be phantoms have
    zero speech overlap. A genuine phantom sits among real speech, so it never
    reaches that share.
    """
    if speech is None or not cfg.guard_speech_intervals:
        return False
    cands = [s for s, n in zip(segments, norms) if n and s.duration >= cfg.phantom_min_seconds]
    if not cands:
        return False
    if not speech:
        return True
    zero = sum(1 for s in cands if overlap_ratio(s.start, s.end, speech) == 0)
    return len(cands) >= 3 and zero / len(cands) >= cfg.speech_guard_ratio


def audio_no_speech(seg: Segment, speech: Optional[list[Interval]], cfg: Config) -> Optional[RuleHit]:
    if speech is None:
        return None
    ratio = overlap_ratio(seg.start, seg.end, speech)
    if ratio is None or ratio >= cfg.speech_overlap_min:
        return None
    phantom = ratio == 0 and seg.duration >= cfg.phantom_min_seconds
    note = (
        f"no speech in the audio under this {seg.duration:.1f}s segment (even a fluent sentence is a phantom)"
        if phantom
        else f"only {ratio:.2f} of the segment overlaps speech"
    )
    return RuleHit(
        "audio.no_speech", round(ratio, 3), f"< {cfg.speech_overlap_min}", note,
        effect="remove" if phantom else "support",
    )


def audio_beyond_end(seg: Segment, duration: Optional[float], cfg: Config) -> Optional[RuleHit]:
    if duration is None:
        return None
    if seg.start >= duration:
        return RuleHit(
            "audio.beyond_end", seg.start, f"< {duration}",
            f"starts at {seg.start}s but the audio is only {duration}s long", effect="remove",
        )
    if seg.end > duration + cfg.beyond_end_slack:
        return RuleHit(
            "audio.beyond_end", seg.end, f"<= {duration + cfg.beyond_end_slack}",
            f"ends at {seg.end}s but the audio is only {duration}s long", effect="suspect",
        )
    return None


def text_broken(seg: Segment) -> Optional[RuleHit]:
    if "�" in seg.text:
        return RuleHit("text.broken", "U+FFFD", "absent", "contains the Unicode replacement character")
    return None


def segment_isolated(
    prev: Optional[Segment], seg: Segment, nxt: Optional[Segment], norm: str, cfg: Config
) -> Optional[RuleHit]:
    if prev is None and nxt is None:
        return None
    short = len(norm) <= 12 if detect_lang(norm) in CJK else len(norm.split()) <= cfg.isolated_max_words
    if not short or seg.duration > cfg.isolated_max_seconds:
        return None
    gaps = []
    if prev is not None:
        gaps.append(seg.start - prev.end)
    if nxt is not None:
        gaps.append(nxt.start - seg.end)
    if all(g >= cfg.isolated_gap for g in gaps):
        return RuleHit(
            "segment.isolated", round(min(gaps), 2), f">= {cfg.isolated_gap}s gap",
            "short segment with long silence before and after it", effect="support",
        )
    return None
