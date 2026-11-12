"""Display language: message tables, precedence, CLI output in Korean, and unchanged machine output."""

from __future__ import annotations

import json
import re
import string

import pytest

from whisper_scrub import i18n
from whisper_scrub.cli import main
from whisper_scrub.errors import ConfigError, ScrubError
from whisper_scrub.i18n import MESSAGES, fix_particles, resolve_lang, translate
from whisper_scrub.rules import SPEECH_GUARD_WARNING
from whisper_scrub.vad import NUMPY_HINT

LOOP_SRT = "examples/mixed_ko.srt"


def _fields(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def test_message_tables_have_identical_keys_and_placeholders():
    assert set(MESSAGES["en"]) == set(MESSAGES["ko"])
    for key, en in MESSAGES["en"].items():
        assert _fields(en) == _fields(MESSAGES["ko"][key]), key


def test_english_constants_come_from_the_table():
    assert SPEECH_GUARD_WARNING == MESSAGES["en"]["warn.speech_guard"]
    assert NUMPY_HINT == MESSAGES["en"]["err.vad.numpy"]


@pytest.mark.parametrize(
    ("argv_value", "env", "expected"),
    [
        ("ko", {"WHISPER_SCRUB_LANG": "en"}, "ko"),  # --lang beats everything
        ("en", {"WHISPER_SCRUB_LANG": "ko"}, "en"),
        (None, {"WHISPER_SCRUB_LANG": "ko", "LC_ALL": "en_US.UTF-8"}, "ko"),
        (None, {"LC_ALL": "ko_KR.UTF-8", "LC_MESSAGES": "en_US", "LANG": "en_US"}, "ko"),
        (None, {"LC_MESSAGES": "ko_KR.UTF-8", "LANG": "en_US.UTF-8"}, "ko"),
        (None, {"LC_ALL": "en_US.UTF-8", "LC_MESSAGES": "ko_KR", "LANG": "ko_KR"}, "en"),
        (None, {"LANG": "ko_KR.UTF-8"}, "ko"),
        (None, {"LANG": "ja_JP.UTF-8"}, "en"),
        (None, {"LC_ALL": "", "LANG": "ko_KR.UTF-8"}, "ko"),  # empty values are skipped
        (None, {}, "en"),
    ],
)
def test_language_precedence(argv_value, env, expected):
    assert resolve_lang(argv_value, env) == expected


@pytest.mark.parametrize(
    ("template", "expected"),
    [
        ("{x}은(는)", "책은"),
        ("{x}은(는)", "나는"),
        ("{x}이(가)", "책이"),
        ("{x}이(가)", "나가"),
        ("{x}을(를)", "책을"),
        ("{x}을(를)", "나를"),
        ("{x}과(와)", "책과"),
        ("{x}과(와)", "나와"),
        ("{x}으로(로)", "책으로"),
        ("{x}으로(로)", "나로"),
        ("{x}으로(로)", "물로"),  # a final ㄹ takes 로
        ("{x}은(는)", "min은"),
        ("{x}은(는)", "repeat_max_gap는"),
        ("{x}은(는)", "3은"),
        ("{x}은(는)", "2는"),
    ],
)
def test_particles_follow_the_sound(template, expected):
    word = re.sub(r"(은|는|이|가|을|를|과|와|으로|로)$", "", expected)
    assert fix_particles(template.replace("{x}", word)) == expected


def test_particle_after_quote_looks_through_it():
    assert fix_particles("'책'을(를) 봅니다") == "'책'을 봅니다"
    assert fix_particles("'나'을(를) 봅니다") == "'나'를 봅니다"


def test_translate_unknown_language_falls_back_to_english():
    assert translate("fr", "cmd.clean") == MESSAGES["en"]["cmd.clean"]


def test_error_keeps_english_message_and_carries_code():
    with pytest.raises(ConfigError) as info:
        from whisper_scrub import Config

        Config(repeat_min=1)
    exc = info.value
    assert isinstance(exc, ValueError) and isinstance(exc, ScrubError)
    assert str(exc) == "repeat_min must be at least 2, got 1"
    assert exc.code == "err.config.repeat_min" and exc.params == {"value": 1}
    assert ScrubError("plain").code is None


def test_cli_korean_summary_and_report(capsys, examples):
    assert main(["--lang", "ko", "clean", LOOP_SRT, "--dry-run", "--report", "-"]) == 0
    out, err = capsys.readouterr()
    assert "삭제 7개, 의심 1개, 유지 2개" in err
    assert "시험 실행이라 아무것도 쓰지 않았습니다" in err
    assert out.startswith("# whisper-scrub 보고서")
    assert "| # | 시간(초) | 동작 | 확신도 | 규칙 | 텍스트 |" in out
    assert "## 근거" in out and "## 기준값" in out
    assert "removed" not in err and "dry run" not in err


def test_cli_english_when_env_says_en(capsys, monkeypatch):
    monkeypatch.setenv("LANG", "ko_KR.UTF-8")  # WHISPER_SCRUB_LANG=en (conftest) still wins
    assert main(["clean", LOOP_SRT, "--dry-run"]) == 0
    assert "removed 7, suspect 1, kept 2 of 10 segments (dry run, nothing written)" in capsys.readouterr().err


def test_cli_picks_korean_from_lang_env(capsys, monkeypatch):
    monkeypatch.delenv("WHISPER_SCRUB_LANG")
    monkeypatch.setenv("LC_ALL", "ko_KR.UTF-8")
    assert main(["clean", LOOP_SRT, "--dry-run"]) == 0
    assert "삭제 7개" in capsys.readouterr().err


def test_flag_beats_env(capsys, monkeypatch):
    monkeypatch.setenv("WHISPER_SCRUB_LANG", "ko")
    assert main(["--lang=en", "clean", LOOP_SRT, "--dry-run"]) == 0
    assert "removed 7" in capsys.readouterr().err


def test_dictionary_lang_and_display_lang_coexist(capsys):
    # display language ko; dictionary language ja (forces the Japanese phrase list)
    assert main(["--lang", "ko", "check", LOOP_SRT, "--lang", "ja"]) == 0
    ko_out = capsys.readouterr().out
    assert "의심" in ko_out
    assert main(["--lang", "en", "check", LOOP_SRT, "--lang", "ja"]) == 0
    en_out = capsys.readouterr().out
    assert "flagged" in en_out
    # the dictionary language really reached Config: the baseline lines of the report say lang=ja
    assert main(["--lang", "en", "clean", LOOP_SRT, "--lang", "ja", "--dry-run", "--report", "-"]) == 0
    assert "lang=ja" in capsys.readouterr().out
    assert main(["--lang", "ko", "clean", LOOP_SRT, "--lang", "ja", "--dry-run", "--report", "-"]) == 0
    assert "lang=ja" in capsys.readouterr().out
    assert main(["--lang", "en", "phrases", "--lang", "ja"]) == 0
    assert capsys.readouterr().out.splitlines()[0].startswith("ja\t")


def test_korean_errors_use_code_and_params(capsys):
    assert main(["--lang", "ko", "clean", LOOP_SRT]) == 2
    assert "오류: clean 은 새 파일을 씁니다" in capsys.readouterr().err
    assert main(["--lang", "ko", "check", LOOP_SRT, "--fail-over", "2"]) == 2
    assert "0과 1 사이의 비율" in capsys.readouterr().err
    assert main(["--lang", "ko", "check", "no-such-file.srt"]) == 2
    err = capsys.readouterr().err
    assert "no-such-file.srt 파일을 읽을 수 없습니다" in err
    assert main(["--lang", "en", "check", "no-such-file.srt"]) == 2
    assert "error: cannot read no-such-file.srt:" in capsys.readouterr().err


def test_korean_library_error_from_deep_call(capsys, tmp_path):
    bad = tmp_path / "speech.json"
    bad.write_text('[{"start": 5, "end": 1}]', encoding="utf-8")
    assert main(["--lang", "ko", "clean", LOOP_SRT, "--speech", str(bad), "--dry-run"]) == 2
    assert "구간 1번의 끝이 시작보다 앞섭니다" in capsys.readouterr().err
    assert main(["clean", LOOP_SRT, "--speech", str(bad), "--dry-run"]) == 2
    assert "speech interval 1 ends before it starts" in capsys.readouterr().err


def test_speech_guard_warning_is_shown_in_korean_but_stored_in_english(capsys, tmp_path):
    speech = tmp_path / "speech.json"
    speech.write_text("[]", encoding="utf-8")
    assert main(["--lang", "ko", "clean", LOOP_SRT, "--speech", str(speech), "--dry-run", "--report", "-"]) == 0
    out, err = capsys.readouterr()
    assert "경고: 말소리 구간이 전사본을 거의 덮지 못합니다" in err
    assert "- 경고: 말소리 구간이" in out
    assert "speech intervals cover almost none" not in err


def test_argparse_chrome_in_korean(capsys):
    with pytest.raises(SystemExit) as info:
        main(["--lang", "ko", "check"])
    assert info.value.code == 2
    err = capsys.readouterr().err
    assert err.startswith("사용법:") and "오류: 다음 인자가 필요합니다: 입력파일" in err
    with pytest.raises(SystemExit):
        main(["--lang", "ko", "bogus"])
    assert "잘못된 선택지입니다" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        main(["--lang", "ko", "clean", "--help"])
    out = capsys.readouterr().out
    assert "사용법:" in out and "옵션:" in out and "위치 인자:" in out
    assert "usage" not in out and "positional" not in out and "options:" not in out


def test_help_explains_the_two_lang_options(capsys):
    with pytest.raises(SystemExit):
        main(["--lang", "en", "check", "--help"])
    out = " ".join(capsys.readouterr().out.split())
    assert "display language is the --lang before the subcommand" in out
    with pytest.raises(SystemExit):
        main(["--lang", "ko", "check", "--help"])
    out = " ".join(capsys.readouterr().out.split())
    assert "화면 언어는 하위 명령 앞의 --lang" in out


def test_version_output_is_not_translated(capsys):
    for lang in ("en", "ko"):
        with pytest.raises(SystemExit) as info:
            main(["--lang", lang, "--version"])
        assert info.value.code == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0] == out[1] and out[0].startswith("whisper-scrub ")


def test_machine_output_is_identical_in_both_languages(capsys, tmp_path):
    def run(lang: str, *args: str) -> tuple[int, str]:
        rc = main(["--lang", lang, *args])
        return rc, capsys.readouterr().out

    for args in (
        ("check", LOOP_SRT, "examples/mixed_en.srt", "--format", "json", "--fail-over", "0.2"),
        ("clean", LOOP_SRT, "--dry-run", "--report", "-", "--report-format", "json"),
        ("phrases", "--lang", "ko"),
    ):
        assert run("en", *args) == run("ko", *args)

    reports = {}
    for lang in ("en", "ko"):
        path = tmp_path / f"{lang}.json"
        assert main(["--lang", lang, "clean", LOOP_SRT, "--dry-run", "--report", str(path)]) == 0
        reports[lang] = path.read_bytes()
        capsys.readouterr()
    assert reports["en"] == reports["ko"]
    assert json.loads(reports["en"])["summary"]["removed"] == 7


def test_exit_codes_do_not_depend_on_language(capsys):
    for lang in ("en", "ko"):
        assert main(["--lang", lang, "check", LOOP_SRT, "--fail-over", "0.1"]) == 1
        assert main(["--lang", lang, "check", LOOP_SRT, "--fail-over", "0.99"]) == 0
        capsys.readouterr()


def test_library_markdown_is_english_by_default(examples):
    from whisper_scrub import scrub_file

    result = scrub_file(examples / "mixed_ko.srt", dry_run=True)
    assert result.report_markdown().startswith("# whisper-scrub report")
    assert result.report_markdown(lang="ko").startswith("# whisper-scrub 보고서")
    assert result.report_markdown() == result.report_markdown(lang="en")
    assert i18n.get_lang() == "en"


def test_summary_line_default_is_english_and_ko_is_opt_in():
    from whisper_scrub.check import CheckReport

    rep = CheckReport(10, 7, 1, 8, 0.8, 1, None, 0)
    assert rep.summary_line() == (
        "flagged 8/10 (0.80) | removed 7 | suspect 1 | repeat runs: 1 | speechless chars: n/a | fast segments: 0"
    )
    assert "표시 8/10" in rep.summary_line("ko")


def _only_korean(text: str, allowed: tuple[str, ...] = ()) -> None:
    """Fail if an English sentence fragment from argparse or the OS leaked into a Korean message."""
    for word in ("No such file", "Is a directory", "Expecting value", "float", "command", "inputs", "usage:", "error:"):
        assert word not in text, (word, text)


def test_korean_screen_has_no_english_leftovers(capsys, tmp_path):
    assert main(["--lang", "ko", "check", "nosuch.srt"]) == 2
    err = capsys.readouterr().err
    assert "nosuch.srt 파일을 읽을 수 없습니다: 파일이나 폴더가 없습니다" in err
    _only_korean(err)
    assert main(["--lang", "ko", "check", str(tmp_path)]) == 2
    err = capsys.readouterr().err
    assert "파일이 아니라 폴더입니다" in err
    _only_korean(err)
    empty = tmp_path / "speech.json"
    empty.write_text("", encoding="utf-8")
    assert main(["--lang", "ko", "clean", LOOP_SRT, "--speech", str(empty), "--dry-run"]) == 2
    err = capsys.readouterr().err
    assert "JSON 문법 오류, 1줄 1열" in err
    _only_korean(err)
    # English keeps the original wording
    assert main(["--lang", "en", "check", "nosuch.srt"]) == 2
    assert "No such file or directory" in capsys.readouterr().err


@pytest.mark.parametrize("argv, expect", [
    (["bogus"], "인자 명령: 잘못된 선택지입니다"),
    ([], "다음 인자가 필요합니다: 명령"),
    (["check"], "다음 인자가 필요합니다: 입력파일"),
    (["clean"], "다음 인자가 필요합니다: 입력파일"),
    (["check", "x.srt", "--fail-over", "abc"], "숫자 값이 올바르지 않습니다"),
    (["clean", "x.srt", "--repeat-min", "abc"], "정수 값이 올바르지 않습니다"),
])
def test_korean_argparse_errors_use_translated_names(capsys, argv, expect):
    with pytest.raises(SystemExit) as info:
        main(["--lang", "ko", *argv])
    assert info.value.code == 2
    err = capsys.readouterr().err
    assert expect in err
    error_line = err.strip().splitlines()[-1]
    _only_korean(error_line)


def test_invalid_ui_lang_falls_through_to_env(capsys, monkeypatch):
    monkeypatch.setenv("WHISPER_SCRUB_LANG", "ko")
    with pytest.raises(SystemExit):
        main(["--lang", "xx", "check", LOOP_SRT])
    assert "오류:" in capsys.readouterr().err
    assert resolve_lang("xx", {"LANG": "ko_KR.UTF-8"}) == "ko"
    assert resolve_lang("ko", {"LANG": "en_US.UTF-8"}) == "ko"
