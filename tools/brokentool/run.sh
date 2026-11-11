#!/bin/bash
# Launch BrokenTool through LaunchServices, so macOS holds BrokenTool itself
# responsible (not your terminal). Waits for it to finish and prints its output.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
out="$(mktemp -t brokentool)"
open -W -n --stdout "$out" --stderr "$out" "$here/build/BrokenTool.app"
cat "$out"
rm -f "$out"
