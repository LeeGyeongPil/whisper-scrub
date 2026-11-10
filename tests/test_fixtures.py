"""Lessons reproduced from recorded real faster-whisper tiny output (AC-1, AC-2, AC-3)."""

from __future__ import annotations

import json

import pytest

from whisper_scrub import Config, load, scrub


def whisper_would_skip(seg) -> bool:
    """Whisper's own skip rule for silent windows: no_speech > 0.6 AND avg_logprob < -1.0."""
    return seg.no_speech_prob > 0.6 and seg.avg_logprob < -1.0


def test_mixed_en_you_escapes_whisper_rule_and_is_removed(examples):
    doc = load(examples / "mixed_en.json")
    you = doc.segments[1]
    assert you.text == " You"
    assert (you.no_speech_prob, you.avg_logprob) == (0.985, -0.942)
    # The lesson: Whisper's own rule does not skip it, because -0.942 is not below -1.0.
    assert whisper_would_skip(you) is False

    result = scrub(doc)
    assert [s.index for s in result.removed] == [2]
    assert len(result.kept) == 2 and not result.suspects
    verdict = result.verdicts[1]
    assert verdict.action == "remove" and verdict.confidence == "medium"
    assert {h.rule_id for h in verdict.rules} == {"phrase.weak", "meta.no_speech"}
    assert [result.verdicts[0].action, result.verdicts[2].action] == ["keep", "keep"]


def test_mixed_ko_loop_collapsed_and_broken_tail_flagged(examples):
    doc = load(examples / "mixed_ko.srt")
    result = scrub(doc, audio_duration=72.0)
    assert len(result.removed) == 7
    assert len(result.suspects) == 1
    assert [s.index for s in result.kept if s not in result.suspects] == [1, 2]
    assert all([h.rule_id for h in v.rules] == ["repeat.run"] for v in result.verdicts[2:9])
    tail = result.verdicts[9]
    assert tail.action == "suspect"
    assert {h.rule_id for h in tail.rules} == {"text.broken", "audio.beyond_end"}
    assert len(result.repeat_runs) == 1 and len(result.repeat_runs[0]) == 8


def test_mixed_ko_json_report_records_shared_meta(examples):
    doc = load(examples / "mixed_ko.json")
    assert doc.duration == 72.0  # picked up from the JSON, no argument needed
    result = scrub(doc)
    data = result.report_json()
    (group,) = data["shared_meta_groups"]
    assert group["segments"] == list(range(1, 10))
    assert (group["no_speech_prob"], group["avg_logprob"], group["compression_ratio"]) == (0.093, -1.475, 2.222)
    md = result.report_markdown()
    assert "9 segments" in md and "same meta values" in md and "-1.475" in md
    # meta alone could not separate them: none of the 9 reaches a meta rule
    assert not any(h.rule_id.startswith("meta.") for v in result.verdicts for h in v.rules)
    assert len(result.removed) == 7 and len(result.suspects) == 1


PHRASE_RUNS = {
    "raw_silence30_ko": "수고하셨습니다.",
    "raw_noise30_ko": "수고하셨습니다.",
    "raw_tones30_ko": "수고하셨습니다.",
    "raw_silence30_ja": "ご視聴ありがとうございました",
    "raw_noise30_ja": "ご視聴ありがとうございます。",
    "raw_silence30_en": " you",
    "raw_noise30_en": " You",
    "raw_tones30_en": " You",
}


@pytest.mark.parametrize("name", sorted(PHRASE_RUNS))
def test_raw_runs_phrases_removed(raw_runs, name):
    result = scrub(raw_runs[name]["segments"])
    hits = [(s, v) for s, v in zip(result.segments, result.verdicts) if s.text.strip() == PHRASE_RUNS[name].strip()]
    assert len(hits) == 1
    _, verdict = hits[0]
    assert verdict.action == "remove", (name, verdict)
    assert any(h.rule_id == "phrase.weak" for h in verdict.rules)


def test_raw_runs_cover_exactly_the_eight_phrase_runs(raw_runs):
    counts = {lang: len([n for n in PHRASE_RUNS if n.endswith("_" + lang)]) for lang in ("ko", "ja", "en")}
    assert counts == {"ko": 3, "ja": 2, "en": 3}
    assert set(PHRASE_RUNS) <= set(raw_runs)


def test_raw_zh_junk_removed_by_silent_window(raw_runs):
    result = scrub(raw_runs["raw_noise30_zh"]["segments"])
    assert [v.action for v in result.verdicts] == ["remove"] * 4


# --- false-positive protection (real speech must survive) -----------------

def seg(text, no_speech=None, logprob=None, start=0.0, end=2.0):
    d = {"start": start, "end": end, "text": text}
    if no_speech is not None:
        d["no_speech_prob"] = no_speech
    if logprob is not None:
        d["avg_logprob"] = logprob
    return d


def action(text, speech=None, **kw):
    return scrub([seg(text, **kw)], speech=speech).verdicts[0].action


def test_real_speech_not_eaten():
    # same phrase, but Whisper and the audio both say someone is talking
    assert action("수고하셨습니다.", speech=[(0.0, 2.0)], no_speech=0.05, logprob=-0.2) == "keep"
    assert action(" You", speech=[(0.0, 2.0)], no_speech=0.05) == "keep"
    # a longer real sentence that merely contains a dictionary phrase is never matched
    sentence = "오늘 발표를 들어 주셔서 감사합니다 그리고 수고하셨습니다 여러분"
    assert action(sentence) == "keep"
    assert action(sentence, no_speech=0.7) == "suspect"  # flagged for a look, not deleted
    # no meta, no audio, no partner signal: stands alone -> suspect, never remove
    assert action("Thank you.") == "suspect"


def test_substring_mode_still_needs_a_second_signal():
    cfg = Config(substring=True)
    text = "그래서 오늘 회의 수고하셨습니다 내일 봐요"
    assert scrub([seg(text)], config=cfg).verdicts[0].action == "suspect"
    assert scrub([seg(text, no_speech=0.9)], config=cfg).verdicts[0].action == "remove"
    assert scrub([seg(text, no_speech=0.9)]).verdicts[0].action == "suspect"  # off by default


# (text, no_speech_prob, speech overlap: None=no audio / True=speaking / False=silent, expected)
PHRASE_TABLE = [
    # positives: dictionary phrase plus a second signal
    ("Thanks for watching!", 0.90, None, "remove"),
    ("Thank you for watching.", 0.70, None, "remove"),
    ("Subtitles by the Amara.org community", None, None, "remove"),  # strict: alone is enough
    ("ご視聴ありがとうございました。", 0.80, None, "remove"),
    ("수고하셨습니다", 0.97, None, "remove"),
    ("Thank you.", None, False, "remove"),  # the audio has no speech there
    # weak phrase, no second signal -> only suspect
    ("Thank you.", None, None, "suspect"),
    ("thanks for watching", None, None, "suspect"),
    # weak phrase with evidence of speech -> keep
    ("Thank you.", 0.05, None, "keep"),
    ("Thank you.", None, True, "keep"),
    # negatives: ordinary sentences
    ("Thank you for the question, let me answer that.", 0.02, None, "keep"),
    ("I want to thank you all for coming today.", None, None, "keep"),
    ("Do you watch the news every day?", None, None, "keep"),
    ("그럼 오늘 수업은 여기까지 하겠습니다.", 0.02, None, "keep"),
    ("ありがとうございます、よろしくお願いします。", 0.02, None, "keep"),
    ("谢谢大家今天来参加会议", 0.02, None, "keep"),
]


@pytest.mark.parametrize("text,no_speech,speech,expected", PHRASE_TABLE)
def test_phrase_regression_table(text, no_speech, speech, expected):
    spans = None
    if speech is True:
        spans = [(0.0, 2.0)]
    elif speech is False:
        spans = [(10.0, 12.0)]  # speech exists, but elsewhere
    assert action(text, speech=spans, no_speech=no_speech) == expected, (text, no_speech, speech)


def test_report_json_roundtrips():
    result = scrub([seg("Thank you.", no_speech=0.9)])
    data = json.loads(json.dumps(result.report_json()))
    assert data["report_version"] == 1
    assert data["segments"][0]["rules"][0]["rule_id"] == "phrase.weak"
