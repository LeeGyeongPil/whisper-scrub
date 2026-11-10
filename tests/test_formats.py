"""SRT / VTT / JSON rewriting keeps everything it did not remove (AC-4)."""

from __future__ import annotations

import json

import pytest

from whisper_scrub import ConfigError, loads, scrub_file
from whisper_scrub.io.document import split_blocks


def clean_to(tmp_path, src, name, **kw):
    out = tmp_path / name
    result = scrub_file(src, out, **kw)
    return result, out.read_bytes()


def test_srt_untouched_blocks_identical(examples, tmp_path):
    src = examples / "mixed_ko.srt"
    original = src.read_bytes()
    result, out = clean_to(tmp_path, src, "out.srt", audio_duration=72.0)
    assert len(result.removed) == 7
    _, blocks, seps = split_blocks(original.decode("utf-8"))
    expected = (blocks[0] + seps[0] + blocks[1] + seps[1] + blocks[9] + seps[-1]).encode("utf-8")
    assert out == expected
    # every kept block, including its timecode line, is a byte-for-byte slice of the input
    for i in (0, 1, 9):
        assert blocks[i].encode("utf-8") in out
    assert src.read_bytes() == original  # input untouched


def test_srt_renumber(examples, tmp_path):
    src = examples / "mixed_ko.srt"
    _, kept = clean_to(tmp_path, src, "keep.srt")
    assert [b.splitlines()[0] for b in kept.decode().strip().split("\n\n")] == ["1", "2", "10"]
    _, renum = clean_to(tmp_path, src, "renum.srt", renumber=True)
    blocks = renum.decode().strip().split("\n\n")
    assert [b.splitlines()[0] for b in blocks] == ["1", "2", "3"]
    # only the number changed; the timecode of the old cue 10 is intact
    assert blocks[2].splitlines()[1] == "00:01:00,000 --> 00:01:19,100"


def test_srt_bom_crlf_multiline_and_korean_survive(tmp_path):
    text = (
        "1\r\n00:00:00,000 --> 00:00:02,000\r\n안녕하세요\r\n두 번째 줄\r\n\r\n"
        "2\r\n00:00:30,000 --> 00:00:32,000\r\nYou\r\n\r\n"
        "3\r\n00:01:00,500 --> 00:01:02,250\r\n<i>마지막</i>\r\n"
    )
    src = tmp_path / "in.srt"
    src.write_bytes(b"\xef\xbb\xbf" + text.encode("utf-8"))
    result, out = clean_to(tmp_path, src, "out.srt", speech=[(0.0, 2.0), (60.0, 63.0)])
    assert [s.index for s in result.removed] == [2]
    expected = (
        "1\r\n00:00:00,000 --> 00:00:02,000\r\n안녕하세요\r\n두 번째 줄\r\n\r\n"
        "3\r\n00:01:00,500 --> 00:01:02,250\r\n<i>마지막</i>\r\n"
    )
    assert out == b"\xef\xbb\xbf" + expected.encode("utf-8")  # BOM, CRLF, tags, timecodes intact


def test_srt_without_bom_stays_without_bom(examples, tmp_path):
    _, out = clean_to(tmp_path, examples / "mixed_en.srt", "o.srt", speech=[(0, 11), (60, 72)])
    assert not out.startswith(b"\xef\xbb\xbf")


def test_srt_removing_the_last_cue_keeps_trailing_newline(tmp_path):
    src = tmp_path / "in.srt"
    src.write_text(
        "1\n00:00:00,000 --> 00:00:02,000\nHello there\n\n2\n00:00:30,000 --> 00:00:32,000\nYou\n",
        encoding="utf-8",
    )
    _, out = clean_to(tmp_path, src, "out.srt", speech=[(0.0, 2.0)])
    assert out == b"1\n00:00:00,000 --> 00:00:02,000\nHello there\n"


VTT = (
    "WEBVTT - lecture\n\n"
    "STYLE\n::cue { color: yellow }\n\n"
    "NOTE made by hand\nsecond note line\n\n"
    "intro\n00:00:00.000 --> 00:00:02.000 align:start\nHello everyone, welcome.\n\n"
    "noise\n00:00:30.000 --> 00:00:32.000\nThank you.\n\n"
    "00:01:00.000 --> 00:01:02.000\nSee you next week.\n"
)


def test_vtt_header_note_style_kept(tmp_path):
    src = tmp_path / "in.vtt"
    src.write_text(VTT, encoding="utf-8")
    result, out = clean_to(tmp_path, src, "out.vtt", speech=[(0.0, 2.0), (60.0, 62.0)])
    assert [s.index for s in result.removed] == [2]
    text = out.decode("utf-8")
    assert text.startswith(
        "WEBVTT - lecture\n\nSTYLE\n::cue { color: yellow }\n\nNOTE made by hand\nsecond note line\n\n"
    )
    assert "intro\n00:00:00.000 --> 00:00:02.000 align:start\nHello everyone, welcome." in text
    assert "noise" not in text and "Thank you." not in text
    assert text.endswith("00:01:00.000 --> 00:01:02.000\nSee you next week.\n")


def test_outputs_parse_with_reference_libs(examples, tmp_path):
    srt = pytest.importorskip("srt")
    webvtt = pytest.importorskip("webvtt")
    _, out = clean_to(tmp_path, examples / "mixed_ko.srt", "o.srt")
    assert [s.index for s in srt.parse(out.decode("utf-8"))] == [1, 2, 10]
    _, renum = clean_to(tmp_path, examples / "mixed_ko.srt", "r.srt", renumber=True)
    assert [s.index for s in srt.parse(renum.decode("utf-8"))] == [1, 2, 3]

    src = tmp_path / "in.vtt"
    src.write_text(VTT, encoding="utf-8")
    clean_to(tmp_path, src, "o.vtt", speech=[(0.0, 2.0), (60.0, 62.0)])
    captions = webvtt.read(str(tmp_path / "o.vtt"))
    assert [c.text for c in captions] == ["Hello everyone, welcome.", "See you next week."]


def test_json_extra_keys_kept(examples, tmp_path):
    src = examples / "mixed_en.json"
    original = json.loads(src.read_text(encoding="utf-8"))
    result, out = clean_to(tmp_path, src, "out.json")
    assert [s.index for s in result.removed] == [2]
    data = json.loads(out.decode("utf-8"))
    assert data["language"] == "en" and data["duration"] == 72.0
    assert [s["id"] for s in data["segments"]] == [1, 3]
    assert data["segments"][0] == original["segments"][0]  # every key of a kept segment is intact
    assert data["segments"][1] == original["segments"][2]


def test_json_top_level_text_follows_segments(tmp_path):
    doc = {
        "text": " Hello there. You",
        "language": "en",
        "segments": [
            {"id": 0, "start": 0.0, "end": 2.0, "text": " Hello there.", "no_speech_prob": 0.01},
            {"id": 1, "start": 30.0, "end": 32.0, "text": " You", "no_speech_prob": 0.98},
        ],
    }
    src = tmp_path / "in.json"
    src.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    _, out = clean_to(tmp_path, src, "out.json")
    data = json.loads(out)
    assert data["text"] == " Hello there."
    assert len(data["segments"]) == 1


def test_whispercpp_json_is_rewritten(tmp_path):
    cpp = {
        "systeminfo": "x",
        "transcription": [
            {"timestamps": {"from": "00:00:00,000"}, "offsets": {"from": 0, "to": 2000}, "text": " Hello there."},
            {"timestamps": {"from": "00:00:30,000"}, "offsets": {"from": 30000, "to": 32000}, "text": " You"},
        ],
    }
    src = tmp_path / "in.json"
    src.write_text(json.dumps(cpp), encoding="utf-8")
    _, out = clean_to(tmp_path, src, "out.json", speech=[(0.0, 2.0)])
    data = json.loads(out)
    assert data["systeminfo"] == "x" and len(data["transcription"]) == 1
    assert data["transcription"][0]["offsets"] == {"from": 0, "to": 2000}


def test_scrub_file_refuses_to_overwrite_input(examples, tmp_path):
    src = tmp_path / "in.srt"
    src.write_bytes((examples / "mixed_en.srt").read_bytes())
    with pytest.raises(ConfigError, match="never overwrites"):
        scrub_file(src, src)
    with pytest.raises(ConfigError, match="dry_run"):
        scrub_file(src)


def test_scrub_file_writes_markdown_and_json_reports(examples, tmp_path):
    scrub_file(examples / "mixed_ko.srt", dry_run=True, report=tmp_path / "r.md")
    scrub_file(examples / "mixed_ko.srt", dry_run=True, report=tmp_path / "r.json")
    assert (tmp_path / "r.md").read_text(encoding="utf-8").startswith("# whisper-scrub report")
    assert json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))["summary"]["removed"] == 7


def test_split_blocks_is_lossless():
    for text in ["", "a\n", "a\n\nb", "\n\na\r\n\r\nb\r\n\r\n", "a\n \t\nb\n\n\n"]:
        lead, blocks, seps = split_blocks(text)
        assert lead + "".join(b + s for b, s in zip(blocks, seps)) == text


def test_loads_keeps_segment_text_without_markup():
    doc = loads("1\n00:00:00,000 --> 00:00:01,000\n<i>hi</i>\n")
    assert doc.segments[0].text == "hi"
