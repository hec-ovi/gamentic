"""Quick CPU benchmark for Kokoro on this box.

Measures model load time, per-line generation time, audio duration, and RTF
(real-time factor = gen_time / audio_seconds; < 1.0 means faster than realtime).
Run inside the venv: .venv/bin/python bench.py
"""
import time
import os

MODEL = os.environ.get("KOKORO_MODEL", "/home/hec/models/kokoro/kokoro-v1.0.onnx")
VOICES = os.environ.get("KOKORO_VOICES", "/home/hec/models/kokoro/voices-v1.0.bin")

# Representative game lines: a short bark, a normal line, a long narration.
LINES = [
    ("short", "af_heart", "You shall not pass!"),
    ("normal", "am_adam", "The tavern door creaks open. A hooded figure steps inside, shaking rain from their cloak, and scans the room with cold grey eyes."),
    ("long", "bm_george", "Long ago, before the towers fell and the rivers turned to ash, this kingdom knew peace. The old king ruled with a fair hand, and the harvests were plenty. But greed festers in quiet places, and one by one the great houses turned upon each other, until nothing remained but ruin and the slow creeping cold that now grips these lands."),
]

def main():
    from kokoro_onnx import Kokoro
    t0 = time.perf_counter()
    k = Kokoro(MODEL, VOICES)
    load_s = time.perf_counter() - t0
    print(f"model load: {load_s:.2f}s")
    print(f"threads (OMP/onnx): {os.environ.get('OMP_NUM_THREADS','default')}")
    print(f"{'label':8} {'voice':10} {'chars':>5} {'gen_s':>7} {'audio_s':>8} {'RTF':>6} {'xRT':>6}")
    # warmup (first call pays one-time graph/phonemizer init)
    k.create("Warmup.", voice="af_heart", speed=1.0, lang="en-us")
    for label, voice, text in LINES:
        t0 = time.perf_counter()
        samples, sr = k.create(text, voice=voice, speed=1.0, lang="en-us")
        gen_s = time.perf_counter() - t0
        audio_s = len(samples) / sr
        rtf = gen_s / audio_s if audio_s else float("nan")
        print(f"{label:8} {voice:10} {len(text):>5} {gen_s:>7.3f} {audio_s:>8.2f} {rtf:>6.3f} {1/rtf:>5.1f}x")

if __name__ == "__main__":
    main()
