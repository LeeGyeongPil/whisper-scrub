"""WebVTT reader/writer: header, NOTE, STYLE, REGION blocks and cue ids are kept."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Collection, Optional

from ..model import Segment
from ..normalize import strip_markup
from .document import Document, parse_timing, split_blocks, split_lines

_NON_CUE = ("WEBVTT", "NOTE", "STYLE", "REGION")


@dataclass
class VttDocument(Document):
    _lead: str = ""
    _blocks: list[str] = None  # type: ignore[assignment]
    _seps: list[str] = None  # type: ignore[assignment]
    _cue_block: list[int] = None  # type: ignore[assignment]

    def render(self, removed: Collection[int] = (), renumber: bool = False) -> str:
        # `renumber` has no meaning for VTT (cue identifiers are free text); ignored.
        drop = {self._cue_block[p] for p in removed}
        keep = [i for i in range(len(self._blocks)) if i not in drop]
        out = [self._lead]
        for j, i in enumerate(keep):
            out.append(self._blocks[i])
            out.append(self._seps[i] if j < len(keep) - 1 else self._seps[-1])
        return "".join(out)


def parse_vtt(text: str, bom: bool = False, source: Optional[str] = None) -> VttDocument:
    lead, blocks, seps = split_blocks(text)
    segments: list[Segment] = []
    cue_block: list[int] = []
    for bi, block in enumerate(blocks):
        lines = split_lines(block)
        if lines[0].startswith(_NON_CUE):
            continue
        for ti in (0, 1):
            t = parse_timing(lines[ti]) if ti < len(lines) else None
            if t:
                body = "\n".join(lines[ti + 1:]).strip()
                segments.append(
                    Segment(len(segments) + 1, t[0], t[1], strip_markup(body) if body else "", raw=block)
                )
                cue_block.append(bi)
                break
    return VttDocument(
        format="vtt",
        segments=segments,
        bom=bom,
        source=source,
        _raw=text,
        _lead=lead,
        _blocks=blocks,
        _seps=seps,
        _cue_block=cue_block,
    )
