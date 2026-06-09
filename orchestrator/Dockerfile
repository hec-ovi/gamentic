# Orchestrator: pure-Python FastAPI service. No GPU (it calls llm-text over HTTP).
# Platform baseline: Ubuntu 26.04 LTS stable, Python 3.12 via uv.
FROM ubuntu:26.04

ENV DEBIAN_FRONTEND=noninteractive
ENV VIRTUAL_ENV=/app/.venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
RUN uv venv .venv --python 3.12

COPY requirements.txt .
RUN uv pip install -r requirements.txt

COPY app ./app
COPY prompts ./prompts

# State lives in a mounted volume so games persist across rebuilds.
ENV DB_PATH=/data/gamentic.db
ENV LLM_BASE_URL=http://gamentic-llm-text:8080/v1
ENV LLM_MODEL=gemma-4-12b-heretic
VOLUME ["/data"]

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
