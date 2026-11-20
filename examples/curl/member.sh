#!/usr/bin/env bash
set -euo pipefail

base_url="https://surgeflows.capital"
api_key="${SURGEFLOW_API_KEY:-sf_live_REPLACE_WITH_YOUR_KEY}"

if [[ "$api_key" == "sf_live_REPLACE_WITH_YOUR_KEY" ]]; then
  printf 'Set SURGEFLOW_API_KEY to your private member key first.\n' >&2
  exit 2
fi

printf '\n== Key plan and usage ==\n'
curl --fail --silent --show-error \
  -H "Authorization: Bearer $api_key" \
  "$base_url/api/v1/me"
printf '\n\n== Momentum Hotlist (us) ==\n'
curl --fail --silent --show-error \
  -H "Authorization: Bearer $api_key" \
  "$base_url/api/v1/markets/us/hotlist"
printf '\n'
