"""Text normalisation and script (language) guessing."""

from __future__ import annotations

import re
import unicodedata

_TAG = re.compile(r"<[^>]+>")
_SPACES = re.compile(r"\s+")


def strip_markup(text: str) -> str:
    """Remove subtitle tags such as ``<i>`` or ``<c.yellow>``."""
    return _TAG.sub("", text)


def _script_of(ch: str) -> str:
    cp = ord(ch)
    if 0xAC00 <= cp <= 0xD7A3 or 0x1100 <= cp <= 0x11FF or 0x3130 <= cp <= 0x318F:
        return "ko"
    if 0x3040 <= cp <= 0x30FF or 0x31F0 <= cp <= 0x31FF:
        return "ja"
    if 0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF or 0xF900 <= cp <= 0xFAFF:
        return "han"
    if ch.isalpha():
        return "latin"
    return ""


def detect_lang(text: str) -> str:
    """Guess a dictionary language from the writing system.

    Returns ``ko``, ``ja``, ``zh`` or ``en`` (any Latin text), or ``""`` when
    the text has no letters at all. Kana wins over Han (Japanese uses both),
    Hangul wins over Han.
    """
    counts = {"ko": 0, "ja": 0, "han": 0, "latin": 0}
    for ch in text:
        s = _script_of(ch)
        if s:
            counts[s] += 1
    if counts["ja"]:
        return "ja"
    if counts["ko"]:
        return "ko"
    if counts["han"]:
        return "zh"
    if counts["latin"]:
        return "en"
    return ""


def normalize(text: str) -> str:
    """NFKC, case-fold, punctuation and symbols to spaces, collapse spaces.

    For Korean, Japanese and Chinese text the spaces are removed as well,
    because those scripts are spaced inconsistently between engines.
    """
    t = unicodedata.normalize("NFKC", strip_markup(text)).casefold()
    chars = []
    for ch in t:
        # P* punctuation, S* symbols, Z* separators, C* controls -> space
        chars.append(" " if unicodedata.category(ch)[0] in "PSZC" else ch)
    t = _SPACES.sub(" ", "".join(chars)).strip()
    if detect_lang(t) in ("ko", "ja", "zh"):
        t = t.replace(" ", "")
    return t
