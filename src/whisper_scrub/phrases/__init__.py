"""Hallucination phrase dictionaries (built-in TSV files plus user files)."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Iterable, Optional, Union

from ..errors import ConfigError
from ..i18n import Reason, fail
from ..normalize import detect_lang, normalize

LANGUAGES = ("ko", "en", "ja", "zh")
LEVELS = ("strict", "weak")


@dataclass(frozen=True)
class PhraseEntry:
    phrase: str  # as written in the file
    norm: str  # normalised key used for matching
    lang: str
    level: str  # "strict" | "weak"
    source: str


class PhraseBook:
    """Phrase lookup by language and normalised text."""

    def __init__(self, entries: Optional[Iterable[PhraseEntry]] = None) -> None:
        self._by_lang: dict[str, dict[str, PhraseEntry]] = {}
        for e in entries or ():
            self.add(e)

    # -- building ---------------------------------------------------------
    def add(self, entry: PhraseEntry) -> None:
        bucket = self._by_lang.setdefault(entry.lang, {})
        old = bucket.get(entry.norm)
        # strict beats weak when the same phrase is listed twice
        if old is None or (old.level == "weak" and entry.level == "strict"):
            bucket[entry.norm] = entry

    def merge(self, other: "PhraseBook") -> "PhraseBook":
        """Return a new book with ``other`` layered on top of this one."""
        merged = PhraseBook(self.entries())
        for e in other.entries():
            bucket = merged._by_lang.setdefault(e.lang, {})
            bucket[e.norm] = e  # the later (user) book wins, including level
        return merged

    @classmethod
    def builtin(cls) -> "PhraseBook":
        """Load the dictionaries shipped inside the package."""
        book = cls()
        base = resources.files(__package__)
        for lang in LANGUAGES:
            text = (base / f"{lang}.tsv").read_text(encoding="utf-8")
            for e in _parse(text, default_lang=lang, where=f"builtin {lang}.tsv"):
                book.add(e)
        return book

    @classmethod
    def from_file(cls, path: Union[str, Path], default_level: str = "weak") -> "PhraseBook":
        """Load a user file: one phrase per line, optional ``<TAB>strict|weak``.

        The language comes from the writing system of each phrase. Lines
        starting with ``#`` and blank lines are ignored.
        """
        p = Path(path)
        try:
            text = p.read_text(encoding="utf-8-sig")
        except OSError as exc:
            raise fail(ConfigError, "err.phrases.read", path=p, reason=Reason(exc)) from exc
        except UnicodeDecodeError as exc:
            raise fail(ConfigError, "err.phrases.utf8", path=p) from exc
        return cls(_parse(text, default_lang=None, where=str(p), default_level=default_level, user=True))

    # -- reading ----------------------------------------------------------
    def entries(self, lang: Optional[str] = None) -> list[PhraseEntry]:
        langs = [lang] if lang else sorted(self._by_lang)
        return [e for lg in langs for e in self._by_lang.get(lg, {}).values()]

    def languages(self) -> list[str]:
        return sorted(self._by_lang)

    def lookup(self, norm_text: str, lang: str) -> Optional[PhraseEntry]:
        """Exact match of an already normalised text."""
        return self._by_lang.get(lang, {}).get(norm_text)

    def find_substring(self, norm_text: str, lang: str, min_len: int) -> Optional[PhraseEntry]:
        """Longest phrase contained in the text (only used with ``substring=True``)."""
        best: Optional[PhraseEntry] = None
        for key, e in self._by_lang.get(lang, {}).items():
            if len(key) >= min_len and key in norm_text and (best is None or len(key) > len(best.norm)):
                best = e
        return best

    def __len__(self) -> int:
        return sum(len(b) for b in self._by_lang.values())


def _parse(
    text: str,
    default_lang: Optional[str],
    where: str,
    default_level: str = "weak",
    user: bool = False,
) -> list[PhraseEntry]:
    out: list[PhraseEntry] = []
    for no, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        cols = line.split("\t")
        phrase = cols[0].strip()
        level = cols[1].strip() if len(cols) > 1 and cols[1].strip() else default_level
        source = cols[2].strip() if len(cols) > 2 else ("user" if user else "")
        if level not in LEVELS:
            raise fail(ConfigError, "err.phrases.level", where=where, no=no, level=level)
        norm = normalize(phrase)
        if not norm:
            raise fail(ConfigError, "err.phrases.empty", where=where, no=no, phrase=phrase)
        lang = default_lang or detect_lang(norm)
        if not lang:
            raise fail(ConfigError, "err.phrases.no_letters", where=where, no=no, phrase=phrase)
        out.append(PhraseEntry(phrase, norm, lang, level, source))
    return out
