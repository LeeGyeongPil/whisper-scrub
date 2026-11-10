"""Exceptions raised by whisper-scrub. All derive from :class:`ScrubError`."""

from __future__ import annotations


class ScrubError(Exception):
    """Base class for every error this package raises on purpose."""


class UnknownFormatError(ScrubError):
    """The input is not a Whisper JSON, whisper.cpp JSON, SRT or VTT document."""


class MissingExtraError(ScrubError):
    """An optional dependency is needed for this feature but is not installed."""


class ConfigError(ScrubError, ValueError):
    """A configuration value is out of range or malformed."""


class AudioError(ScrubError):
    """The audio file cannot be read (unsupported encoding, corrupt header)."""
