"""Format detection by content (the file extension is only a hint)."""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

from ..errors import ScrubError, UnknownFormatError
from ..i18n import Reason, fail
from .document import Document, parse_timing, split_lines
from .srt import parse_srt
from .vtt import parse_vtt
from .whisper_json import parse_json

_BOM = "﻿"


def loads(text: str, source: Optional[str] = None) -> Document:
    """Parse text of any supported format. Raises :class:`UnknownFormatError`."""
    bom = text.startswith(_BOM)
    if bom:
        text = text[1:]
    head = text.lstrip()
    if head.startswith("WEBVTT"):
        return parse_vtt(text, bom, source)
    if head[:1] in ("{", "["):
        return parse_json(text, bom, source)
    # SRT: some line in the first few lines is a timing line
    for line in split_lines(head)[:4]:
        if parse_timing(line):
            doc = parse_srt(text, bom, source)
            if doc.segments:
                return doc
    raise fail(UnknownFormatError, "err.io.unknown")


def load(path: Union[str, Path]) -> Document:
    """Read a file (UTF-8, with or without BOM) and parse it."""
    p = Path(path)
    try:
        raw = p.read_bytes()
    except OSError as exc:
        raise fail(ScrubError, "err.io.read", path=p, reason=Reason(exc)) from exc
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise fail(UnknownFormatError, "err.io.utf8", path=p, byte=exc.start) from exc
    return loads(text, source=str(p))
