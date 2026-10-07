#!/usr/bin/env bash
# Cleanly stop the aether-hub stack (containers are kept, data is untouched).
#
# Usage: scripts/stop.sh            stop the containers
#        scripts/stop.sh --poweroff stop, then power off the Pi
#
# Restart policy is `always`: a manual stop lasts until the next reboot or
# Docker restart. Start again with scripts/start.sh.

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

docker compose stop
docker compose ps

if [[ "${1:-}" == "--poweroff" ]]; then
    echo "Powering off..."
    sudo systemctl poweroff
fi
