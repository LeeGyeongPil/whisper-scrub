"""Degenerate speech intervals must not delete real speech (QA round 1, Q-1/Q-2)."""

from __future__ import annotations

import wave

import pytest

from whisper_scrub import Config, scrub
from whisper_scrub.cli import main
from whisper_scrub.vad import energy_vad

SENTENCES = [
    {"start": 0.0, "end": 4.0, "text": " And so my fellow Americans, ask not what your country can do."},
    {"start": 4.5, "end": 9.0, "text": " Ask what you can do for your country."},
]
SRT = (
    "1\n00:00:00,000 --> 00:00:04,000\nAnd so my fellow Americans, ask not what your country can do.\n\n"
    "2\n00:00:04,500 --> 00:00:09,000\nAsk what you can do for your country.\n"
)


def _quiet_wav(tmp_path, amplitude=0.004, seconds=10, rate=16000):
    np = pytest.importorskip("numpy")
    t = np.arange(int(rate * seconds)) / rate
    data = (amplitude * np.sin(2 * np.pi * 220 * t) * 32767).astype("<i2")
    path = tmp_path / "quiet.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(data.tobytes())
    return path


def test_empty_speech_list_does_not_delete_real_sentences():
    result = scrub(SENTENCES, speech=[])
    assert [v.action for v in result.verdicts] == ["keep", "keep"]  # audio rules skipped
    assert any("speech intervals" in w for w in result.warnings)


def test_speech_in_wrong_units_does_not_delete():
    # milliseconds instead of seconds: nothing overlaps the transcript
    result = scrub(SENTENCES + [{"start": 10.0, "end": 12.0, "text": " Third sentence here."}],
                   speech=[(100000.0, 200000.0)])
    assert not result.removed
    assert result.warnings


def test_quiet_wav_is_still_speech(tmp_path):
    wav = _quiet_wav(tmp_path)
    spans, duration = energy_vad(wav)
    assert spans and spans[0][0] == pytest.approx(0.0, abs=0.05)
    result = scrub(SENTENCES, speech=spans, audio_duration=duration)
    assert [v.action for v in result.verdicts] == ["keep", "keep"]
    assert not result.warnings


def test_digital_silence_wav_gives_warning_not_deletion(tmp_path, make_wav):
    wav = make_wav([("silence", 10)])
    spans, duration = energy_vad(wav)
    assert spans == []
    result = scrub(SENTENCES, speech=spans, audio_duration=duration)
    assert not result.removed
    assert result.warnings


def test_real_phantom_over_true_silence_is_still_removed(make_wav):
    """Positive regression: speech exists elsewhere, the phantom sits on silence."""
    wav = make_wav([("tone", 2), ("silence", 3)])
    spans, duration = energy_vad(wav)
    segments = [
        {"start": 0.0, "end": 2.0, "text": " The quarterly numbers look fine."},
        {"start": 2.5, "end": 4.5, "text": " Remember to bring the signed contract tomorrow."},
    ]
    result = scrub(segments, speech=spans, audio_duration=duration)
    assert [v.action for v in result.verdicts] == ["keep", "remove"]
    assert result.warnings == []


def test_guard_can_be_switched_off():
    result = scrub(SENTENCES, speech=[], config=Config(guard_speech_intervals=False))
    assert [v.action for v in result.verdicts] == ["remove", "remove"]
    assert result.warnings == []


def test_warning_is_in_reports():
    result = scrub(SENTENCES, speech=[])
    assert "speech intervals cover almost none" in result.report_markdown()
    assert result.report_json()["warnings"] == result.warnings


def test_cli_empty_speech_file_warns_and_keeps(tmp_path, capsys):
    srt = tmp_path / "a.srt"
    srt.write_text(SRT, encoding="utf-8")
    empty = tmp_path / "empty.json"
    empty.write_text("[]")
    out = tmp_path / "out.srt"
    assert main(["clean", str(srt), "--speech", str(empty), "-o", str(out)]) == 0
    err = capsys.readouterr().err
    assert "warning:" in err and "speech intervals cover almost none" in err
    assert out.read_text(encoding="utf-8") == SRT  # nothing was deleted


def test_config_rejects_bad_guard_ratio():
    from whisper_scrub.errors import ConfigError

    with pytest.raises(ConfigError, match="speech_guard_ratio"):
        Config(speech_guard_ratio=1.5)


def test_cli_threshold_options(tmp_path, capsys):
    srt = tmp_path / "yes.srt"
    cues = "".join(
        f"{i}\n00:00:0{i - 1},000 --> 00:00:0{i - 1},800\nYes.\n\n" for i in (1, 2, 3)
    )
    srt.write_text(cues, encoding="utf-8")
    assert main(["clean", str(srt), "--dry-run"]) == 0
    assert "removed 2" in capsys.readouterr().err
    assert main(["clean", str(srt), "--dry-run", "--repeat-min", "4"]) == 0
    assert "removed 0" in capsys.readouterr().err
    assert main(["clean", str(srt), "--dry-run", "--repeat-min", "1"]) == 2
    assert "repeat_min" in capsys.readouterr().err


def test_cli_phantom_min_seconds_option(tmp_path, capsys):
    srt = tmp_path / "p.srt"
    srt.write_text(
        "1\n00:00:00,000 --> 00:00:02,000\nThe quarterly numbers look fine.\n\n"
        "2\n00:00:02,500 --> 00:00:04,500\nRemember to bring the signed contract tomorrow.\n",
        encoding="utf-8",
    )
    speech = tmp_path / "s.json"
    speech.write_text("[[0, 2]]")
    base = ["clean", str(srt), "--speech", str(speech), "--dry-run"]
    assert main(base) == 0
    assert "removed 1" in capsys.readouterr().err
    assert main(base + ["--phantom-min-seconds", "60"]) == 0
    assert "removed 0" in capsys.readouterr().err
