# Recorded examples

These files are real output of faster-whisper 1.2.1 (`tiny`, CPU int8), recorded on 2026-11-11 and
replayed by the tests. **No model runs when you use them**: they are practice (mock) inputs.

| File | What it is |
|---|---|
| `mixed_en.json`, `mixed_en.srt`, `mixed_en.vtt` | Speech, 20 s of silence, speech again (72 s clip). The silent part came out as `" You"` (no_speech_prob 0.985, avg_logprob -0.942). |
| `mixed_ko.json`, `mixed_ko.srt` | The same clip decoded with `language="ko"` forced: a loop of `이 말은,` and a broken last cue that runs past the end of the audio. |
| `mixed_vad_speech.json` | Speech intervals (seconds) of that clip from faster-whisper's built-in Silero VAD. |
| `raw_runs.jsonl` | One JSON object per recorded run on 30 s of synthetic silence, noise or tones (ko, en, ja, zh). |

The audio itself is not in this repository (the speech part came from a public speech clip shipped with
faster-whisper's test data); only the transcribed text and numbers are kept.
The SRT/VTT files were written from the JSON with faster-whisper's segment times, so they carry no
meta signals, like most subtitle files you will meet.

`audio_demo.py` builds its own WAV with numpy (2 s tone, 3 s silence) and needs the `[audio]` extra; `api_demo.py` replays `mixed_en.json`.
