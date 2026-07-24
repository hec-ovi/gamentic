"""End-to-end tests for fetch-models.sh: the real script, run as the operator runs it.

Downloads are the only thing faked, by a stub `curl` earlier on PATH that records what it
was asked for and writes the URL into the target file. Everything else (reading .env,
resolving the target dir, the skip-if-present rule) is the shipped code path.

Run:  python -m pytest infra/comfyui/tests -q
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "fetch-models.sh"
ROOT = HERE.parents[2]

KLEIN_UNET = "flux-2-klein-4b.safetensors"
KLEIN_CLIP = "qwen_3_4b.safetensors"
KLEIN_VAE = "flux2-vae.safetensors"

STUB_CURL = """#!/usr/bin/env bash
out=""; url=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    -o) out="$2"; shift 2 ;;
    -C|--retry) shift 2 ;;
    -*) shift ;;
    *) url="$1"; shift ;;
  esac
done
echo "$url -> $out" >> "$CURL_LOG"
printf '%s' "$url" > "$out"
"""


@pytest.fixture
def stub_curl(tmp_path):
    """A fake curl first on PATH; yields the log of (url -> destination) it was asked for."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    curl = bin_dir / "curl"
    curl.write_text(STUB_CURL)
    curl.chmod(0o755)
    log = tmp_path / "curl.log"
    log.write_text("")

    def run(*args, env_file=None, extra_env=None):
        env = dict(os.environ)
        env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
        env["CURL_LOG"] = str(log)
        # never let the developer's own .env leak into a test run
        env["ENV_FILE"] = str(env_file) if env_file else str(tmp_path / "absent.env")
        for key in ("COMFY_MODELS_DIR", "COMFY_UNET_NAME", "COMFY_UNET_URL", "COMFY_CLIP_NAME",
                    "COMFY_CLIP_URL", "COMFY_VAE_NAME", "COMFY_VAE_URL"):
            env.pop(key, None)
        env.update(extra_env or {})
        proc = subprocess.run(
            ["bash", str(SCRIPT), *args], capture_output=True, text=True, timeout=60, env=env
        )
        return proc, log.read_text()

    return run


def test_no_env_file_downloads_the_shipped_klein_set(stub_curl, tmp_path):
    dest = tmp_path / "models"
    proc, log = stub_curl(str(dest))
    assert proc.returncode == 0, proc.stderr

    assert (dest / "diffusion_models" / KLEIN_UNET).exists()
    assert (dest / "text_encoders" / KLEIN_CLIP).exists()
    assert (dest / "vae" / KLEIN_VAE).exists()
    # the URLs are the Comfy-Org repacks, not something the stub invented
    assert "huggingface.co/Comfy-Org/flux2-klein" in log
    assert log.count("->") == 3


def test_env_file_names_the_model_set(stub_curl, tmp_path):
    envf = tmp_path / ".env"
    envf.write_text(
        "COMFY_MODELS_DIR=" + str(tmp_path / "store") + "\n"
        "COMFY_UNET_NAME=other-model.safetensors\n"
        "COMFY_UNET_URL=https://example.test/other-model.safetensors\n"
        "COMFY_CLIP_NAME=other-encoder.safetensors\n"
        "COMFY_CLIP_URL=https://example.test/other-encoder.safetensors\n"
        "COMFY_VAE_NAME=other-vae.safetensors\n"
        "COMFY_VAE_URL=https://example.test/other-vae.safetensors\n"
    )
    proc, log = stub_curl(env_file=envf)
    assert proc.returncode == 0, proc.stderr

    store = tmp_path / "store"
    # a whole different model set, downloaded into ComfyUI's own layout, no script edit
    assert (store / "diffusion_models" / "other-model.safetensors").read_text() == (
        "https://example.test/other-model.safetensors"
    )
    assert (store / "text_encoders" / "other-encoder.safetensors").exists()
    assert (store / "vae" / "other-vae.safetensors").exists()
    assert KLEIN_UNET not in log


def test_quoted_and_crlf_env_values_are_read_clean(stub_curl, tmp_path):
    envf = tmp_path / ".env"
    envf.write_bytes(
        b'export COMFY_MODELS_DIR="' + str(tmp_path / "store").encode() + b'"\r\n'
        b'COMFY_UNET_NAME="quoted-model.safetensors"\r\n'
        b"COMFY_UNET_URL=https://example.test/quoted.safetensors\r\n"
    )
    proc, _ = stub_curl(env_file=envf)
    assert proc.returncode == 0, proc.stderr
    assert (tmp_path / "store" / "diffusion_models" / "quoted-model.safetensors").exists()


def test_environment_wins_over_the_env_file(stub_curl, tmp_path):
    envf = tmp_path / ".env"
    envf.write_text("COMFY_UNET_NAME=from-file.safetensors\n")
    dest = tmp_path / "models"
    proc, _ = stub_curl(str(dest), env_file=envf,
                        extra_env={"COMFY_UNET_NAME": "from-shell.safetensors"})
    assert proc.returncode == 0, proc.stderr
    assert (dest / "diffusion_models" / "from-shell.safetensors").exists()
    assert not (dest / "diffusion_models" / "from-file.safetensors").exists()


def test_present_files_are_skipped_so_reruns_are_free(stub_curl, tmp_path):
    dest = tmp_path / "models"
    (dest / "diffusion_models").mkdir(parents=True)
    (dest / "diffusion_models" / KLEIN_UNET).write_text("already here")

    proc, log = stub_curl(str(dest))
    assert proc.returncode == 0, proc.stderr
    assert f"[skip] diffusion_models/{KLEIN_UNET}" in proc.stdout
    assert (dest / "diffusion_models" / KLEIN_UNET).read_text() == "already here"
    assert log.count("->") == 2  # only the two missing ones were fetched


def test_a_relative_models_dir_resolves_under_the_gamentic_folder(stub_curl, tmp_path):
    """Compose reads ./models/comfyui as repo-relative; the script must agree, whatever
    directory the operator happens to be standing in."""
    target = ROOT / "models" / "fetch-models-test"
    models_root_existed = (ROOT / "models").exists()
    envf = tmp_path / ".env"
    envf.write_text("COMFY_MODELS_DIR=./models/fetch-models-test\n")
    try:
        proc, _ = stub_curl(env_file=envf)
        assert proc.returncode == 0, proc.stderr
        assert (target / "diffusion_models" / KLEIN_UNET).exists()
    finally:
        shutil.rmtree(target, ignore_errors=True)
        if not models_root_existed:
            shutil.rmtree(ROOT / "models", ignore_errors=True)
