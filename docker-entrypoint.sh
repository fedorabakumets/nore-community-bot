#!/bin/sh
set -eu

mkdir -p /app/data

if [ "$(id -u)" -eq 0 ]; then
  chown -R botuser:botuser /app/data 2>/dev/null || true
  if command -v runuser >/dev/null 2>&1 && id botuser >/dev/null 2>&1; then
    exec runuser -u botuser -- "$@"
  fi
fi

exec "$@"
