"""Loaded input documents that can be re-rendered without some segments."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Collection, Optional

from ..model import Segment

_NEWLINE = r"(?:\r\n|\n|\r(?!\n))"  # the lookahead stops a CRLF from being split in two
_LEAD = re.compile(rf"(?:[ \t]*{_NEWLINE})*")
_SEP = re.compile(rf"{_NEWLINE}(?:[ \t]*{_NEWLINE})+")
_LINES = re.compile(_NEWLINE)

_TIMING = re.compile(
    r"(?:(\d{1,3}):)?(\d{1,2}):(\d{2})[,.](\d{1,3})\s*-->\s*"
    r"(?:(\d{1,3}):)?(\d{1,2}):(\d{2})[,.](\d{1,3})"
)


def split_lines(block: str) -> list[str]:
    return _LINES.split(block)


def split_blocks(text: str) -> tuple[str, list[str], list[str]]:
    """Split a subtitle file into blank-line separated blocks.

    Returns ``(lead, blocks, seps)`` where ``seps[i]`` is the exact text that
    followed ``blocks[i]`` (the last one is the file's trailing newline).
    ``lead + "".join(b + s for b, s in zip(blocks, seps)) == text`` always holds.
    """
    lead = _LEAD.match(text).group(0)  # type: ignore[union-attr]
    rest = text[len(lead):]
    blocks: list[str] = []
    seps: list[str] = []
    pos = 0
    for m in _SEP.finditer(rest):
        blocks.append(rest[pos:m.start()])
        seps.append(m.group(0))
        pos = m.end()
    tail = rest[pos:]
    body = tail.rstrip("\r\n")
    if body or not blocks:
        blocks.append(body)
        seps.append(tail[len(body):])
    else:  # the file ended with a separator: it is the trailer of the last block
        seps[-1] = seps[-1] + tail
    return lead, blocks, seps


def parse_timing(line: str) -> Optional[tuple[float, float]]:
    """Return ``(start, end)`` seconds for an SRT/VTT timing line, else None."""
    m = _TIMING.search(line)
    if not m:
        return None
    h1, m1, s1, f1, h2, m2, s2, f2 = m.groups()

    def sec(h: Optional[str], mi: str, s: str, frac: str) -> float:
        return int(h or 0) * 3600 + int(mi) * 60 + int(s) + int(frac.ljust(3, "0")) / 1000

    return sec(h1, m1, s1, f1), sec(h2, m2, s2, f2)


@dataclass
class Document:
    """A parsed input that remembers its original bytes-level layout.

    ``render`` rebuilds the text without the removed segments (given as
    0-based positions in ``segments``). Everything that is not removed keeps
    its original characters.
    """

    format: str
    segments: list[Segment]
    bom: bool = False
    duration: Optional[float] = None
    source: Optional[str] = None
    _raw: str = field(default="", repr=False)

    def render(self, removed: Collection[int] = (), renumber: bool = False) -> str:
        raise NotImplementedError

    def render_bytes(self, removed: Collection[int] = (), renumber: bool = False) -> bytes:
        data = self.render(removed, renumber).encode("utf-8")
        return b"\xef\xbb\xbf" + data if self.bom else data
