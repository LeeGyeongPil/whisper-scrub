"""CLI behaviour (AC-7, AC-8) and its error messages."""

from __future__ import annotations

import json
import subprocess
import sys

from whisper_scrub.cli import main


def test_dry_run_suspect_then_remove_with_speech(examples, capsys):
    srt = examples / "mixed_en.srt"
    before = srt.read_bytes()

    assert main(["clean", str(srt), "--dry-run", "--report", "-"]) == 0
    out = capsys.readouterr().out
    assert "| 2 | 30.00-32.00 | suspect | low | phrase.weak, segment.isolated | You |" in out

    argv = ["clean", str(srt), "--speech", str(examples / "mixed_vad_speech.json"), "--dry-run", "--report", "-"]
    assert main(argv) == 0
    out = capsys.readouterr().out
    rows = [line for line in out.splitlines() if line.startswith("| ") and "| remove |" in line]
    assert len(rows) == 1
    assert "phrase.weak, audio.no_speech" in rows[0]
    assert srt.read_bytes() == before  # the input is never modified


def test_clean_writes_output_and_report_files(examples, tmp_path, capsys):
    out_file, report = tmp_path / "o.srt", tmp_path / "r.json"
    code = main(["clean", str(examples / "mixed_ko.srt"), "-o", str(out_file), "--report", str(report)])
    assert code == 0
    assert out_file.exists()
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["summary"]["removed"] == 7 and data["report_version"] == 1
    assert "removed 7, suspect 1, kept 2 of 10" in capsys.readouterr().err


def test_check_fails_over_threshold(examples, capsys):
    assert main(["check", str(examples / "mixed_ko.srt"), "--fail-over", "0.3"]) == 1
    out = capsys.readouterr().out
    assert "flagged 8/10 (0.80)" in out and "repeat runs: 1" in out
    assert main(["check", str(examples / "mixed_ko.srt"), "--fail-over", "0.9"]) == 0
    assert main(["check", str(examples / "mixed_en.srt")]) == 0  # no threshold: informational


def test_check_json_format_and_many_files(examples, capsys):
    argv = ["check", str(examples / "mixed_en.json"), str(examples / "mixed_ko.json"), "--format", "json"]
    assert main(argv) == 0
    rows = json.loads(capsys.readouterr().out)
    assert [r["flagged"] for r in rows] == [1, 8]
    assert rows[1]["repeat_runs"] == 1


def test_phrases_lists_dictionary(capsys):
    assert main(["phrases", "--lang", "ko"]) == 0
    assert capsys.readouterr().out.startswith("ko\tweak\t수고하셨습니다\tprobe:")


def test_user_phrase_file(examples, tmp_path, capsys):
    mine = tmp_path / "mine.tsv"
    mine.write_text("# my list\nlike and subscribe\nbrought to you by acme\tstrict\n", encoding="utf-8")
    assert main(["phrases", "--phrases", str(mine), "--no-builtin"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines == ["en\tweak\tlike and subscribe\tuser", "en\tstrict\tbrought to you by acme\tuser"]


def test_errors_are_one_line_with_a_fix(examples, tmp_path, capsys):
    srt = str(examples / "mixed_en.srt")
    assert main(["clean", srt]) == 2
    assert "-o FILE" in capsys.readouterr().err
    assert main(["clean", srt, "-o", srt]) == 2
    assert "never overwrites" in capsys.readouterr().err
    bad = tmp_path / "x.txt"
    bad.write_text("hello")
    assert main(["clean", str(bad), "--dry-run"]) == 2
    assert "unrecognised input" in capsys.readouterr().err
    assert main(["clean", str(tmp_path / "missing.srt"), "--dry-run"]) == 2
    assert main(["check", srt, "--fail-over", "3"]) == 2
    bad_phrases = tmp_path / "p.tsv"
    bad_phrases.write_text("hello\tmaybe\n")
    assert main(["phrases", "--phrases", str(bad_phrases)]) == 2
    assert "strict" in capsys.readouterr().err


def test_python_dash_m_entry_point(examples):
    proc = subprocess.run(
        [sys.executable, "-m", "whisper_scrub", "check", str(examples / "mixed_ko.srt"), "--fail-over", "0.3"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 1
    assert "flagged 8/10 (0.80)" in proc.stdout
