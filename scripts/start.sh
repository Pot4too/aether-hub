#!/usr/bin/env bash
# Build (if needed) and start the aether-hub stack: mosquitto + ingest + api.
#
# Usage: scripts/start.sh [--no-build]
# Works from any directory; always runs against the repo root.

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

if [[ ! -f .env ]]; then
    echo ".env not found — copying from .env.example"
    cp .env.example .env
fi

# Make sure the bind-mounted data dirs exist and belong to the current user,
# otherwise Docker creates them as root.
DATA_DIR="$(grep -E '^AETHER_DATA_DIR=' .env | tail -n1 | cut -d= -f2-)"
DATA_DIR="${DATA_DIR:-./data}"
mkdir -p "${DATA_DIR}/sqlite" "${DATA_DIR}/mosquitto/data" "${DATA_DIR}/mosquitto/log"

if [[ "${1:-}" == "--no-build" ]]; then
    docker compose up -d
else
    docker compose up --build -d
fi

docker compose ps
echo
echo "API / web UI: http://localhost:8000"
echo "MQTT broker:  localhost:1883"
echo "Logs:         docker compose logs -f"
