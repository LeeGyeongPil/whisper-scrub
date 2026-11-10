"""Run: uv run python examples/audio_demo.py   (needs the [audio] extra: numpy)

Builds a 5 s WAV (2 s tone, 3 s silence) and a subtitle whose second cue claims a
fluent sentence during the silence, then lets scrub_file() look at the audio.
"""

import tempfile
import wave
from pathlib import Path

import numpy as np

from whisper_scrub import scrub_file

rate = 16000
t = np.arange(2 * rate) / rate
tone = (0.5 * np.sin(2 * np.pi * 220 * t) * 32767).astype("<i2")
pcm = np.concatenate([tone, np.zeros(3 * rate, dtype="<i2")])

SRT = """1
00:00:00,000 --> 00:00:02,000
Today we start with the budget.

2
00:00:02,500 --> 00:00:04,800
Please remember to like and subscribe to the channel.
"""

with tempfile.TemporaryDirectory() as tmp:
    wav = Path(tmp) / "clip.wav"
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())
    srt = Path(tmp) / "clip.srt"
    srt.write_text(SRT, encoding="utf-8")

    result = scrub_file(srt, audio=wav, dry_run=True)

for seg, verdict in zip(result.segments, result.verdicts):
    rules = ", ".join(h.rule_id for h in verdict.rules) or "-"
    print(f"#{seg.index} {verdict.action:7} {rules}  {seg.text}")
