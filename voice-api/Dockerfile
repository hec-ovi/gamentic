# Gamentic voice service - Kokoro-82M on CPU. No GPU: the iGPU stays free for the
# LLM and ComfyUI. libgomp1 is onnxruntime's only system dep; soundfile and the
# espeak phonemizer lib ship inside their wheels.
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY *.py ./

# Model files are mounted read-only; generated audio + the registry live in /data.
ENV KOKORO_MODEL=/models/kokoro/kokoro-v1.0.onnx \
    KOKORO_VOICES=/models/kokoro/voices-v1.0.bin \
    VOICE_DATA_DIR=/data \
    VOICE_VOCAL_DIR=/data/vocalizations \
    KOKORO_THREADS=4

EXPOSE 8080
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
