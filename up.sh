#!/usr/bin/env bash
# up.sh - mode-aware launcher for the Gamentic stack.
#
#   ./up.sh         build + start the stack for the mode set in .env:
#                     ANNA=false  -> full local stack (GPU inference containers)
#                     ANNA=true   -> orchestrator + frontend + anna-agent + anna-api
#                                    (nothing GPU-shaped is built, pulled or started)
#   ./up.sh down    stop and remove the whole stack, whichever mode is running
#
# The compose profile trick does the service selection; this script adds the two
# things compose cannot do alone: clean up the OTHER mode's containers when the
# boolean was flipped without a down, and retire the standalone infra/anna-agent
# container (same port, same volume) when the stack runs its own copy.
set -euo pipefail
cd "$(dirname "$0")"

[ -f .env ] || { echo "no .env here - cp .env.example .env and edit it first" >&2; exit 1; }

# ANNA from .env, last assignment wins; literal-'false' semantics (mirror compose + app)
anna_raw=$(grep -E '^ANNA=' .env | tail -n1 | cut -d= -f2- | tr -d "[:space:]'\"")
# refuse non-literal values: the app would read them as ON while compose matches
# NO profile at all (neither stack starts) - the one split-brain the trick allows
if [ -n "$anna_raw" ] && [ "$anna_raw" != "true" ] && [ "$anna_raw" != "false" ]; then
    echo "ANNA in .env must be the literal 'true' or 'false' (found: '$anna_raw')." >&2
    echo "The app reads anything non-'false' as on, but compose profiles match only" >&2
    echo "the literal values, so '$anna_raw' would start NO inference services at all." >&2
    exit 1
fi
if [ "$anna_raw" = "true" ]; then mode=anna; else mode=local; fi

# Every profile either mode can produce (plus the current interpolation, in case
# ANNA holds a non-literal truthy value): with this list active, compose sees ALL
# services regardless of the boolean, so cleanup calls reach the other mode too.
ALL_PROFILES="local-inference-anna-false,local-inference-anna-true,anna-agent-anna-false,anna-agent-anna-true,local-inference-anna-${anna_raw:-false},anna-agent-anna-${anna_raw:-false}"

if [ "${1:-}" = "down" ]; then
    COMPOSE_PROFILES="$ALL_PROFILES" docker compose down
    exit 0
fi

if [ "$mode" = anna ]; then
    # the standalone infra/anna-agent compose project holds port 19001 and the
    # shared volume; the stack runs its own copy of the agent now
    if docker ps -a --format '{{.Names}}' | grep -qx anna-agent; then
        echo "==> retiring the standalone anna-agent container (the stack runs its own; sign-in survives on the shared volume)"
        docker rm -f anna-agent >/dev/null
    fi
    echo "==> ANNA mode: stopping any local-inference leftovers"
    COMPOSE_PROFILES="$ALL_PROFILES" docker compose rm -sf llm-text image image-api llm-voice voice-api >/dev/null 2>&1 || true
else
    echo "==> local mode: stopping any Anna leftovers"
    COMPOSE_PROFILES="$ALL_PROFILES" docker compose rm -sf anna-agent anna-api >/dev/null 2>&1 || true
fi

echo "==> starting the $mode stack"
docker compose up -d --build
echo
docker compose ps
echo
echo "frontend     http://localhost:5173"
echo "orchestrator http://localhost:8000  (admin panel: http://localhost:8000/admin)"

if [ "$mode" = anna ]; then
    echo "anna agent   http://localhost:19001"
    connected=$(curl -fsS -m 5 http://127.0.0.1:19001/api/agent/status 2>/dev/null \
        | grep -o '"connected":[a-z]*' | cut -d: -f2 || true)
    if [ "$connected" != "true" ]; then
        echo
        echo "NOTE: the Anna agent is not signed in to its cloud yet. Open"
        echo "      http://localhost:19001 and sign in once (state persists on the"
        echo "      anna-data volume); until then text turns will fail with an"
        echo "      'unauthenticated' error from the adapter."
    fi
fi
