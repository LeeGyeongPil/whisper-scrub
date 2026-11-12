"""Command line interface: ``whisper-scrub clean | check | phrases``."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Optional, Sequence

from ._version import __version__
from .check import check_result
from .config import Config
from .errors import ScrubError
from .i18n import fail, get_lang, localize_error, localize_warning, resolve_lang, set_lang, t
from .judge import scrub
from .io import load
from .model import REMOVE, ScrubResult
from .phrases import PhraseBook
from .vad import Interval, energy_vad, load_speech_json

COMMANDS = ("clean", "check", "phrases")


class _Formatter(argparse.HelpFormatter):
    """Help formatter whose 'usage:' heading follows the display language."""

    def add_usage(self, usage, actions, groups, prefix=None):  # type: ignore[no-untyped-def]
        if prefix is None:
            prefix = t("usage_prefix") + " "
        super().add_usage(usage, actions, groups, prefix)


def _localize_argparse(msg: str) -> str:
    """Translate the common argparse error messages when the display language is Korean."""
    if get_lang() != "ko":
        return msg
    head = ""
    m = re.match(r"argument (.+?): (.*)$", msg, re.S)
    if m:
        head, msg = t("argparse.argument", name=m.group(1)), m.group(2)
    if m := re.fullmatch(r"the following arguments are required: (.*)", msg, re.S):
        return t("argparse.required", names=m.group(1))
    if m := re.fullmatch(r"unrecognized arguments: (.*)", msg, re.S):
        return t("argparse.unrecognized", names=m.group(1))
    if m := re.fullmatch(r"invalid choice: (.+?) \(choose from (.*)\)", msg, re.S):
        return head + t("argparse.invalid_choice", value=m.group(1), choices=m.group(2))
    if m := re.fullmatch(r"invalid (\w+) value: (.*)", msg, re.S):
        kind = m.group(1)
        try:
            kind = t(f"argparse.kind.{kind}")
        except KeyError:
            pass
        return head + t("argparse.invalid_value", kind=kind, value=m.group(2))
    if msg == "expected one argument":
        return head + t("argparse.expected_one")
    return head + msg


class _Parser(argparse.ArgumentParser):
    """ArgumentParser whose headings, -h text and error prefix follow the display language."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs["add_help"] = False
        kwargs.setdefault("formatter_class", _Formatter)
        super().__init__(*args, **kwargs)
        self._positionals.title = t("positional_title")
        self._optionals.title = t("options_title")
        self.add_argument("-h", "--help", action="help", default=argparse.SUPPRESS, help=t("help.help"))

    def error(self, message: str) -> Any:
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog}: {t('prefix.error')} {_localize_argparse(message)}\n")


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--audio", metavar="WAV", help=t("help.audio"))
    p.add_argument("--speech", metavar="JSON", help=t("help.speech"))
    p.add_argument("--duration", type=float, metavar="SEC", help=t("help.duration"))
    p.add_argument("--phrases", metavar="TSV", help=t("help.phrases"))
    p.add_argument("--no-builtin", action="store_true", help=t("help.no_builtin"))
    p.add_argument("--substring", action="store_true", help=t("help.substring"))
    # transcript (dictionary) language; the display language is the --lang before the subcommand
    p.add_argument("--lang", choices=["ko", "en", "ja", "zh"], help=t("help.dict_lang"))
    d = Config()
    p.add_argument("--repeat-min", type=int, metavar="N", default=d.repeat_min, help=t("help.repeat_min", default=d.repeat_min))
    p.add_argument("--phantom-min-seconds", type=float, metavar="SEC", default=d.phantom_min_seconds, help=t("help.phantom", default=d.phantom_min_seconds))
    p.add_argument("--no-speech-guard", action="store_true", help=t("help.no_guard"))


def build_parser() -> argparse.ArgumentParser:
    """Build the parser in the current display language (see :func:`whisper_scrub.i18n.set_lang`)."""
    ap = _Parser(prog="whisper-scrub", description=t("desc.main"))
    ap.add_argument("--version", action="version", version=f"whisper-scrub {__version__}", help=t("help.version"))
    # display language; read by _display_lang() before parsing, registered here for --help and validation
    ap.add_argument("--lang", dest="ui_lang", choices=["en", "ko"], metavar="{en,ko}", help=t("help.ui_lang"))
    # English keeps argparse's own {clean,check,phrases} usage; Korean shows a translated name instead of the dest
    sub_names: dict[str, Any] = {"metavar": t("metavar.command")} if get_lang() == "ko" else {}
    sub = ap.add_subparsers(dest="command", required=True, parser_class=_Parser, **sub_names)

    c = sub.add_parser("clean", help=t("cmd.clean"))
    c.add_argument("input", metavar=t("metavar.input"), help=t("help.clean.input"))
    c.add_argument("-o", "--output", metavar="FILE", help=t("help.clean.output"))
    c.add_argument("--report", metavar="FILE|-", help=t("help.clean.report"))
    c.add_argument("--report-format", choices=["md", "json"], help=t("help.clean.report_format"))
    c.add_argument("--dry-run", action="store_true", help=t("help.clean.dry_run"))
    c.add_argument("--renumber", action="store_true", help=t("help.clean.renumber"))
    _add_common(c)

    k = sub.add_parser("check", help=t("cmd.check"))
    k.add_argument("inputs", nargs="+", metavar=t("metavar.inputs"), help=t("help.check.inputs"))
    k.add_argument("--fail-over", type=float, metavar="RATIO", help=t("help.check.fail_over"))
    k.add_argument("--audio-dir", metavar="DIR", help=t("help.check.audio_dir"))
    k.add_argument("--format", choices=["table", "json"], default="table", help=t("help.check.format"))
    _add_common(k)

    ph = sub.add_parser("phrases", help=t("cmd.phrases"))
    ph.add_argument("--lang", choices=["ko", "en", "ja", "zh"], help=t("help.dict_lang"))
    ph.add_argument("--phrases", metavar="TSV", help=t("help.phrases.phrases"))
    ph.add_argument("--no-builtin", action="store_true", help=t("help.phrases.no_builtin"))
    return ap


def _display_lang(argv: Sequence[str]) -> str:
    """Display language: ``--lang`` before the subcommand > env vars (see ``resolve_lang``).

    Only the tokens before the first subcommand name are looked at, so the subcommands'
    own ``--lang ko|en|ja|zh`` (dictionary language) is never mistaken for it.
    """

    class _Quiet(argparse.ArgumentParser):
        def error(self, message: str) -> Any:  # a bad value is reported by the real parser
            raise ValueError(message)

    cut = next((i for i, a in enumerate(argv) if a in COMMANDS), len(argv))
    pre = _Quiet(add_help=False, allow_abbrev=False)
    pre.add_argument("--lang", dest="ui_lang")
    try:
        known, _ = pre.parse_known_args(list(argv[:cut]))
        value = known.ui_lang
    except ValueError:
        value = None
    return resolve_lang(value, os.environ)


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
        print(
            f"whisper-scrub: {t('prefix.warning')} {(name + ': ') if name else ''}{localize_warning(w, get_lang())}",
            file=sys.stderr,
        )


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
        raise fail(ScrubError, "err.cli.audio_and_speech")
    if not args.dry_run and not args.output:
        raise fail(ScrubError, "err.cli.need_output")
    if args.output and Path(args.output).resolve() == Path(args.input).resolve():
        raise fail(ScrubError, "err.cli.same_output")
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
        # JSON is machine output and never translated; only the Markdown labels follow the display language
        text = (
            json.dumps(result.report_json(), ensure_ascii=False, indent=2) + "\n"
            if as_json
            else result.report_markdown(lang=get_lang())
        )
        if args.report == "-":
            sys.stdout.write(text)
        else:
            Path(args.report).write_text(text, encoding="utf-8")

    n = len(result.segments)
    note = t("out.note_dry") if args.dry_run else t("out.note_wrote", output=args.output)
    print(
        t(
            "out.summary",
            removed=len(result.removed),
            suspect=len(result.suspects),
            kept=n - len(result.removed) - len(result.suspects),
            total=n,
            note=note,
        ),
        file=sys.stderr,
    )
    return 0


def _cmd_check(args: argparse.Namespace) -> int:
    if args.fail_over is not None and not 0.0 <= args.fail_over <= 1.0:
        raise fail(ScrubError, "err.cli.fail_over", value=args.fail_over)
    if args.audio and len(args.inputs) > 1:
        raise fail(ScrubError, "err.cli.audio_many")
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
            tail = t("out.fail_tail", ratio=args.fail_over) if over else ""
            print(f"{path}: {rep.summary_line(get_lang())}{tail}")
    return 1 if failed else 0


def _cmd_phrases(args: argparse.Namespace) -> int:
    book = _book(args) or PhraseBook.builtin()
    for e in book.entries(args.lang):
        print(f"{e.lang}\t{e.level}\t{e.phrase}\t{e.source}")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    tokens = list(sys.argv[1:] if argv is None else argv)
    set_lang(_display_lang(tokens))
    args = build_parser().parse_args(tokens)
    try:
        return {"clean": _cmd_clean, "check": _cmd_check, "phrases": _cmd_phrases}[args.command](args)
    except ScrubError as exc:
        print(f"whisper-scrub: {t('prefix.error')} {localize_error(exc)}", file=sys.stderr)
        return 2
    except BrokenPipeError:  # e.g. `... | head`
        return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
