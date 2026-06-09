# image-api: thin REST adapter in front of ComfyUI. No GPU, no ROCm here -- all the
# heavy lifting happens in the `image` (ComfyUI) container. Keep this small and boring.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY workflows ./workflows

EXPOSE 9001
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9001"]
