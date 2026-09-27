#!/usr/bin/env bash
set -Eeuo pipefail
scenario_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
repo_root=$(cd "$scenario_root/../../.." && pwd)
exec "$repo_root/scripts/test-scenario.sh" "$scenario_root" "${1:---static}"
