#!/usr/bin/env bash
# Resolve model credentials and the base URL the agent must use from INSIDE a
# container, then emit them for `harbor run --agent-env`.
#
# The sandbox's anonymizer proxy is published on loopback
# (ANTHROPIC_BASE_URL=http://localhost:PORT), and inside a container
# `localhost` is the container itself -- so every model
# call dies on connection-refused and Harbor reports UnknownApiError, which is
# indistinguishable from a bad key. Rewriting the loopback host to the rootless
# docker host alias is the whole fix.
#
# Usage:
#   proxy_setup.sh [--out-dir DIR] [--no-preflight] [--host-alias IP]
#                  [--anthropic-auth api_key|bearer]

set -uo pipefail

PREFLIGHT="true"
OUT_DIR="."
HOST_ALIAS="${FLC_HOST_ALIAS:-10.0.2.2}"
ANTHROPIC_AUTH_STYLE="${ANTHROPIC_AUTH_STYLE:-api_key}"
SETTINGS_JSON="${SETTINGS_JSON:-$HOME/.claude/settings.json}"

log()  { echo "[proxy] $*" >&2; }
warn() { echo "[proxy] WARNING: $*" >&2; }
die()  { echo "[proxy] FATAL: $*" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --out-dir)          OUT_DIR="${2:?}"; shift 2 ;;
    --no-preflight)     PREFLIGHT="false"; shift ;;
    --host-alias)       HOST_ALIAS="${2:?}"; shift 2 ;;
    --anthropic-auth)   ANTHROPIC_AUTH_STYLE="${2:?}"; shift 2 ;;
    -h|--help)          sed -n '2,20p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "unknown arg: $1" ;;
  esac
done

mkdir -p "$OUT_DIR"
OUT_DIR="$(cd "$OUT_DIR" && pwd)"
ENV_SH="$OUT_DIR/.flc_proxy_env.sh"
ENV_JSON="$OUT_DIR/.flc_proxy_agent_env.json"

command -v python3 >/dev/null 2>&1 || die "python3 is required"

# --- 1) credentials: live env first, then settings.json's .env block ----------
read_settings_env() {
  [ -f "$SETTINGS_JSON" ] || return 0
  python3 - "$SETTINGS_JSON" "$1" <<'PY'
import json, sys
try:
    d = json.load(open(sys.argv[1]))
except Exception:
    sys.exit(0)
v = (d.get("env") or {}).get(sys.argv[2])
if v:
    print(v)
PY
}

: "${ANTHROPIC_API_KEY:=$(read_settings_env ANTHROPIC_API_KEY)}"
: "${ANTHROPIC_BASE_URL:=$(read_settings_env ANTHROPIC_BASE_URL)}"
: "${OPENAI_API_KEY:=$(read_settings_env OPENAI_API_KEY)}"
: "${OPENAI_BASE_URL:=$(read_settings_env OPENAI_BASE_URL)}"
: "${OPENAI_API_BASE:=$(read_settings_env OPENAI_API_BASE)}"

ANON_KEY="${ANTHROPIC_API_KEY:-${OPENAI_API_KEY:-}}"
ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-$ANON_KEY}"
OPENAI_API_KEY="${OPENAI_API_KEY:-$ANON_KEY}"
ANTHROPIC_BASE_URL="${ANTHROPIC_BASE_URL:-${OPENAI_BASE_URL:-${OPENAI_API_BASE:-}}}"
OPENAI_BASE_URL="${OPENAI_BASE_URL:-${OPENAI_API_BASE:-$ANTHROPIC_BASE_URL}}"

if [ -z "$ANTHROPIC_BASE_URL$OPENAI_BASE_URL" ] || [ -z "$ANON_KEY" ]; then
  die "no model credentials found. Set ANTHROPIC_API_KEY + ANTHROPIC_BASE_URL " \
      "(or the OPENAI_ equivalents) in the environment or in $SETTINGS_JSON's .env block."
fi

# --- 2) loopback -> host alias -----------------------------------------------
url_field() { python3 - "$1" "$2" <<'PY'
import sys
from urllib.parse import urlparse
u = urlparse(sys.argv[1]); print(getattr(u, sys.argv[2]) or "")
PY
}

in_container_url() {
  local base="$1"
  [ -n "$base" ] || { echo ""; return 0; }
  local host
  host="$(url_field "$base" hostname)"
  case "$host" in
    localhost|127.0.0.1|0.0.0.0) : ;;
    *) echo "$base"; return 0 ;;
  esac
  local scheme port path hostport
  scheme="$(url_field "$base" scheme)"; port="$(url_field "$base" port)"; path="$(url_field "$base" path)"
  hostport="$HOST_ALIAS"
  [ -n "$port" ] && hostport="$HOST_ALIAS:$port"
  log "rewrote loopback $host${port:+:$port} -> $hostport"
  echo "${scheme}://${hostport}${path}"
}

ANTHROPIC_BASE_INCONTAINER="$(in_container_url "$ANTHROPIC_BASE_URL")"
OPENAI_BASE_INCONTAINER="$(in_container_url "$OPENAI_BASE_URL")"

# --- 3) preflight from a throwaway container ---------------------------------
# Worth one alpine pull: it turns "the run failed after 40 minutes" into "the
# credentials are wrong, here is the status code", before anything is spent.
if [ "$PREFLIGHT" = "true" ] && command -v docker >/dev/null 2>&1 && [ -n "$OPENAI_BASE_INCONTAINER" ]; then
  # K is passed by name, not by value: a value here would sit in the docker
  # command line, readable by any other process on the machine, and be kept in
  # `docker inspect` for the life of the container.
  code="$(K="$OPENAI_API_KEY" docker run --rm \
    -e U="${OPENAI_BASE_INCONTAINER%/}/chat/completions" -e K \
    -e D='{"model":"gpt-4o-mini","messages":[{"role":"user","content":"ping"}],"max_completion_tokens":8}' \
    alpine:latest sh -c 'apk add --no-cache curl >/dev/null 2>&1; curl -s -m 25 -o /dev/null -w "%{http_code}" -X POST "$U" -H "Content-Type: application/json" -H "Authorization: Bearer $K" --data "$D"' \
    2>/dev/null || echo 000)"
  case "$code" in
    000) warn "preflight got no response at $OPENAI_BASE_INCONTAINER -- the container cannot reach the proxy" ;;
    2*|4*) log "preflight reached the gateway (HTTP $code)" ;;
    *)   log "preflight: HTTP $code" ;;
  esac
else
  log "preflight skipped"
fi

# --- 4) emit ------------------------------------------------------------------
# This file holds the keys in the clear and is created private.
(
  umask 077
  {
    echo "# sourced before harbor run: real keys, so Harbor can expand the \${VAR} placeholders."
    echo "export ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY:+\"$ANTHROPIC_API_KEY\"}"
    echo "export OPENAI_API_KEY=${OPENAI_API_KEY:+\"$OPENAI_API_KEY\"}"
  } > "$ENV_SH"
)
chmod 600 "$ENV_SH" 2>/dev/null || true

ANTHROPIC_BASE_INCONTAINER="$ANTHROPIC_BASE_INCONTAINER" \
OPENAI_BASE_INCONTAINER="$OPENAI_BASE_INCONTAINER" \
ANTHROPIC_AUTH_STYLE="$ANTHROPIC_AUTH_STYLE" \
python3 - "$ENV_JSON" <<'PY'
import json, os, sys
env = {}
o = os.environ.get("OPENAI_BASE_INCONTAINER")
if o:
    env["OPENAI_API_KEY"] = "${OPENAI_API_KEY}"
    env["OPENAI_BASE_URL"] = o
    env["OPENAI_API_BASE"] = o
a = os.environ.get("ANTHROPIC_BASE_INCONTAINER")
if a:
    # Exactly one credential variable, never both. The Anthropic clients resolve
    # ANTHROPIC_API_KEY first and ANTHROPIC_AUTH_TOKEN second; with both set
    # they send x-api-key and Authorization together and the API returns 401.
    if os.environ.get("ANTHROPIC_AUTH_STYLE") == "bearer":
        env["ANTHROPIC_AUTH_TOKEN"] = "${ANTHROPIC_API_KEY}"
    else:
        env["ANTHROPIC_API_KEY"] = "${ANTHROPIC_API_KEY}"
    # Both spellings: ANTHROPIC_BASE_URL is what the Anthropic SDK and
    # claude-code read, ANTHROPIC_API_BASE is what litellm reads, and an agent
    # routed through litellm without it dials api.anthropic.com from inside a
    # container that cannot reach it.
    env["ANTHROPIC_BASE_URL"] = a
    env["ANTHROPIC_API_BASE"] = a
json.dump(env, open(sys.argv[1], "w"), indent=2)
PY

log "ready -- env $ENV_SH, agent env $ENV_JSON"
