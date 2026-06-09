"""Quick benchmark for the Maya1 path on this box.

Measures wall time end to end (llama.cpp Vulkan token generation + SNAC decode
on CPU), audio duration, and RTF (real-time factor = wall_time / audio_seconds;
1.0 means realtime). Needs the llm-voice server running (compose or manual).
Run inside the venv: MAYA1_URL=http://localhost:9091 .venv/bin/python bench.py
"""
import time

import synth

# Representative game lines: a short bark, an emotional line, a long narration.
LINES = [
    ("short", "brute", "You shall not pass!"),
    ("emotional", "villain_male",
     "[angry] You dare return? [laugh] How precious. [whisper] Run while you still can."),
    ("long", "narrator",
     "Long ago, before the towers fell and the rivers turned to ash, this kingdom "
     "knew peace. The old king ruled with a fair hand, and the harvests were plenty. "
     "But greed festers in quiet places, and one by one the great houses turned upon "
     "each other, until nothing remained but ruin and the slow creeping cold."),
]


def main():
    t0 = time.perf_counter()
    engine = synth.Maya1Engine()
    print(f"SNAC load: {time.perf_counter() - t0:.2f}s; upstream ok: {engine.upstream_ok()}")
    print(f"{'label':10} {'voice':14} {'chars':>5} {'wall_s':>7} {'audio_s':>8} {'RTF':>6}")
    for label, voice, text in LINES:
        t0 = time.perf_counter()
        wav = engine.render(text, voice)
        wall = time.perf_counter() - t0
        dur = synth.duration_s(wav)
        print(f"{label:10} {voice:14} {len(text):>5} {wall:>7.2f} {dur:>8.2f} {wall / dur:>6.2f}")


if __name__ == "__main__":
    main()
