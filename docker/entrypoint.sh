#!/usr/bin/env bash
set -euo pipefail

uvicorn apps.api.main:app --host 127.0.0.1 --port 8001 &
api_pid=$!

nginx -g 'daemon off;' &
nginx_pid=$!

cleanup() {
  kill "$api_pid" "$nginx_pid" 2>/dev/null || true
  wait "$api_pid" "$nginx_pid" 2>/dev/null || true
}

trap cleanup EXIT INT TERM

status=0
wait -n "$api_pid" "$nginx_pid" || status=$?
exit "$status"
