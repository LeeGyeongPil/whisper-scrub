"""Real mode (optional): transcribes a synthetic clip with a local faster-whisper model.

Skipped unless faster-whisper is installed (`uv sync --extra whisper`, planned for
M2) and WHISPER_SCRUB_MODEL_DIR points to a local tiny model folder. It never
downloads anything.
"""

from __future__ import annotations

import os

import pytest

from whisper_scrub import scrub

pytestmark = pytest.mark.real


def test_real_tiny_on_silence(make_wav):
    model_dir = os.environ.get("WHISPER_SCRUB_MODEL_DIR")
    if not model_dir:
        pytest.skip("WHISPER_SCRUB_MODEL_DIR is not set")
    faster_whisper = pytest.importorskip("faster_whisper")
    wav = make_wav([("silence", 10)])
    model = faster_whisper.WhisperModel(model_dir, device="cpu", compute_type="int8")
    segments, info = model.transcribe(str(wav), language="en")
    result = scrub(list(segments), audio_duration=info.duration)
    assert result.flagged_ratio >= 0.0  # real output varies; the check is that the pipeline runs
