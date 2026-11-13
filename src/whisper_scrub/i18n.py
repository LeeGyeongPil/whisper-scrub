"""Display-language support (English / Korean) for the command line and reports.

Only text that a person reads is translated. Machine-readable output (JSON, phrase TSV),
rule ids, actions and the per-rule notes shared with the JSON report stay English.

Language precedence for the CLI: ``--lang`` before the subcommand, then ``WHISPER_SCRUB_LANG``,
then ``LC_ALL``, ``LC_MESSAGES`` and ``LANG``. A value that does not start with ``ko`` means English.
"""

from __future__ import annotations

import errno
import json
import re
from typing import Any, Mapping, Optional

LANGUAGES = ("en", "ko")
ENV_VAR = "WHISPER_SCRUB_LANG"
_ENV_ORDER = (ENV_VAR, "LC_ALL", "LC_MESSAGES", "LANG")

MESSAGES: dict[str, dict[str, str]] = {
    "en": {
        # -- argparse chrome ------------------------------------------------
        "usage_prefix": "usage:",
        "options_title": "options",
        "positional_title": "positional arguments",
        "prefix.error": "error:",
        "prefix.warning": "warning:",
        "argparse.argument": "argument {name}: ",
        "argparse.required": "the following arguments are required: {names}",
        "argparse.unrecognized": "unrecognized arguments: {names}",
        "argparse.invalid_choice": "invalid choice: {value} (choose from {choices})",
        "argparse.expected_one": "expected one argument",
        "argparse.invalid_value": "invalid {kind} value: {value}",
        "help.help": "show this help message and exit",
        "help.version": "show program's version number and exit",
        # -- help texts -----------------------------------------------------
        "desc.main": "Find and remove Whisper hallucinations (phantom sentences, repeat loops) in JSON/SRT/VTT transcripts.",
        "help.ui_lang": "display language of messages and reports (default: WHISPER_SCRUB_LANG, then LC_ALL/LC_MESSAGES/LANG, else en); put it before the subcommand",
        "help.audio": "16-bit PCM WAV; speech is found with an energy VAD (needs the [audio] extra)",
        "help.speech": "speech intervals you already have: [{'start': s, 'end': e}] in seconds",
        "help.duration": "audio length in seconds (default: from --audio or the JSON 'duration')",
        "help.phrases": "your own phrase file (one phrase per line, optional TAB + strict|weak)",
        "help.no_builtin": "do not use the built-in dictionaries",
        "help.substring": "also match phrases inside longer text (more false positives)",
        "help.dict_lang": "force the dictionary (transcript) language instead of guessing it from the script; the display language is the --lang before the subcommand",
        "help.repeat_min": "fold the same sentence when it appears N+ times in a row (default {default}, minimum 2)",
        "help.phantom": "a segment this long with no speech under it may be removed on audio alone (default {default:g}; a huge value turns audio-only removal off)",
        "help.no_guard": "do not downgrade audio-only removal when the speech intervals look broken (empty, or covering almost none of the transcript)",
        "cmd.clean": "remove hallucinated segments and write a report",
        "help.clean.input": "Whisper JSON, whisper.cpp JSON, SRT or VTT file",
        "help.clean.output": "where to write the cleaned file (never the input itself)",
        "help.clean.report": "write a report; '-' prints it to stdout (.json extension: JSON, otherwise Markdown)",
        "help.clean.report_format": "override the format guessed from --report",
        "help.clean.dry_run": "judge only, write no cleaned file",
        "help.clean.renumber": "renumber SRT cues from 1 (default keeps the original numbers)",
        "cmd.check": "reference-free quality check (flagged ratio, repeat runs)",
        "help.check.inputs": "one or more files",
        "help.check.fail_over": "exit 1 if any file's flagged ratio (removed+suspect)/segments exceeds this (0..1)",
        "help.check.audio_dir": "use DIR/<input stem>.wav as the audio of each input",
        "help.check.format": "output format",
        "cmd.phrases": "list the dictionary phrases",
        "help.phrases.phrases": "also include your own phrase file",
        "help.phrases.no_builtin": "list only your own phrase file",
        # -- CLI output -----------------------------------------------------
        "out.summary": "whisper-scrub: removed {removed}, suspect {suspect}, kept {kept} of {total} segments ({note})",
        "out.note_dry": "dry run, nothing written",
        "out.note_wrote": "wrote {output}",
        "out.fail_tail": " | FAIL (> {ratio:g})",
        "out.na": "n/a",
        "check.summary": (
            "flagged {flagged}/{segments} ({ratio:.2f}) | removed {removed} | suspect {suspect} | "
            "repeat runs: {repeat_runs} | speechless chars: {speechless} | fast segments: {fast}"
        ),
        # -- warnings (stderr display; ScrubResult.warnings stays English) -----
        "warn.speech_guard": (
            "speech intervals cover almost none of the transcript - check the file and its units (seconds) "
            "or the recording level; the speech-interval rule (audio.no_speech) was skipped, so nothing was "
            "deleted because of missing speech (audio.beyond_end, based on the audio length, still applies)"
        ),
        # -- errors ---------------------------------------------------------
        "err.cli.audio_and_speech": "use either --audio or --speech, not both",
        "err.cli.need_output": "clean writes a new file: pass -o FILE, or use --dry-run to only look at the report",
        "err.cli.same_output": "-o must differ from the input; whisper-scrub never overwrites its input",
        "err.cli.fail_over": "--fail-over must be a ratio between 0 and 1, got {value}",
        "err.cli.audio_many": "--audio fits one input; use --audio-dir DIR for several files",
        "err.config.range": "{name} must be between 0 and 1, got {value}",
        "err.config.silent_logprob": "silent_logprob must be <= 0 (it is a log probability), got {value}",
        "err.config.repeat_min": "repeat_min must be at least 2, got {value}",
        "err.config.loop_min": "loop_min must be at least 2, got {value}",
        "err.config.negative": "{name} must not be negative, got {value}",
        "err.config.lang": "lang must be one of ko, en, ja, zh (got {value!r})",
        "err.config.audio_duration": "audio_duration must be positive, got {value}",
        "err.config.need_out": "scrub_file needs out=<path> to write the cleaned file (or dry_run=True)",
        "err.config.same_out": "out must differ from the input path; whisper-scrub never overwrites its input",
        "err.config.audio_and_speech": "pass either audio= or speech=, not both",
        "err.vad.interval_format": "speech interval {n} is not {{'start': s, 'end': e}} or [s, e] in seconds: {item!r}",
        "err.vad.interval_order": "speech interval {n} ends before it starts: {item!r}",
        "err.vad.read": "cannot read speech file {path}: {reason}",
        "err.vad.json": "speech file {path} is not valid JSON: {reason}",
        "err.vad.shape": "speech file {path} must be a list of intervals or an object with a 'speech' list",
        "err.vad.numpy": (
            'numpy is required for --audio (energy VAD). Install it with: pip install "whisper-scrub[audio]" '
            "(or pass --speech with a speech-interval JSON you already have; that needs no extras)"
        ),
        "err.vad.wav": (
            "cannot read {path} as a WAV file ({reason}). Convert first, e.g. "
            "`ffmpeg -i input.mp3 -ar 16000 -ac 1 -c:a pcm_s16le out.wav`"
        ),
        "err.vad.width": (
            "{path} is {bits}-bit PCM; only 16-bit is supported. "
            "Convert with `ffmpeg -i in.wav -c:a pcm_s16le out.wav`"
        ),
        "err.io.unknown": (
            "unrecognised input: expected Whisper/whisper.cpp JSON, SRT or WebVTT "
            "(a WEBVTT header, a JSON object/list, or numbered 'hh:mm:ss,mmm --> hh:mm:ss,mmm' cues)"
        ),
        "err.io.read": "cannot read {path}: {reason}",
        "err.io.utf8": "{path} is not valid UTF-8 (byte {byte}); convert it first, e.g. `iconv -f CP949 -t UTF-8`",
        "err.io.segment": (
            "segment {pos} needs start, end and text (or whisper.cpp offsets.from/to); "
            "got a {kind} without them"
        ),
        "err.io.json_parse": "input looks like JSON but does not parse: {reason}",
        "err.io.json_shape": (
            "JSON must be an object with a 'segments' or 'transcription' list, "
            "or a list of segments with start/end/text"
        ),
        "err.phrases.read": "cannot read phrase file {path}: {reason}",
        "err.phrases.utf8": "phrase file {path} is not UTF-8; re-save it as UTF-8",
        "err.phrases.level": "{where}:{no}: level {level!r} must be 'strict' or 'weak' (format: phrase<TAB>strict|weak)",
        "err.phrases.empty": "{where}:{no}: phrase {phrase!r} is empty after normalisation",
        "err.phrases.no_letters": "{where}:{no}: phrase {phrase!r} has no letters",
        # -- Markdown report ------------------------------------------------
        "argparse.kind.float": "float",
        "argparse.kind.int": "int",
        "metavar.command": "command",
        "metavar.input": "input",
        "metavar.inputs": "inputs",
        "reason.enoent": "No such file or directory",
        "reason.eisdir": "Is a directory",
        "reason.enotdir": "Not a directory",
        "reason.eacces": "Permission denied",
        "reason.os": "OS error {errno}",
        "reason.json": "JSON syntax error at line {line} column {col} (char {pos})",
        "report.title": "# whisper-scrub report",
        "report.input": "- input: {source}",
        "report.input_format": " ({format})",
        "report.in_memory": "(in memory)",
        "report.segments": "- segments: {total} (removed {removed}, suspect {suspect}, kept {kept})",
        "report.audio_duration": "- audio duration: {seconds:g} s",
        "report.speech_intervals": "- speech intervals: {value}",
        "report.not_provided": "not provided",
        "report.tool": "- tool: whisper-scrub {version} (report_version {report_version})",
        "report.warning": "- WARNING: {text}",
        "report.none_flagged": "No segments were flagged.",
        "report.table_header": "| # | time (s) | action | confidence | rules | text |",
        "report.evidence_title": "## Evidence",
        "report.evidence_line": "- #{index} {action}: `{rule}` value={value} threshold={threshold} - {note}",
        "report.shared_title": "## Shared meta values",
        "report.shared_line": (
            "- segments {first}-{last} ({count} segments) have the same meta values: "
            "no_speech_prob={no_speech_prob}, avg_logprob={avg_logprob}, "
            "compression_ratio={compression_ratio}. Whisper computes them per decoding window, "
            "so meta signals cannot tell these segments apart."
        ),
        "report.thresholds_title": "## Thresholds",
    },
    "ko": {
        "usage_prefix": "사용법:",
        "options_title": "옵션",
        "positional_title": "위치 인자",
        "prefix.error": "오류:",
        "prefix.warning": "경고:",
        "argparse.argument": "인자 {name}: ",
        "argparse.required": "다음 인자가 필요합니다: {names}",
        "argparse.unrecognized": "인식할 수 없는 인자입니다: {names}",
        "argparse.invalid_choice": "잘못된 선택지입니다: {value} (선택 가능: {choices})",
        "argparse.expected_one": "값이 하나 필요합니다",
        "argparse.invalid_value": "{kind} 값이 올바르지 않습니다: {value}",
        "help.help": "도움말을 보여 주고 종료합니다",
        "help.version": "버전을 보여 주고 종료합니다",
        "desc.main": "JSON/SRT/VTT 전사본에서 Whisper 환각(유령 문장, 반복 루프)을 찾아 지웁니다.",
        "help.ui_lang": "메시지·보고서 화면 언어(기본: WHISPER_SCRUB_LANG, 그다음 LC_ALL/LC_MESSAGES/LANG, 모두 없으면 en); 하위 명령 앞에 둡니다",
        "help.audio": "16비트 PCM WAV; 에너지 VAD 로 말소리를 찾습니다([audio] 추가 패키지 필요)",
        "help.speech": "이미 가진 말소리 구간: 초 단위 [{'start': s, 'end': e}]",
        "help.duration": "오디오 길이(초) (기본: --audio 또는 JSON 의 'duration')",
        "help.phrases": "내 문구 파일(한 줄에 문구 하나, 선택적으로 TAB + strict|weak)",
        "help.no_builtin": "내장 사전을 쓰지 않습니다",
        "help.substring": "더 긴 글 안에 들어 있는 문구도 찾습니다(오탐이 늘어납니다)",
        "help.dict_lang": "글자 모양으로 추측하지 않고 사전(전사) 언어를 강제합니다; 화면 언어는 하위 명령 앞의 --lang 입니다",
        "help.repeat_min": "같은 문장이 연속 N번 이상 나오면 접습니다(기본 {default}, 최소 2)",
        "help.phantom": "이 길이 이상인데 밑에 말소리가 없는 구간은 오디오만으로 지울 수 있습니다(기본 {default:g}; 아주 큰 값이면 오디오만으로 지우기를 끕니다)",
        "help.no_guard": "말소리 구간이 이상해 보여도(비었거나 전사본을 거의 덮지 못함) 오디오만으로 지우기를 낮추지 않습니다",
        "cmd.clean": "환각 구간을 지우고 보고서를 씁니다",
        "help.clean.input": "Whisper JSON, whisper.cpp JSON, SRT 또는 VTT 파일",
        "help.clean.output": "정리한 파일을 쓸 위치(입력 파일 자체는 안 됩니다)",
        "help.clean.report": "보고서를 씁니다; '-' 는 표준 출력에 찍습니다(.json 확장자면 JSON, 아니면 Markdown)",
        "help.clean.report_format": "--report 로 추측한 형식을 바꿉니다",
        "help.clean.dry_run": "판정만 하고 정리한 파일은 쓰지 않습니다",
        "help.clean.renumber": "SRT 번호를 1부터 다시 매깁니다(기본은 원래 번호 유지)",
        "cmd.check": "정답 없이 하는 품질 점검(의심 비율, 반복 구간)",
        "help.check.inputs": "파일 하나 이상",
        "help.check.fail_over": "어느 파일이든 의심 비율 (삭제+의심)/구간 수 가 이 값(0..1)을 넘으면 종료 코드 1",
        "help.check.audio_dir": "각 입력의 오디오로 DIR/<입력 파일 이름>.wav 를 씁니다",
        "help.check.format": "출력 형식",
        "cmd.phrases": "사전 문구를 나열합니다",
        "help.phrases.phrases": "내 문구 파일도 함께 나열합니다",
        "help.phrases.no_builtin": "내 문구 파일만 나열합니다",
        "out.summary": "whisper-scrub: 삭제 {removed}개, 의심 {suspect}개, 유지 {kept}개 (전체 {total}개 구간, {note})",
        "out.note_dry": "시험 실행이라 아무것도 쓰지 않았습니다",
        "out.note_wrote": "{output} 파일을 썼습니다",
        "out.fail_tail": " | 실패 (> {ratio:g})",
        "out.na": "없음",
        "check.summary": (
            "표시 {flagged}/{segments} ({ratio:.2f}) | 삭제 {removed} | 의심 구간 {suspect} | "
            "반복 구간: {repeat_runs} | 무음 글자 비율: {speechless} | 빠른 구간: {fast}"
        ),
        "warn.speech_guard": (
            "말소리 구간이 전사본을 거의 덮지 못합니다 - 파일과 단위(초) 또는 녹음 크기를 확인하세요. "
            "말소리 구간 규칙(audio.no_speech)을 건너뛰었으므로 말소리가 없다는 이유로 지워진 구간은 없습니다"
            "(오디오 길이 규칙 audio.beyond_end 는 그대로 적용됩니다)"
        ),
        "err.cli.audio_and_speech": "--audio 와 --speech 는 함께 쓸 수 없습니다. 하나만 고르세요",
        "err.cli.need_output": "clean 은 새 파일을 씁니다. -o FILE 을 주거나, 보고서만 보려면 --dry-run 을 쓰세요",
        "err.cli.same_output": "-o 는 입력 파일과 달라야 합니다. whisper-scrub 은 입력 파일을 덮어쓰지 않습니다",
        "err.cli.fail_over": "--fail-over 는 0과 1 사이의 비율이어야 합니다(받은 값: {value})",
        "err.cli.audio_many": "--audio 는 입력 하나에만 맞습니다. 여러 파일은 --audio-dir DIR 을 쓰세요",
        "err.config.range": "{name}은(는) 0과 1 사이여야 합니다(받은 값: {value})",
        "err.config.silent_logprob": "silent_logprob 은 0 이하여야 합니다(로그 확률입니다, 받은 값: {value})",
        "err.config.repeat_min": "repeat_min 은 2 이상이어야 합니다(받은 값: {value})",
        "err.config.loop_min": "loop_min 은 2 이상이어야 합니다(받은 값: {value})",
        "err.config.negative": "{name}은(는) 음수일 수 없습니다(받은 값: {value})",
        "err.config.lang": "lang 은 ko, en, ja, zh 중 하나여야 합니다(받은 값: {value!r})",
        "err.config.audio_duration": "audio_duration 은 양수여야 합니다(받은 값: {value})",
        "err.config.need_out": "scrub_file 로 정리한 파일을 쓰려면 out=<경로> 가 필요합니다(또는 dry_run=True)",
        "err.config.same_out": "out 은 입력 경로와 달라야 합니다. whisper-scrub 은 입력 파일을 덮어쓰지 않습니다",
        "err.config.audio_and_speech": "audio= 와 speech= 는 함께 쓸 수 없습니다. 하나만 넘기세요",
        "err.vad.interval_format": "말소리 구간 {n}번이 {{'start': s, 'end': e}} 또는 초 단위 [s, e] 형식이 아닙니다: {item!r}",
        "err.vad.interval_order": "말소리 구간 {n}번의 끝이 시작보다 앞섭니다: {item!r}",
        "err.vad.read": "{path} 말소리 파일을 읽을 수 없습니다: {reason}",
        "err.vad.json": "{path} 말소리 파일은 올바른 JSON 이 아닙니다: {reason}",
        "err.vad.shape": "{path} 말소리 파일은 구간 목록이거나 'speech' 목록이 든 객체여야 합니다",
        "err.vad.numpy": (
            'numpy 가 있어야 --audio(에너지 VAD)를 쓸 수 있습니다. pip install "whisper-scrub[audio]" 로 설치하세요 '
            "(또는 이미 가진 말소리 구간 JSON 을 --speech 로 넘기면 추가 패키지가 필요 없습니다)"
        ),
        "err.vad.wav": (
            "{path} 파일을 WAV 로 읽을 수 없습니다({reason}). 먼저 변환하세요. 예: "
            "`ffmpeg -i input.mp3 -ar 16000 -ac 1 -c:a pcm_s16le out.wav`"
        ),
        "err.vad.width": (
            "{path} 파일은 {bits}비트 PCM 입니다. 16비트만 지원합니다. "
            "`ffmpeg -i in.wav -c:a pcm_s16le out.wav` 로 변환하세요"
        ),
        "err.io.unknown": (
            "알 수 없는 입력입니다. Whisper/whisper.cpp JSON, SRT 또는 WebVTT 여야 합니다 "
            "(WEBVTT 머리글, JSON 객체/목록, 또는 번호가 붙은 'hh:mm:ss,mmm --> hh:mm:ss,mmm' 구간)"
        ),
        "err.io.read": "{path} 파일을 읽을 수 없습니다: {reason}",
        "err.io.utf8": "{path} 파일은 올바른 UTF-8 이 아닙니다({byte}번째 바이트). 먼저 변환하세요. 예: `iconv -f CP949 -t UTF-8`",
        "err.io.segment": (
            "{pos}번 구간에는 start, end, text 가 있어야 합니다(또는 whisper.cpp offsets.from/to). "
            "{kind} 에 그 값이 없습니다"
        ),
        "err.io.json_parse": "입력이 JSON 처럼 보이지만 해석되지 않습니다: {reason}",
        "err.io.json_shape": (
            "JSON 은 'segments' 또는 'transcription' 목록이 든 객체이거나, "
            "start/end/text 가 있는 구간 목록이어야 합니다"
        ),
        "err.phrases.read": "{path} 문구 파일을 읽을 수 없습니다: {reason}",
        "err.phrases.utf8": "{path} 문구 파일은 UTF-8 이 아닙니다. UTF-8 로 다시 저장하세요",
        "err.phrases.level": "{where}:{no}: 수준 {level!r}은(는) 'strict' 또는 'weak' 여야 합니다(형식: 문구<TAB>strict|weak)",
        "err.phrases.empty": "{where}:{no}: 문구 {phrase!r}은(는) 정규화하면 비어 있습니다",
        "err.phrases.no_letters": "{where}:{no}: 문구 {phrase!r}에는 글자가 없습니다",
        "argparse.kind.float": "숫자",
        "argparse.kind.int": "정수",
        "metavar.command": "명령",
        "metavar.input": "입력파일",
        "metavar.inputs": "입력파일",
        "reason.enoent": "파일이나 폴더가 없습니다",
        "reason.eisdir": "파일이 아니라 폴더입니다",
        "reason.enotdir": "경로 중간이 폴더가 아닙니다",
        "reason.eacces": "읽을 권한이 없습니다",
        "reason.os": "운영체제 오류 {errno}",
        "reason.json": "JSON 문법 오류, {line}줄 {col}열(문자 {pos}번째)",
        "report.title": "# whisper-scrub 보고서",
        "report.input": "- 입력: {source}",
        "report.input_format": " ({format})",
        "report.in_memory": "(메모리)",
        "report.segments": "- 구간: {total}개 (삭제 {removed}, 의심 {suspect}, 유지 {kept})",
        "report.audio_duration": "- 오디오 길이: {seconds:g}초",
        "report.speech_intervals": "- 말소리 구간: {value}",
        "report.not_provided": "주어지지 않음",
        "report.tool": "- 도구: whisper-scrub {version} (report_version {report_version})",
        "report.warning": "- 경고: {text}",
        "report.none_flagged": "표시된 구간이 없습니다.",
        "report.table_header": "| # | 시간(초) | 동작 | 확신도 | 규칙 | 텍스트 |",
        "report.evidence_title": "## 근거",
        "report.evidence_line": "- #{index} {action}: `{rule}` 값={value} 기준={threshold} - {note}",
        "report.shared_title": "## 같은 메타 값",
        "report.shared_line": (
            "- {first}-{last}번 구간({count}개)은 메타 값이 같습니다: "
            "no_speech_prob={no_speech_prob}, avg_logprob={avg_logprob}, "
            "compression_ratio={compression_ratio}. Whisper 는 이 값을 디코딩 창마다 계산하므로 "
            "메타 신호로는 이 구간들을 구별할 수 없습니다."
        ),
        "report.thresholds_title": "## 기준값",
    },
}

# English warning text (as stored in ScrubResult.warnings) -> message key, for display only.
_WARNING_KEYS = {"warn.speech_guard"}

_current = "en"


# -- Korean particles ---------------------------------------------------------
_PARTICLE = re.compile(r"(\S)(은\(는\)|이\(가\)|을\(를\)|과\(와\)|으로\(로\))")
_PARTICLE_FORMS = {  # (after final consonant, after vowel)
    "은(는)": ("은", "는"),
    "이(가)": ("이", "가"),
    "을(를)": ("을", "를"),
    "과(와)": ("과", "와"),
    "으로(로)": ("으로", "로"),
}
_DIGIT_BATCHIM = set("013678")  # 영·일·삼·육·칠·팔 end in a final consonant
_LATIN_BATCHIM = set("lmnrLMNR")


def _has_batchim(ch: str, rieul_ok: bool) -> bool:
    code = ord(ch)
    if 0xAC00 <= code <= 0xD7A3:
        jong = (code - 0xAC00) % 28
        return jong != 0 and not (rieul_ok and jong == 8)  # ㄹ takes the vowel form of 으로
    if ch.isdigit():
        return ch in _DIGIT_BATCHIM and not (rieul_ok and ch in "18")  # 일·팔 end in ㄹ
    if ch.isascii() and ch.isalpha():
        return ch in _LATIN_BATCHIM
    return False


def fix_particles(text: str) -> str:
    """Pick 은/는, 이/가, 을/를, 과/와, 으로/로 from the sound before a ``X(Y)`` marker."""

    def repl(m: re.Match[str]) -> str:
        ch, marker = m.group(1), m.group(2)
        with_batchim, without = _PARTICLE_FORMS[marker]
        return ch + (with_batchim if _has_batchim(ch, marker == "으로(로)") else without)

    # markers right after a closing quote or bracket look through it
    text = re.sub(r"([^\s'\"`)\]])(['\"`)\]]+)(은\(는\)|이\(가\)|을\(를\)|과\(와\)|으로\(로\))",
                  lambda m: m.group(1) + m.group(2) + _PARTICLE_FORMS[m.group(3)][
                      0 if _has_batchim(m.group(1), m.group(3) == "으로(로)") else 1], text)
    return _PARTICLE.sub(repl, text)


# -- language resolution ------------------------------------------------------
def normalize_lang(value: Optional[str]) -> str:
    """``ko``/``ko_KR.UTF-8`` -> ``ko``; anything else -> ``en``."""
    return "ko" if value and value.strip().lower().startswith("ko") else "en"


def resolve_lang(argv_value: Optional[str], env: Mapping[str, str]) -> str:
    """``--lang`` > ``WHISPER_SCRUB_LANG`` > ``LC_ALL`` > ``LC_MESSAGES`` > ``LANG``; default ``en``."""
    if argv_value and argv_value.strip().lower() in LANGUAGES:  # an invalid --lang is reported by the parser
        return normalize_lang(argv_value)
    for name in _ENV_ORDER:
        value = env.get(name, "")
        if value.strip():
            return normalize_lang(value)
    return "en"


def set_lang(lang: str) -> None:
    global _current
    _current = normalize_lang(lang)


def get_lang() -> str:
    return _current


# -- lookup -------------------------------------------------------------------
def translate(lang: str, key: str, **params: Any) -> str:
    """Message ``key`` in ``lang`` (unknown language falls back to English)."""
    params = {k: (v.text(lang) if isinstance(v, Reason) else v) for k, v in params.items()}
    table = MESSAGES.get(lang, MESSAGES["en"])
    text = table.get(key) or MESSAGES["en"][key]
    out = text.format(**params) if params else text
    return fix_particles(out) if lang == "ko" else out


def t(key: str, **params: Any) -> str:
    """Message ``key`` in the current display language."""
    return translate(_current, key, **params)


_ERRNO_KEYS = {errno.ENOENT: "reason.enoent", errno.EISDIR: "reason.eisdir",
               errno.ENOTDIR: "reason.enotdir", errno.EACCES: "reason.eacces"}


class Reason:
    """The cause of an error, kept as an exception so it can be shown in either language.

    English text is the library's own wording (``strerror`` / the exception message).
    Korean text is built per errno or per JSON error position; anything unknown keeps
    the original text.
    """

    def __init__(self, exc: BaseException) -> None:
        self.exc = exc

    def __str__(self) -> str:
        return self.text("en")

    def text(self, lang: str) -> str:
        exc = self.exc
        if lang != "ko":
            return (exc.strerror if isinstance(exc, OSError) and exc.strerror else str(exc))
        if isinstance(exc, OSError):
            key = _ERRNO_KEYS.get(exc.errno or 0)
            if key:
                return translate("ko", key)
            return translate("ko", "reason.os", errno=exc.errno if exc.errno is not None else "?")
        if isinstance(exc, json.JSONDecodeError):
            return translate("ko", "reason.json", line=exc.lineno, col=exc.colno, pos=exc.pos)
        return str(exc)


def fail(cls: type, code: str, **params: Any) -> Exception:
    """Build ``cls(english_message, code=..., params=...)`` for ``raise``."""
    return cls(translate("en", code, **params), code=code, params=params)


def localize_error(exc: Exception) -> str:
    """The error text in the current language (the plain message when it has no code)."""
    code = getattr(exc, "code", None)
    if code:
        return t(code, **(getattr(exc, "params", None) or {}))
    return str(exc)


def localize_warning(text: str, lang: Optional[str] = None) -> str:
    """Translate a known English warning for display; unknown text is returned unchanged."""
    for key in _WARNING_KEYS:
        if text == MESSAGES["en"][key]:
            return translate(lang or _current, key)
    return text
