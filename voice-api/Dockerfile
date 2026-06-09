# Gamentic voice service - Maya1 SNAC decoder on CPU. The 3B token model runs in
# its own llama.cpp server-vulkan container (llm-voice); this image only needs
# CPU torch + the ~80MB SNAC codec, baked in so startup never hits the network.
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Bake the SNAC decoder weights into the image.
ENV HF_HOME=/opt/hf
RUN python -c "from snac import SNAC; SNAC.from_pretrained('hubertsiuzdak/snac_24khz')"

COPY *.py ./

# Generated audio + the character registry live in /data.
ENV MAYA1_URL=http://llm-voice:8080 \
    VOICE_DATA_DIR=/data

EXPOSE 8080
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
