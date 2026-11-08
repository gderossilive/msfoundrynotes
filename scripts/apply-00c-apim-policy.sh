#!/usr/bin/env bash

set -euo pipefail

if [[ $# -ne 1 ]]; then
  printf 'Usage: %s <azd-environment-name>\n' "$0" >&2
  exit 2
fi

exec "$(dirname "${BASH_SOURCE[0]}")/apply-gateway-policy.sh" 00c "$1"
