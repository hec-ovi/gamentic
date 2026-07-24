#!/usr/bin/env bash
# Download the ComfyUI model set named in .env into the persistent ComfyUI models dir.
# Idempotent: existing files are skipped, partial ones resume.
#
# The defaults are the FLUX.2 Klein 4B (distilled) set the shipped workflow template uses
# (Comfy-Org repacks, ~16GB total: 7.75 + 8.04 + 0.34). Swapping models is a config change:
# point COMFY_UNET_NAME / COMFY_UNET_URL (and the clip / vae pairs) somewhere else in .env,
# run this, then restart image-api - it patches those filenames into the template's loader
# nodes at boot, so the template itself never has to be touched.
#
# Usage:  ./fetch-models.sh [COMFY_MODELS_DIR]
#         ENV_FILE=/path/to/.env ./fetch-models.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT/.env}"

# One key out of .env, unless it is already set in the environment (which wins). Not a
# shell source: an .env is data, and sourcing it would run whatever it happens to contain.
env_get() {
  local key="$1" default="$2" val="${!1-}"
  if [[ -z "$val" && -f "$ENV_FILE" ]]; then
    val="$(grep -E "^[[:space:]]*(export[[:space:]]+)?${key}=" "$ENV_FILE" | tail -n 1 | cut -d= -f2- || true)"
    val="${val%$'\r'}"                     # an .env saved on Windows carries CRLF
    val="${val#\"}"; val="${val%\"}"
    val="${val#\'}"; val="${val%\'}"
  fi
  printf '%s' "${val:-$default}"
}

HF="https://huggingface.co"
DEST="${1:-$(env_get COMFY_MODELS_DIR "$ROOT/models/comfyui")}"
# A relative dir means "under the gamentic folder", the same way compose reads it.
[[ "$DEST" = /* ]] || DEST="$ROOT/${DEST#./}"

UNET_NAME="$(env_get COMFY_UNET_NAME "flux-2-klein-4b.safetensors")"
UNET_URL="$(env_get COMFY_UNET_URL "$HF/Comfy-Org/flux2-klein/resolve/main/split_files/diffusion_models/flux-2-klein-4b.safetensors")"
CLIP_NAME="$(env_get COMFY_CLIP_NAME "qwen_3_4b.safetensors")"
CLIP_URL="$(env_get COMFY_CLIP_URL "$HF/Comfy-Org/flux2-klein/resolve/main/split_files/text_encoders/qwen_3_4b.safetensors")"
VAE_NAME="$(env_get COMFY_VAE_NAME "flux2-vae.safetensors")"
VAE_URL="$(env_get COMFY_VAE_URL "$HF/Comfy-Org/flux2-dev/resolve/main/split_files/vae/flux2-vae.safetensors")"

# subfolder | filename | url. The subfolders are ComfyUI's own layout, not a choice.
FILES=(
  "diffusion_models|$UNET_NAME|$UNET_URL"
  "text_encoders|$CLIP_NAME|$CLIP_URL"
  "vae|$VAE_NAME|$VAE_URL"
)

echo "[fetch-models] target: $DEST"
[[ -f "$ENV_FILE" ]] && echo "[fetch-models] names read from: $ENV_FILE"
for entry in "${FILES[@]}"; do
  IFS='|' read -r sub name url <<< "$entry"
  mkdir -p "$DEST/$sub"
  out="$DEST/$sub/$name"
  if [[ -s "$out" ]]; then
    echo "[skip] $sub/$name already present"
    continue
  fi
  echo "[get ] $sub/$name"
  # -C - resumes a partial download; -L follows the HF redirect to the CDN.
  curl -fL -C - --retry 3 -o "$out" "$url"
done

echo "[fetch-models] done."
echo "Tip: a smaller text encoder (qwen_3_4b_fp4_flux2.safetensors, 3.85GB) exists in the"
echo "same repo if you want to trim VRAM; set COMFY_CLIP_NAME + COMFY_CLIP_URL to it."
