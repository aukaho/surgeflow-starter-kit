#!/usr/bin/env bash
set -euo pipefail

base_url="https://surgeflows.capital"
market="${1:-us}"

case "$market" in
  us|cn|jp|hk) ;;
  *)
    printf 'Market must be us, cn, jp, or hk.\n' >&2
    exit 2
    ;;
esac

printf '\n== Data freshness JSON ==\n'
curl --fail --silent --show-error \
  "$base_url/api/public/snapshots/data-freshness.json"
printf '\n\n== Momentum Hotlist CSV (%s) ==\n' "$market"
curl --fail --silent --show-error \
  "$base_url/api/public/snapshots/momentum-hotlist.csv?market=$market"
printf '\n'
