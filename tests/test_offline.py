"""Light and offline by default (AC-9) plus packaging metadata."""

from __future__ import annotations

import re
import subprocess
import sys
from importlib import resources

from whisper_scrub import PhraseBook, __version__
from whisper_scrub.phrases import LANGUAGES

from .conftest import ROOT


def test_import_pulls_no_heavy_modules():
    code = (
        "import sys, whisper_scrub\n"
        "whisper_scrub.scrub([{'start': 0, 'end': 1, 'text': 'hi'}])\n"
        "bad = [m for m in ('faster_whisper', 'numpy', 'onnxruntime', 'av') if m in sys.modules]\n"
        "print(bad)\n"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "[]"


def test_builtin_dictionaries_load_from_package_data():
    base = resources.files("whisper_scrub.phrases")
    for lang in LANGUAGES:
        assert (base / f"{lang}.tsv").is_file()
    book = PhraseBook.builtin()
    assert book.languages() == ["en", "ja", "ko", "zh"]
    assert all(e.source for e in book.entries())  # every phrase says where it came from
    assert book.lookup("수고하셨습니다", "ko").level == "weak"
    assert book.lookup("subtitles by the amara org community", "en").level == "strict"


def test_version_matches_pyproject():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert re.search(rf'^version = "{re.escape(__version__)}"$', text, re.M)


def test_changelog_mentions_current_version():
    assert f"## [{__version__}]" in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
