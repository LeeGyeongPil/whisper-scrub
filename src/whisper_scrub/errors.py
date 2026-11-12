"""Exceptions raised by whisper-scrub. All derive from :class:`ScrubError`."""

from __future__ import annotations

from typing import Any, Mapping, Optional


class ScrubError(Exception):
    """Base class for every error this package raises on purpose.

    ``str(exc)`` is always the English message. ``code`` and ``params`` (both optional) let the
    command line show the same error in the chosen display language.
    """

    def __init__(
        self,
        message: str = "",
        *,
        code: Optional[str] = None,
        params: Optional[Mapping[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.params = dict(params) if params else None


class UnknownFormatError(ScrubError):
    """The input is not a Whisper JSON, whisper.cpp JSON, SRT or VTT document."""


class MissingExtraError(ScrubError):
    """An optional dependency is needed for this feature but is not installed."""


class ConfigError(ScrubError, ValueError):
    """A configuration value is out of range or malformed."""


class AudioError(ScrubError):
    """The audio file cannot be read (unsupported encoding, corrupt header)."""
