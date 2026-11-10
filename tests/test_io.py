"""Input format detection (AC-5)."""

from __future__ import annotations

import json
from collections import namedtuple

import pytest

from whisper_scrub import UnknownFormatError, load, loads, scrub
from whisper_scrub.io import segments_from_items

EXPECTED = [(0.0, 2.5, "hello there"), (3.0, 4.2, "general kenobi")]


def triples(segments):
    return [(s.start, s.end, s.text.strip()) for s in segments]


SRT = "1\n00:00:00,000 --> 00:00:02,500\nhello there\n\n2\n00:00:03,000 --> 00:00:04,200\ngeneral kenobi\n"
VTT = "WEBVTT\n\n00:00:00.000 --> 00:00:02.500\nhello there\n\n00:00:03.000 --> 00:00:04.200\ngeneral kenobi\n"
OPENAI_WHISPER = json.dumps(
    {
        "text": " hello there general kenobi",
        "language": "en",
        "segments": [
            {"id": 0, "start": 0.0, "end": 2.5, "text": " hello there", "no_speech_prob": 0.1},
            {"id": 1, "start": 3.0, "end": 4.2, "text": " general kenobi", "no_speech_prob": 0.1},
        ],
    }
)
VERBOSE_JSON = json.dumps(
    {
        "task": "transcribe",
        "language": "english",
        "duration": 5.0,
        "text": "hello there general kenobi",
        "segments": [
            {"id": 0, "start": 0.0, "end": 2.5, "text": "hello there"},
            {"id": 1, "start": 3.0, "end": 4.2, "text": "general kenobi"},
        ],
    }
)
FW_DICTS = json.dumps(
    [
        {"start": 0.0, "end": 2.5, "text": " hello there", "avg_logprob": -0.3},
        {"start": 3.0, "end": 4.2, "text": " general kenobi", "avg_logprob": -0.3},
    ]
)
WHISPER_CPP = json.dumps(
    {
        "transcription": [
            {"offsets": {"from": 0, "to": 2500}, "text": " hello there"},
            {"offsets": {"from": 3000, "to": 4200}, "text": " general kenobi"},
        ]
    }
)


def test_detect_all_formats():
    FWSegment = namedtuple(
        "Segment", "id seek start end text no_speech_prob avg_logprob compression_ratio temperature"
    )
    fw_objects = [
        FWSegment(1, 0, 0.0, 2.5, " hello there", 0.1, -0.3, 1.0, 0.0),
        FWSegment(2, 0, 3.0, 4.2, " general kenobi", 0.1, -0.3, 1.0, 0.0),
    ]
    docs = {
        "openai-whisper": loads(OPENAI_WHISPER).segments,
        "verbose_json": loads(VERBOSE_JSON).segments,
        "faster-whisper dicts": loads(FW_DICTS).segments,
        "faster-whisper objects": segments_from_items(fw_objects),
        "whisper.cpp": loads(WHISPER_CPP).segments,
        "srt": loads(SRT).segments,
        "vtt": loads(VTT).segments,
    }
    for name, segs in docs.items():
        assert triples(segs) == EXPECTED, name
    assert loads(OPENAI_WHISPER).format == "whisper-json"
    assert loads(WHISPER_CPP).format == "whisper-cpp-json"
    assert loads(SRT).format == "srt" and loads(VTT).format == "vtt"
    # meta fields come through where the format has them
    assert docs["faster-whisper objects"][0].no_speech_prob == 0.1
    assert docs["srt"][0].no_speech_prob is None
    assert loads(VERBOSE_JSON).duration == 5.0
    # scrub() takes the objects directly, no files needed
    assert scrub(fw_objects).verdicts[0].action == "keep"


@pytest.mark.parametrize(
    "bad",
    ["", "hello world", "{}", '{"segments": "nope"}', "[1, 2, 3]", "{not json", '[{"start": 0}]', "1\n\nfoo\n"],
)
def test_unknown_format_raises(bad):
    with pytest.raises(UnknownFormatError):
        loads(bad)


def test_unknown_format_message_tells_what_is_expected():
    with pytest.raises(UnknownFormatError, match="SRT or WebVTT"):
        loads("just some text")


def test_non_utf8_file_gives_a_fix(tmp_path):
    p = tmp_path / "x.srt"
    p.write_bytes("1\n00:00:00,000 --> 00:00:01,000\n안녕\n".encode("cp949"))
    with pytest.raises(UnknownFormatError, match="iconv"):
        load(p)
