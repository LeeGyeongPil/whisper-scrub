"""Command line interface: ``whisper-scrub clean | check | phrases``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Sequence

from ._version import __version__
from .check import check_result
from .config import Config
from .errors import ScrubError
from .judge import scrub
from .io import load
from .model import REMOVE, ScrubResult
from .phrases import PhraseBook
from .vad import Interval, energy_vad, load_speech_json


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--audio", metavar="WAV", help="16-bit PCM WAV; speech is found with an energy VAD (needs the [audio] extra)")
    p.add_argument("--speech", metavar="JSON", help="speech intervals you already have: [{'start': s, 'end': e}] in seconds")
    p.add_argument("--duration", type=float, metavar="SEC", help="audio length in seconds (default: from --audio or the JSON 'duration')")
    p.add_argument("--phrases", metavar="TSV", help="your own phrase file (one phrase per line, optional TAB + strict|weak)")
    p.add_argument("--no-builtin", action="store_true", help="do not use the built-in dictionaries")
    p.add_argument("--substring", action="store_true", help="also match phrases inside longer text (more false positives)")
    p.add_argument("--lang", choices=["ko", "en", "ja", "zh"], help="force the dictionary language instead of guessing it from the script")
    d = Config()
    p.add_argument("--repeat-min", type=int, metavar="N", default=d.repeat_min, help=f"fold the same sentence when it appears N+ times in a row (default {d.repeat_min}, minimum 2)")
    p.add_argument("--phantom-min-seconds", type=float, metavar="SEC", default=d.phantom_min_seconds, help=f"a segment this long with no speech under it may be removed on audio alone (default {d.phantom_min_seconds:g}; a huge value turns audio-only removal off)")
    p.add_argument("--no-speech-guard", action="store_true", help="do not downgrade audio-only removal when the speech intervals look broken (empty, or covering almost none of the transcript)")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="whisper-scrub",
        description="Find and remove Whisper hallucinations (phantom sentences, repeat loops) in JSON/SRT/VTT transcripts.",
    )
    ap.add_argument("--version", action="version", version=f"whisper-scrub {__version__}")
    sub = ap.add_subparsers(dest="command", required=True)

    c = sub.add_parser("clean", help="remove hallucinated segments and write a report")
    c.add_argument("input", help="Whisper JSON, whisper.cpp JSON, SRT or VTT file")
    c.add_argument("-o", "--output", metavar="FILE", help="where to write the cleaned file (never the input itself)")
    c.add_argument("--report", metavar="FILE|-", help="write a report; '-' prints it to stdout (.json extension: JSON, otherwise Markdown)")
    c.add_argument("--report-format", choices=["md", "json"], help="override the format guessed from --report")
    c.add_argument("--dry-run", action="store_true", help="judge only, write no cleaned file")
    c.add_argument("--renumber", action="store_true", help="renumber SRT cues from 1 (default keeps the original numbers)")
    _add_common(c)

    k = sub.add_parser("check", help="reference-free quality check (flagged ratio, repeat runs)")
    k.add_argument("inputs", nargs="+", help="one or more files")
    k.add_argument("--fail-over", type=float, metavar="RATIO", help="exit 1 if any file's flagged ratio (removed+suspect)/segments exceeds this (0..1)")
    k.add_argument("--audio-dir", metavar="DIR", help="use DIR/<input stem>.wav as the audio of each input")
    k.add_argument("--format", choices=["table", "json"], default="table")
    _add_common(k)

    ph = sub.add_parser("phrases", help="list the dictionary phrases")
    ph.add_argument("--lang", choices=["ko", "en", "ja", "zh"])
    ph.add_argument("--phrases", metavar="TSV", help="also include your own phrase file")
    ph.add_argument("--no-builtin", action="store_true")
    return ap


def _book(args: argparse.Namespace) -> Optional[PhraseBook]:
    """The phrase book chosen by --phrases/--no-builtin (None = built-in default)."""
    if not args.phrases and not args.no_builtin:
        return None
    user = PhraseBook.from_file(args.phrases) if args.phrases else PhraseBook()
    return user if args.no_builtin else PhraseBook.builtin().merge(user)


def _config(args: argparse.Namespace) -> Config:
    return Config(
        substring=args.substring,
        lang=args.lang,
        phrases=_book(args),
        repeat_min=args.repeat_min,
        phantom_min_seconds=args.phantom_min_seconds,
        guard_speech_intervals=not args.no_speech_guard,
    )


def _warn(result: ScrubResult, name: Optional[str] = None) -> None:
    for w in result.warnings:
        print(f"whisper-scrub: warning: {(name + ': ') if name else ''}{w}", file=sys.stderr)


def _audio_info(
    args: argparse.Namespace, wav: Optional[str]
) -> tuple[Optional[list[Interval]], Optional[float]]:
    spans: Optional[list[Interval]] = None
    duration = args.duration
    if wav:
        spans, wav_duration = energy_vad(wav)
        duration = duration if duration is not None else wav_duration
    elif args.speech:
        spans = load_speech_json(args.speech)
    return spans, duration


def _cmd_clean(args: argparse.Namespace) -> int:
    if args.audio and args.speech:
        raise ScrubError("use either --audio or --speech, not both")
    if not args.dry_run and not args.output:
        raise ScrubError("clean writes a new file: pass -o FILE, or use --dry-run to only look at the report")
    if args.output and Path(args.output).resolve() == Path(args.input).resolve():
        raise ScrubError("-o must differ from the input; whisper-scrub never overwrites its input")
    doc = load(args.input)
    spans, duration = _audio_info(args, args.audio)
    result = scrub(doc, audio_duration=duration, speech=spans, config=_config(args))
    _warn(result)

    if args.output and not args.dry_run:
        removed = {i for i, v in enumerate(result.verdicts) if v.action == REMOVE}
        Path(args.output).write_bytes(doc.render_bytes(removed, args.renumber))

    if args.report:
        as_json = args.report_format == "json" or (
            args.report_format is None and args.report != "-" and args.report.endswith(".json")
        )
        text = json.dumps(result.report_json(), ensure_ascii=False, indent=2) + "\n" if as_json else result.report_markdown()
        if args.report == "-":
            sys.stdout.write(text)
        else:
            Path(args.report).write_text(text, encoding="utf-8")

    n = len(result.segments)
    note = "dry run, nothing written" if args.dry_run else f"wrote {args.output}"
    print(
        f"whisper-scrub: removed {len(result.removed)}, suspect {len(result.suspects)}, "
        f"kept {n - len(result.removed) - len(result.suspects)} of {n} segments ({note})",
        file=sys.stderr,
    )
    return 0


def _cmd_check(args: argparse.Namespace) -> int:
    if args.fail_over is not None and not 0.0 <= args.fail_over <= 1.0:
        raise ScrubError(f"--fail-over must be a ratio between 0 and 1, got {args.fail_over}")
    if args.audio and len(args.inputs) > 1:
        raise ScrubError("--audio fits one input; use --audio-dir DIR for several files")
    cfg = _config(args)
    rows = []
    failed = False
    for path in args.inputs:
        wav = args.audio
        if args.audio_dir:
            cand = Path(args.audio_dir) / (Path(path).stem + ".wav")
            wav = str(cand) if cand.exists() else None
        doc = load(path)
        spans, duration = _audio_info(args, wav)
        res = scrub(doc, audio_duration=duration, speech=spans, config=cfg)
        _warn(res, path)
        rep = check_result(res)
        over = args.fail_over is not None and rep.flagged_ratio > args.fail_over
        failed = failed or over
        rows.append((path, rep, over))

    if args.format == "json":
        payload = [dict(file=p, fail=o, **r.as_dict()) for p, r, o in rows]
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for path, rep, over in rows:
            tail = f" | FAIL (> {args.fail_over:g})" if over else ""
            print(f"{path}: {rep.summary_line()}{tail}")
    return 1 if failed else 0


def _cmd_phrases(args: argparse.Namespace) -> int:
    book = _book(args) or PhraseBook.builtin()
    for e in book.entries(args.lang):
        print(f"{e.lang}\t{e.level}\t{e.phrase}\t{e.source}")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return {"clean": _cmd_clean, "check": _cmd_check, "phrases": _cmd_phrases}[args.command](args)
    except ScrubError as exc:
        print(f"whisper-scrub: error: {exc}", file=sys.stderr)
        return 2
    except BrokenPipeError:  # e.g. `... | head`
        return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
