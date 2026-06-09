#!/bin/bash
set -e

# ECHO: Start Log
echo "=================================================="
echo "   STRIX HALO (RDNA 3.5) COMFYUI BOOTLOADER"
echo "=================================================="

# AUTO-INJECT: Check if HSA Override is missing, and force it.
if [ -z "$HSA_OVERRIDE_GFX_VERSION" ]; then
    echo "[INFO] No GFX version detected. Defaulting to Strix Halo (11.5.1)..."
    export HSA_OVERRIDE_GFX_VERSION=11.5.1
else
    echo "[INFO] GFX Override detected: $HSA_OVERRIDE_GFX_VERSION"
fi

# CHECK: Print GPU Info
echo "[INFO] Checking Python Torch detection..."
python3 -c "import torch; print(f'Device: {torch.cuda.get_device_name(0)}')" || echo "[WARN] GPU detection failed, but proceeding..."

# LAUNCH: Start ComfyUI
#   --bf16-vae      : the FLUX.2 VAE decodes in bf16; prevents OOM/instability on the APU
#   --disable-mmap  : load weights into the 128GB unified RAM instead of mmap, which is
#                     very slow above 64GB on gfx1151 (known ROCm bug). Faster + stabler.
echo "[INFO] Starting ComfyUI..."
exec python main.py --listen --port 8188 --preview-method auto \
    --bf16-vae --disable-mmap "$@"
