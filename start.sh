#!/usr/bin/env bash
set -euo pipefail
echo "Booting Phoenix Recruiting API (v3.1.2) on port ${PORT:-8080}"
exec uvicorn application:app --host 0.0.0.0 --port "${PORT:-8080}" --log-level info
