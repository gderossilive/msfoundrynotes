#!/usr/bin/env bash

set -euo pipefail

fail_scenario_layout() {
  printf '%s\n' "$1" >&2
  return 2
}

resolve_scenario_lane() {
  local repo_root="$1"
  local lane_reference="$2"
  local lane_dir level_dir lane_name level_name lane_level lane_profile lane_slug lane_suffix level_slug

  [[ "$lane_reference" != /* ]] || {
    fail_scenario_layout 'Scenario lane must be relative to scenarios/.'
    return
  }

  lane_dir="$repo_root/scenarios/$lane_reference"
  [[ -f "$lane_dir/azure.yaml" ]] || {
    fail_scenario_layout "Scenario lane '$lane_reference' does not contain azure.yaml."
    return
  }

  level_dir=$(dirname "$lane_dir")
  lane_name=$(basename "$lane_dir")
  level_name=$(basename "$level_dir")

  if [[ ! "$level_name" =~ ^([0-9]{2})-(.+)$ ]]; then
    fail_scenario_layout "Level directory '$level_name' must start with a two-digit identifier."
    return
  fi
  level_slug="${BASH_REMATCH[2]}"

  if [[ ! "$lane_name" =~ ^([0-9]{2})([abc])-(.+)-(public|managed-vnet|byo-vnet)$ ]]; then
    fail_scenario_layout "Lane directory '$lane_name' has an invalid name."
    return
  fi
  lane_level="${BASH_REMATCH[1]}"
  lane_profile="${BASH_REMATCH[2]}"
  lane_slug="${BASH_REMATCH[3]}"
  lane_suffix="${BASH_REMATCH[4]}"

  [[ "$lane_level" == "${level_name%%-*}" ]] || {
    fail_scenario_layout "Lane '$lane_name' does not match level '$level_name'."
    return
  }
  [[ "$lane_slug" == "$level_slug" ]] || {
    fail_scenario_layout "Lane '$lane_name' does not use level slug '$level_slug'."
    return
  }

  case "$lane_profile:$lane_suffix" in
    a:public|b:managed-vnet|c:byo-vnet) ;;
    *)
      fail_scenario_layout "Lane '$lane_name' has an invalid profile and network suffix combination."
      return
      ;;
  esac

  SCENARIO_LEVEL_DIR="$level_dir"
  SCENARIO_LANE_DIR="$lane_dir"
  SCENARIO_LEVEL_ID="$lane_level"
  SCENARIO_LANE_ID="${lane_level}${lane_profile}"
  SCENARIO_NETWORK_PROFILE="$lane_profile"
}