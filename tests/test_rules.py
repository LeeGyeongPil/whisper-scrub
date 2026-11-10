"""Rule boundaries, configuration validation and edge cases."""

from __future__ import annotations

import pytest

from whisper_scrub import Config, ConfigError, PhraseBook, scrub
from whisper_scrub.normalize import detect_lang, normalize


def S(text, start, end, **meta):
    return {"start": start, "end": end, "text": text, **meta}


def test_normalize_and_language_guess():
    assert normalize(" Thank-you!! ") == "thank you"
    assert normalize("I'm") == "i m"  # same convention as the BoH list
    assert normalize("ご視聴 ありがとう ございました。") == "ご視聴ありがとうございました"
    assert normalize("<i>Hi</i>") == "hi"
    assert [detect_lang(t) for t in ("수고", "ありがとう", "谢谢", "you", "123")] == ["ko", "ja", "zh", "en", ""]


def test_repeat_run_needs_three_in_a_row():
    two = scrub([S("Yes.", 0, 1), S("Yes.", 1, 2), S("No way.", 2, 3)])
    assert [v.action for v in two.verdicts] == ["keep"] * 3
    three = scrub([S("Yes.", 0, 1), S("yes", 1, 2), S("YES!", 2, 3)])
    assert [v.action for v in three.verdicts] == ["keep", "remove", "remove"]


def test_repeat_run_ignores_far_apart_copies():
    segs = [S("Okay.", 0, 1), S("Okay.", 40, 41), S("Okay.", 80, 81)]
    assert [v.action for v in scrub(segs).verdicts] == ["keep"] * 3


def test_repeat_loop_inside_one_segment_is_suspect():
    word_loop = scrub([S("so we go so we go so we go so we go", 0, 5)])
    assert word_loop.verdicts[0].action == "suspect"
    assert word_loop.verdicts[0].rules[0].rule_id == "repeat.loop"
    char_loop = scrub([S("이 말은 이 말은 이 말은 이 말은", 0, 5)])
    assert char_loop.verdicts[0].rules[0].rule_id == "repeat.loop"
    assert scrub([S("we go and we go again and then we go", 0, 5)]).verdicts[0].action == "keep"


def test_silent_window_needs_both_signals():
    both = scrub([S("Some made up words here.", 0, 3, no_speech_prob=0.85, avg_logprob=-1.2)])
    assert both.verdicts[0].action == "remove" and both.verdicts[0].confidence == "high"
    only_prob = scrub([S("Some made up words here.", 0, 3, no_speech_prob=0.85, avg_logprob=-0.5)])
    assert only_prob.verdicts[0].action == "suspect"  # meta.no_speech alone: look, do not delete


def test_beyond_end_remove_and_suspect():
    segs = [S("Hello there.", 0, 2), S("Ghost text.", 80, 82), S("Almost fine.", 70, 72.4), S("Overrun.", 70, 73.0)]
    result = scrub(segs, audio_duration=72.0)
    assert [v.action for v in result.verdicts] == ["keep", "remove", "keep", "suspect"]
    assert result.verdicts[1].rules[0].rule_id == "audio.beyond_end"


def test_isolated_does_not_count_when_neighbours_are_close():
    segs = [S("Hi.", 0, 1), S("Thank you.", 1.5, 3.0), S("Bye.", 3.5, 4)]
    assert scrub(segs).verdicts[1].action == "suspect"
    assert [h.rule_id for h in scrub(segs).verdicts[1].rules] == ["phrase.weak"]


def test_strict_phrase_removes_alone():
    r = scrub([S("Subtitles by the Amara.org community", 0, 3)])
    assert r.verdicts[0].action == "remove" and r.verdicts[0].rules[0].rule_id == "phrase.strict"


def test_user_phrases_layered_on_builtin(tmp_path):
    f = tmp_path / "mine.tsv"
    f.write_text("brought to you by acme\tstrict\n", encoding="utf-8")
    cfg = Config(phrases=PhraseBook.builtin().merge(PhraseBook.from_file(f)))
    assert scrub([S("Brought to you by ACME.", 0, 3)], config=cfg).verdicts[0].action == "remove"
    assert scrub([S("Thank you.", 0, 2, no_speech_prob=0.9)], config=cfg).verdicts[0].action == "remove"
    assert scrub([S("Brought to you by ACME.", 0, 3)]).verdicts[0].action == "keep"  # not in the default book


def test_forced_language():
    cfg = Config(lang="ko")
    assert scrub([S("수고하셨습니다", 0, 2, no_speech_prob=0.9)], config=cfg).verdicts[0].action == "remove"


def test_empty_and_degenerate_input():
    assert scrub([]).flagged_ratio == 0.0
    assert scrub([S("", 0, 0)]).verdicts[0].action == "keep"
    assert scrub([S("   ", 5, 4)]).verdicts[0].action == "keep"


def test_generator_input_and_result_views():
    result = scrub(s for s in [S("Hello.", 0, 1), S("You", 30, 32, no_speech_prob=0.98)])
    assert [s.text for s in result.removed] == ["You"]
    assert [s.text for s in result.kept] == ["Hello."]
    assert result.suspects == []


@pytest.mark.parametrize(
    "kwargs,message",
    [
        ({"no_speech_threshold": 1.5}, "between 0 and 1"),
        ({"silent_logprob": 0.5}, "log probability"),
        ({"repeat_min": 1}, "at least 2"),
        ({"phantom_min_seconds": -1}, "negative"),
        ({"lang": "xx"}, "one of ko, en, ja, zh"),
    ],
)
def test_config_validation_messages(kwargs, message):
    with pytest.raises(ConfigError, match=message):
        Config(**kwargs)


def test_invalid_duration():
    with pytest.raises(ConfigError, match="audio_duration"):
        scrub([S("a", 0, 1)], audio_duration=0)


def test_bad_segment_input_says_what_is_missing():
    from whisper_scrub import UnknownFormatError

    with pytest.raises(UnknownFormatError, match="start, end and text"):
        scrub([{"text": "no times"}])
