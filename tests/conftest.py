"""Shared fixtures. Nothing here needs a model, a network or an audio file."""

from __future__ import annotations

import json
import wave
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"


@pytest.fixture(scope="session")
def examples() -> Path:
    return EXAMPLES


@pytest.fixture(scope="session")
def raw_runs() -> dict:
    """The recorded faster-whisper tiny runs (one JSON object per line)."""
    lines = (EXAMPLES / "raw_runs.jsonl").read_text(encoding="utf-8").splitlines()
    return {r["name"]: r for r in map(json.loads, filter(None, lines))}


@pytest.fixture
def make_wav(tmp_path):
    """Write a 16 kHz mono 16-bit WAV from [("tone"|"silence", seconds), ...]."""
    np = pytest.importorskip("numpy")

    def _make(parts, name="clip.wav", rate=16000) -> Path:
        chunks = []
        for kind, seconds in parts:
            n = int(rate * seconds)
            if kind == "tone":
                t = np.arange(n) / rate
                chunks.append((0.5 * np.sin(2 * np.pi * 440 * t) * 32767).astype("<i2"))
            else:
                chunks.append(np.zeros(n, dtype="<i2"))
        path = tmp_path / name
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(np.concatenate(chunks).tobytes())
        return path

    return _make
