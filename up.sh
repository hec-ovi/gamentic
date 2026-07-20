#!/usr/bin/env bash
# up.sh - launcher for the Gamentic stack.
#
#   ./up.sh         build + start the full local stack (all inference containers)
#   ./up.sh harness [llm-url] [model]
#                   the WHOLE stack except llm-text: orchestrator, frontend,
#                   ComfyUI + image-api, Maya voice + voice-api all run; only
#                   text inference comes from an external OpenAI-compatible
#                   server (default http://host.docker.internal:8090/v1 = the
#                   llama-vulkan-strix stack on this box). Model defaults to
#                   LLM_ALIAS from .env.
#   ./up.sh down    stop and remove the whole stack, whichever mode is running
#
# The profile trick is one rule: llm-text alone carries profiles: ["local"].
# Default mode selects it (COMPOSE_PROFILES=local); harness mode selects a
# profile nothing carries, so llm-text drops out and everything else runs.
set -euo pipefail
cd "$(dirname "$0")"

[ -f .env ] || { echo "no .env here - cp .env.example .env and edit it first" >&2; exit 1; }

if [ "${1:-}" = "down" ]; then
    COMPOSE_PROFILES=local docker compose down
    exit 0
fi

if [ "${1:-}" = "harness" ]; then
    url="${2:-http://host.docker.internal:8090/v1}"
    echo "==> harness mode: the whole stack except llm-text; text inference at $url"
    # reachability hint, not a gate: 8090 maps to localhost on the host side
    probe=$(printf '%s' "$url" | sed 's|host.docker.internal|localhost|')
    curl -fsS -m 5 "$probe/models" >/dev/null 2>&1 \
        || echo "WARNING: $probe is not answering - start the external llama server first (llama-vulkan-strix: docker compose up -d) or text turns will fail."
    echo "==> stopping the local text-inference leftover"
    COMPOSE_PROFILES=local docker compose rm -sf llm-text >/dev/null 2>&1 || true
    export COMPOSE_PROFILES=harness
    export TEXT_PROVIDER=local TEXT_BASE_URL="$url"
    [ -n "${3:-}" ] && export TEXT_MODEL="$3"
    docker compose up -d --build
    echo
    docker compose ps
    echo
    echo "frontend     http://localhost:5173"
    echo "orchestrator http://localhost:8000"
    echo "text model   $url (external llama server; images + voice run locally)"
    exit 0
fi

echo "==> starting the full local stack"
COMPOSE_PROFILES=local docker compose up -d --build
echo
COMPOSE_PROFILES=local docker compose ps
echo
echo "frontend     http://localhost:5173"
echo "orchestrator http://localhost:8000"
