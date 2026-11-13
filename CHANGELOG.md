# Changelog

All notable changes to this project are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.1] - 2026-11-13

### Fixed
- Documentation: the README install section now leads with the tag-pinned GitHub install
  (`pip` and `uvx --from git+...@v0.2.1`) so it works whether or not the package is on PyPI yet; the bare PyPI
  commands are described as working once published. Also notes that `git+` installs need git.

### Known issues
- The numpy hint printed by the CLI and `MissingExtraError` (in `i18n.py`) suggests the PyPI form
  `pip install "whisper-scrub[audio]"`, which fails until the package is published; use the GitHub tag install.

## [0.2.0] - 2026-11-13

### Added
- Display language for the CLI: English or Korean. Chosen by `--lang en|ko` before the subcommand,
  then `WHISPER_SCRUB_LANG`, then `LC_ALL`, `LC_MESSAGES`, `LANG`; anything not starting with `ko` is English.
  Covers `--help`, usage and argparse errors, the summary lines, warnings, error messages and the
  Markdown report labels. The subcommands' own `--lang ko|en|ja|zh` (dictionary language) is unchanged.
- `whisper_scrub.i18n` (message tables, `resolve_lang`, Korean particle handling).
- `ScrubError` accepts optional `code` and `params` keyword arguments; `str(exc)` stays the English message.
- `report_markdown(lang="en")` and `CheckReport.summary_line(lang="en")` accept an opt-in language.

### Changed
- If a script compares CLI message text and your environment `LANG` starts with `ko`, the text is now
  Korean. Set `WHISPER_SCRUB_LANG=en` to keep English. JSON output, phrase TSV and exit codes are unchanged.
- The dictionary `--lang` option now has help text that points to the display `--lang`.

## [0.1.0] - 2026-11-11

### Added
- Speech-interval guard: when the intervals are empty, or at least `speech_guard_ratio` (0.8) of the
  long text segments have zero overlap (3+ candidates), `audio.no_speech` is skipped and a warning is
  added to `ScrubResult.warnings`, the reports and the CLI stderr. `Config.guard_speech_intervals`
  / `--no-speech-guard` turn it off.
- CLI options `--repeat-min` and `--phantom-min-seconds` (same defaults as `Config`).
- Input readers with content-based detection: openai-whisper JSON, OpenAI `verbose_json`,
  faster-whisper segment lists (dicts or `Segment` objects), whisper.cpp `-oj`, SRT and WebVTT.
- Ten rules: `phrase.strict`, `phrase.weak`, `repeat.run`, `repeat.loop`, `meta.no_speech`,
  `meta.silent_window`, `audio.no_speech`, `audio.beyond_end`, `text.broken`, `segment.isolated`.
- `remove` / `suspect` / `keep` verdicts with confidence and per-rule evidence.
- Format-preserving rewriting: untouched SRT/VTT blocks stay byte-identical (BOM, CRLF, timecodes,
  VTT header/NOTE/STYLE/cue ids), JSON keeps every other key; optional `--renumber` for SRT.
- Speech intervals from a JSON file, and an energy VAD for 16-bit PCM WAV (`[audio]` extra).
- Built-in phrase dictionaries for ko, en, ja, zh with per-phrase source; user phrase files.
- CLI: `whisper-scrub clean`, `check` (with `--fail-over` exit code) and `phrases`.
- Markdown and JSON reports (`report_version` 1).
- Typed package (`py.typed`).

### Fixed
- A wrong or empty speech-interval file, or a quietly recorded WAV, no longer deletes real speech
  through `audio.no_speech`.
- `energy_vad` threshold is relative to the signal (10% of the 95th-percentile RMS); only digital
  silence (< 1e-4) yields no speech.

### Known limitations
- With the guard active, `audio.beyond_end` still applies when `--audio` is given, but the warning
  text says "nothing was deleted because of the audio"; the wording will be corrected in a later release.
- The guard needs 3 or more candidate segments; with 1-2 segments a speech-interval file from another
  recording can still remove real sentences through `audio.no_speech` without a warning.
