#!/usr/bin/env bash
# Download the FLUX.2 Klein 4B (distilled) model set into the persistent ComfyUI
# models dir. Idempotent: existing files are skipped. URLs are the ones the official
# ComfyUI Klein template points at (Comfy-Org repacks).
#
# Usage:  ./fetch-models.sh [COMFY_MODELS_DIR]
# Default dir matches infra/.env (COMFY_MODELS_DIR).
set -euo pipefail

DEST="${1:-${COMFY_MODELS_DIR:-/home/hec/models/comfyui}}"
HF="https://huggingface.co"

# subfolder | filename | hf repo path
FILES=(
  "diffusion_models|flux-2-klein-4b.safetensors|Comfy-Org/flux2-klein/resolve/main/split_files/diffusion_models/flux-2-klein-4b.safetensors"
  "text_encoders|qwen_3_4b.safetensors|Comfy-Org/flux2-klein/resolve/main/split_files/text_encoders/qwen_3_4b.safetensors"
  "vae|flux2-vae.safetensors|Comfy-Org/flux2-dev/resolve/main/split_files/vae/flux2-vae.safetensors"
)

echo "[fetch-models] target: $DEST"
for entry in "${FILES[@]}"; do
  IFS='|' read -r sub name path <<< "$entry"
  mkdir -p "$DEST/$sub"
  out="$DEST/$sub/$name"
  if [[ -s "$out" ]]; then
    echo "[skip] $sub/$name already present"
    continue
  fi
  echo "[get ] $sub/$name"
  # -C - resumes a partial download; -L follows the HF redirect to the CDN.
  curl -fL -C - --retry 3 -o "$out" "$HF/$path"
done

echo "[fetch-models] done. ~16GB total (7.75 + 8.04 + 0.34)."
echo "Tip: a smaller text encoder (qwen_3_4b_fp4_flux2.safetensors, 3.85GB) exists in the"
echo "same repo if you want to trim VRAM; update the CLIPLoader name in the workflow to match."
