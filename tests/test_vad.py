"""Audio signals (AC-6)."""

from __future__ import annotations

import json
import sys

import pytest

from whisper_scrub import MissingExtraError, load, scrub
from whisper_scrub.errors import AudioError, ScrubError
from whisper_scrub.vad import energy_vad, load_speech_json, normalize_intervals, overlap_ratio


def test_speech_json_overlap(examples):
    speech = load_speech_json(examples / "mixed_vad_speech.json")
    doc = load(examples / "mixed_en.json")
    assert overlap_ratio(30.0, 32.0, speech) == 0.0
    assert overlap_ratio(0.0, 11.0, speech) > 0.9
    result = scrub(doc, speech=speech)
    assert [v.action for v in result.verdicts] == ["keep", "remove", "keep"]


def test_energy_vad_finds_silence(make_wav):
    wav = make_wav([("tone", 2), ("silence", 3)])
    spans, duration = energy_vad(wav)
    assert duration == pytest.approx(5.0)
    assert len(spans) == 1
    start, end = spans[0]
    assert start == pytest.approx(0.0, abs=0.05) and end == pytest.approx(2.0, abs=0.1)
    assert overlap_ratio(2.5, 4.5, spans) == 0.0


def test_fluent_phantom_removed_by_audio(make_wav):
    wav = make_wav([("tone", 2), ("silence", 3)])
    spans, duration = energy_vad(wav)
    segments = [
        {"start": 0.0, "end": 2.0, "text": " The quarterly numbers look fine."},
        {"start": 2.5, "end": 4.5, "text": " Remember to bring the signed contract tomorrow."},
    ]
    result = scrub(segments, speech=spans, audio_duration=duration)
    assert [v.action for v in result.verdicts] == ["keep", "remove"]
    assert [h.rule_id for h in result.verdicts[1].rules] == ["audio.no_speech"]
    assert result.verdicts[1].confidence == "high"


def test_short_unvoiced_segment_is_only_suspect(make_wav):
    wav = make_wav([("tone", 2), ("silence", 3)])
    spans, _ = energy_vad(wav)
    result = scrub([{"start": 2.5, "end": 3.0, "text": " Okay then."}], speech=spans)
    assert result.verdicts[0].action == "suspect"  # under 1 s: not enough to delete


def test_missing_numpy_message(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "numpy", None)  # makes `import numpy` raise ImportError
    with pytest.raises(MissingExtraError) as exc:
        energy_vad(tmp_path / "whatever.wav")
    assert 'pip install "whisper-scrub[audio]"' in str(exc.value)


def test_bad_wav_gives_conversion_hint(tmp_path):
    pytest.importorskip("numpy")
    p = tmp_path / "x.wav"
    p.write_bytes(b"not a wav")
    with pytest.raises(AudioError, match="ffmpeg"):
        energy_vad(p)


def test_interval_inputs(tmp_path):
    assert normalize_intervals([[3, 4], {"start": 0, "end": 3.5}]) == [(0.0, 4.0)]
    with pytest.raises(ScrubError, match="ends before"):
        normalize_intervals([[5, 1]])
    with pytest.raises(ScrubError, match="seconds"):
        normalize_intervals([{"begin": 1}])
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"speech": [[0, 1]]}))
    assert load_speech_json(p) == [(0.0, 1.0)]
    p.write_text("{oops")
    with pytest.raises(ScrubError, match="not valid JSON"):
        load_speech_json(p)
