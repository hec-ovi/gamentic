# ComfyUI for AMD Strix Halo (RDNA 3.5 / gfx1151)
# Adapted from hec-ovi/comfyui-strix-docker:
#   - BASE: Ubuntu 26.04 LTS (stable), not ubuntu:rolling
#   - TORCH: TheRock ROCm 7.13 pinned wheels, not the AMD prerelease/nightly index
#   - Python 3.12 managed by uv (system Python on 26.04 is 3.13; ComfyUI + rocm wheels want 3.12)

# BASE: Ubuntu 26.04 LTS stable
FROM ubuntu:26.04

LABEL maintainer="hector"
LABEL description="ComfyUI on Strix Halo (gfx1151), ROCm 7.13 via TheRock, Python 3.12 / uv"

ENV DEBIAN_FRONTEND=noninteractive
ENV UV_CACHE_DIR=/root/.cache/uv
ENV VIRTUAL_ENV=/app/.venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# 1. SYSTEM DEPENDENCIES (minimal)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    wget \
    curl \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 2. UV
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# 3. WORKSPACE
WORKDIR /app

# 4. VIRTUALENV (Python 3.12, downloaded by uv, ignores system 3.13)
RUN uv venv .venv --python 3.12

# 5. PYTORCH - TheRock ROCm 7.13, gfx1151. There is NO stable PyPI index for gfx1151,
#    so the reproducible move is to pin ONE coherent same-date build off the nightly
#    index, not float "latest". The reproducible invariant is the shared
#    +rocm7.13.0a<date> tag. Versions pair by line and MUST match:
#      torch 2.9.1  <-> torchvision 0.24.0 <-> torchaudio 2.9.0   (used here)
#      torch 2.10.0 <-> torchvision 0.25.0 <-> torchaudio 2.10.0
#    Mixing lines (e.g. torch 2.9.1 + torchvision 0.25.0) is an ABI mismatch.
#    20260513 is the newest date carrying the full 2.9.1-line triple for cp312.
#    To bump: pick a date present for all three on the same line:
#      for p in torch torchvision torchaudio; do \
#        curl -fsSL https://rocm.nightlies.amd.com/v2/gfx1151/$p/ | grep rocm7.13.0a<DATE>; done
#    The --index-url is exclusive: torch's deps (numpy, pillow, rocm-sdk libs, ...)
#    all resolve from this same gfx1151 index.
ARG ROCM_INDEX=https://rocm.nightlies.amd.com/v2/gfx1151/
ARG TORCH_VER=2.9.1+rocm7.13.0a20260513
ARG VISION_VER=0.24.0+rocm7.13.0a20260513
ARG AUDIO_VER=2.9.0+rocm7.13.0a20260513
RUN uv pip install --index-url ${ROCM_INDEX} \
    "torch==${TORCH_VER}" \
    "torchvision==${VISION_VER}" \
    "torchaudio==${AUDIO_VER}"

# 6. VERIFY (fail the build if a CPU-only torch slipped in)
RUN python -c "import torch; print(f'Torch: {torch.__version__}'); assert 'rocm' in torch.__version__, 'FATAL: non-ROCm torch installed!'"

# 7. COMFYUI (cloned into a subfolder; '.' holds the .venv)
RUN git clone https://github.com/comfyanonymous/ComfyUI.git ComfyUI

# 8. COMFYUI REQUIREMENTS (from PyPI default; torch already satisfied)
WORKDIR /app/ComfyUI
RUN uv pip install -r requirements.txt

# 9. ENTRYPOINT
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# 10. RUN
EXPOSE 8188
# gfx1151 (Strix Halo) runtime. HSA_OVERRIDE pins the ISA; SDMA off + SVM off are the
# community-standard stability fixes for unified memory (avoids GPU ring timeouts /
# checkerboard artifacts during VAE decode). Overridable from compose.
ENV HSA_OVERRIDE_GFX_VERSION=11.5.1 \
    HSA_ENABLE_SDMA=0 \
    HSA_USE_SVM=0
ENTRYPOINT ["/entrypoint.sh"]
