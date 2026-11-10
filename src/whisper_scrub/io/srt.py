"""SRT reader/writer that keeps untouched cue blocks byte-for-byte."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Collection, Optional

from ..model import Segment
from ..normalize import strip_markup
from .document import Document, parse_timing, split_blocks, split_lines

_NUMBER_LINE = re.compile(r"^(\s*)\d+")


def _cue_of(block: str) -> Optional[tuple[int, tuple[float, float]]]:
    """Return ``(timing line index, (start, end))`` when the block is a cue."""
    lines = split_lines(block)
    for i in (0, 1):
        if i < len(lines):
            t = parse_timing(lines[i])
            if t:
                return i, t
    return None


@dataclass
class SrtDocument(Document):
    _lead: str = ""
    _blocks: list[str] = None  # type: ignore[assignment]
    _seps: list[str] = None  # type: ignore[assignment]
    _cue_block: list[int] = None  # type: ignore[assignment]  # segment position -> block index

    def render(self, removed: Collection[int] = (), renumber: bool = False) -> str:
        drop = {self._cue_block[p] for p in removed}
        keep = [i for i in range(len(self._blocks)) if i not in drop]
        if not keep:
            return ""
        cue_of_block = {b: p for p, b in enumerate(self._cue_block)}
        out = [self._lead]
        n = 0
        for j, i in enumerate(keep):
            block = self._blocks[i]
            if renumber and i in cue_of_block:
                n += 1
                if _NUMBER_LINE.match(split_lines(block)[0]):
                    block = _NUMBER_LINE.sub(lambda m: f"{m.group(1)}{n}", block, count=1)
            out.append(block)
            out.append(self._seps[i] if j < len(keep) - 1 else self._seps[-1])
        return "".join(out)


def parse_srt(text: str, bom: bool = False, source: Optional[str] = None) -> SrtDocument:
    lead, blocks, seps = split_blocks(text)
    segments: list[Segment] = []
    cue_block: list[int] = []
    for bi, block in enumerate(blocks):
        cue = _cue_of(block)
        if not cue:
            continue
        ti, (start, end) = cue
        body = "\n".join(split_lines(block)[ti + 1:]).strip()
        segments.append(Segment(len(segments) + 1, start, end, strip_markup(body) if body else "", raw=block))
        cue_block.append(bi)
    return SrtDocument(
        format="srt",
        segments=segments,
        bom=bom,
        source=source,
        _raw=text,
        _lead=lead,
        _blocks=blocks,
        _seps=seps,
        _cue_block=cue_block,
    )
