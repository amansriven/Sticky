#!/bin/bash
# Render every page of the app to PNGs, light and dark, for design review.
#   app/snapshot.sh OUTPUT_DIR [extra client ids…]
# Uses live data from `sticky report`. Set STICKY_BIN to use a source checkout.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
out="${1:?usage: snapshot.sh OUTPUT_DIR [client ids…]}"; shift
swift build --package-path "$here" 2>&1 | grep -E 'error' || true
bin="$(swift build --package-path "$here" --show-bin-path)/StickyBar"
sticky="${STICKY_BIN:-$(command -v sticky)}"
apps=$("$sticky" report --compact | python3 -c '
import json, sys
r = json.load(sys.stdin)
ids = [p["client_id"] for p in r["problems"]]
print("\n".join(dict.fromkeys(ids)))')
pages=(overview problems menu settings)
while read -r id; do [ -n "$id" ] && pages+=("app:$id"); done <<< "$apps"
for id in "$@"; do pages+=("app:$id"); done
for page in "${pages[@]}"; do
  for mode in "" "--dark"; do
    "$bin" --snapshot "$out" --page "$page" $mode >/dev/null
  done
done
ls "$out"
