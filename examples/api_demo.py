"""Run: uv run python examples/api_demo.py

Feeds a recorded faster-whisper result to scrub() and prints what happened.
"""

import json
from pathlib import Path

from whisper_scrub import scrub

data = json.loads((Path(__file__).parent / "mixed_en.json").read_text(encoding="utf-8"))
result = scrub(data["segments"], audio_duration=data["duration"])

for seg, verdict in zip(result.segments, result.verdicts):
    rules = ", ".join(h.rule_id for h in verdict.rules) or "-"
    print(f"#{seg.index} {seg.text.strip()[:30]!r:34} {verdict.action:8} {verdict.confidence:7} {rules}")
print("kept:", [s.index for s in result.kept])
