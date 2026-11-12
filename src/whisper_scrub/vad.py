"""Speech intervals: from a JSON file you already have, or a simple energy VAD."""

from __future__ import annotations

import json
import wave
from pathlib import Path
from typing import Any, Iterable, Optional, Union

from .errors import AudioError, MissingExtraError, ScrubError
from .i18n import MESSAGES, Reason, fail

Interval = tuple[float, float]

NUMPY_HINT = MESSAGES["en"]["err.vad.numpy"]


def normalize_intervals(items: Iterable[Any]) -> list[Interval]:
    """Accept ``[{"start":..,"end":..}]`` or ``[[start, end]]`` (seconds); sort and merge."""
    spans: list[Interval] = []
    for n, it in enumerate(items, 1):
        try:
            if isinstance(it, dict):
                s, e = float(it["start"]), float(it["end"])
            else:
                s, e = float(it[0]), float(it[1])
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise fail(ScrubError, "err.vad.interval_format", n=n, item=it) from exc
        if e < s:
            raise fail(ScrubError, "err.vad.interval_order", n=n, item=it)
        spans.append((s, e))
    spans.sort()
    merged: list[Interval] = []
    for s, e in spans:
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged


def load_speech_json(path: Union[str, Path]) -> list[Interval]:
    """Read speech intervals (seconds) from a JSON file.

    Either a list of ``{"start", "end"}`` objects / ``[start, end]`` pairs, or an
    object with such a list under ``speech``.
    """
    p = Path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise fail(ScrubError, "err.vad.read", path=p, reason=Reason(exc)) from exc
    except json.JSONDecodeError as exc:
        raise fail(ScrubError, "err.vad.json", path=p, reason=Reason(exc)) from exc
    if isinstance(data, dict) and isinstance(data.get("speech"), list):
        data = data["speech"]
    if not isinstance(data, list):
        raise fail(ScrubError, "err.vad.shape", path=p)
    return normalize_intervals(data)


def overlap_ratio(start: float, end: float, speech: list[Interval]) -> Optional[float]:
    """Share of ``[start, end]`` covered by speech (0..1). None for empty segments."""
    length = end - start
    if length <= 0:
        return None
    covered = 0.0
    for s, e in speech:  # speech is sorted and merged
        if e <= start:
            continue
        if s >= end:
            break
        covered += min(e, end) - max(s, start)
    return min(1.0, covered / length)


def energy_vad(
    path: Union[str, Path],
    frame_ms: int = 30,
    min_silence: float = 0.3,
    min_speech: float = 0.1,
) -> tuple[list[Interval], float]:
    """Find speech intervals in a 16-bit PCM WAV by frame energy.

    Returns ``(intervals, duration_seconds)``. A frame counts as speech when
    its RMS is above 10% of the 95th-percentile RMS (full scale 1.0; a signal
    whose 95th percentile is below 1e-4 counts as digital silence). Gaps shorter than ``min_silence`` are bridged, bursts shorter
    than ``min_speech`` are dropped. This is a deliberately simple detector:
    it separates silence from sound, not speech from noise.
    """
    try:
        import numpy as np
    except ImportError as exc:
        raise fail(MissingExtraError, "err.vad.numpy") from exc

    p = Path(path)
    try:
        with wave.open(str(p), "rb") as w:
            rate, width, channels, frames = w.getframerate(), w.getsampwidth(), w.getnchannels(), w.getnframes()
            raw = w.readframes(frames)
    except (OSError, EOFError, wave.Error) as exc:
        raise fail(AudioError, "err.vad.wav", path=p, reason=Reason(exc)) from exc
    if width != 2:
        raise fail(AudioError, "err.vad.width", path=p, bits=width * 8)
    duration = frames / rate if rate else 0.0
    samples = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    if channels > 1:
        samples = samples[: len(samples) // channels * channels].reshape(-1, channels).mean(axis=1)
    frame = max(1, int(rate * frame_ms / 1000))
    n = len(samples) // frame
    if n == 0:
        return [], duration
    rms = np.sqrt((samples[: n * frame].reshape(n, frame) ** 2).mean(axis=1))
    # Relative to the signal: a quietly recorded voice is still speech. Only (near) digital
    # silence (below about -80 dBFS) has no speech at all.
    loud = float(np.percentile(rms, 95))
    threshold = max(1e-4, 0.1 * loud)
    flags = rms > threshold if loud > 1e-4 else np.zeros(n, dtype=bool)

    step = frame / rate
    spans: list[Interval] = []
    i = 0
    while i < n:
        if flags[i]:
            j = i
            while j < n and flags[j]:
                j += 1
            spans.append((i * step, min(j * step, duration)))
            i = j
        else:
            i += 1
    merged: list[Interval] = []
    for s, e in spans:
        if merged and s - merged[-1][1] < min_silence:
            merged[-1] = (merged[-1][0], e)
        else:
            merged.append((s, e))
    return [(s, e) for s, e in merged if e - s >= min_speech], duration
