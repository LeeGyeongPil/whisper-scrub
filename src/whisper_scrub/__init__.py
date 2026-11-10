"""whisper-scrub: remove Whisper hallucinations from transcripts and subtitles.

Quick start::

    from whisper_scrub import scrub
    result = scrub(segments, audio_duration=72.0)
    clean = result.kept
    print(result.report_markdown())
"""

from ._version import __version__
from .check import CheckReport, check_result
from .config import Config
from .errors import AudioError, ConfigError, MissingExtraError, ScrubError, UnknownFormatError
from .io import Document, load, loads
from .judge import scrub, scrub_file
from .model import RuleHit, ScrubResult, Segment, Verdict
from .phrases import PhraseBook

__all__ = [
    "AudioError",
    "CheckReport",
    "Config",
    "ConfigError",
    "Document",
    "MissingExtraError",
    "PhraseBook",
    "RuleHit",
    "ScrubError",
    "ScrubResult",
    "Segment",
    "UnknownFormatError",
    "Verdict",
    "__version__",
    "check_result",
    "load",
    "loads",
    "scrub",
    "scrub_file",
]
