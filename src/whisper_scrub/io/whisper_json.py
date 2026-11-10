"""Whisper-family JSON: openai-whisper, OpenAI verbose_json, faster-whisper
segment lists and whisper.cpp ``-oj`` output."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Collection, Iterable, Optional

from ..errors import UnknownFormatError
from ..model import Segment
from .document import Document

_INDENT = re.compile(r"\n([ \t]+)\S")


def _get(item: Any, name: str) -> Any:
    if isinstance(item, dict):
        return item.get(name)
    return getattr(item, name, None)


def _num(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def segments_from_items(items: Iterable[Any]) -> list[Segment]:
    """Turn dicts or Segment-like objects into :class:`Segment` objects.

    Accepts openai-whisper / verbose_json dicts, faster-whisper ``Segment``
    objects (anything with ``start``/``end``/``text`` attributes) and
    whisper.cpp entries (``offsets.from``/``offsets.to`` in milliseconds).
    """
    out: list[Segment] = []
    for pos, item in enumerate(items, 1):
        offsets = _get(item, "offsets")
        if offsets is not None:
            start, end = _num(_get(offsets, "from")), _num(_get(offsets, "to"))
            start = start / 1000 if start is not None else None
            end = end / 1000 if end is not None else None
        else:
            start, end = _num(_get(item, "start")), _num(_get(item, "end"))
        text = _get(item, "text")
        if start is None or end is None or not isinstance(text, str):
            raise UnknownFormatError(
                f"segment {pos} needs start, end and text (or whisper.cpp offsets.from/to); "
                f"got a {type(item).__name__} without them"
            )
        out.append(
            Segment(
                pos,
                start,
                end,
                text,
                _num(_get(item, "no_speech_prob")),
                _num(_get(item, "avg_logprob")),
                _num(_get(item, "compression_ratio")),
                _num(_get(item, "temperature")),
                raw=item,
            )
        )
    return out


def _detect_indent(raw: str) -> Any:
    m = _INDENT.search(raw)
    if not m:
        return None
    ws = m.group(1)
    return "\t" if "\t" in ws else len(ws)


@dataclass
class JsonDocument(Document):
    """JSON input. Rendering re-parses the original text and drops list entries,
    so every other key (including keys of the kept segments) is untouched."""

    _key: Optional[str] = None  # which key holds the segment list (None: top-level list)

    def render(self, removed: Collection[int] = (), renumber: bool = False) -> str:
        # `renumber` is ignored: JSON "id" values are left exactly as they were.
        drop = set(removed)
        doc = json.loads(self._raw)
        if self._key is None:
            doc = [e for p, e in enumerate(doc) if p not in drop]
        else:
            doc[self._key] = [e for p, e in enumerate(doc[self._key]) if p not in drop]
            before = [s.text for s in self.segments]
            after = [t for p, t in enumerate(before) if p not in drop]
            _refresh_text(doc, before, after)
        out = json.dumps(doc, ensure_ascii=False, indent=_detect_indent(self._raw))
        return out + ("\n" if self._raw.endswith("\n") else "")


def _refresh_text(doc: dict, before: list[str], after: list[str]) -> None:
    """Keep a top-level ``text`` field in sync when it is just the joined segments."""
    current = doc.get("text")
    if not isinstance(current, str):
        return
    joins = (lambda xs: "".join(xs), lambda xs: " ".join(x.strip() for x in xs))
    for join in joins:
        if current.strip() == join(before).strip():
            doc["text"] = join(after)
            return


def parse_json(raw: str, bom: bool = False, source: Optional[str] = None) -> JsonDocument:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise UnknownFormatError(f"input looks like JSON but does not parse: {exc}") from exc
    if isinstance(data, dict) and isinstance(data.get("segments"), list):
        fmt, key, items = "whisper-json", "segments", data["segments"]
    elif isinstance(data, dict) and isinstance(data.get("transcription"), list):
        fmt, key, items = "whisper-cpp-json", "transcription", data["transcription"]
    elif isinstance(data, list):
        fmt, key, items = "segment-list-json", None, data
    else:
        raise UnknownFormatError(
            "JSON must be an object with a 'segments' or 'transcription' list, "
            "or a list of segments with start/end/text"
        )
    duration = _num(data.get("duration")) if isinstance(data, dict) else None
    return JsonDocument(
        format=fmt,
        segments=segments_from_items(items),
        bom=bom,
        duration=duration,
        source=source,
        _raw=raw,
        _key=key,
    )
