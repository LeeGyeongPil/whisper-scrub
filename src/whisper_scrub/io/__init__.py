"""Readers and writers for Whisper JSON, SRT and VTT (internal helpers)."""

from .detect import load, loads
from .document import Document
from .whisper_json import segments_from_items

__all__ = ["Document", "load", "loads", "segments_from_items"]
