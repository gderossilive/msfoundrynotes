#!/usr/bin/env bash

set -euo pipefail

if [[ $# -ne 2 ]]; then
  printf 'Usage: %s <create|cleanup> <azd-environment-name>\n' "$0" >&2
  exit 2
fi

exec "$(dirname "${BASH_SOURCE[0]}")/manage-second-caller.sh" 00c "$1" "$2"
