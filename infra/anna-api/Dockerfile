# anna-api: thin REST adapter giving the Anna agent an OpenAI-compatible face.
# No GPU, no models here -- the agent container does the talking to Anna's cloud.
# Keep this small and boring (same shape as image-api).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 9100
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9100"]
