#!/bin/bash
# Build and ad-hoc sign BrokenTool.app. Each build gets a new identity.
#   tools/brokentool/build.sh [tag]     (default tag: current time)
#   (each build is a new identity; see main.c for the modes)
# Then run it with:  tools/brokentool/run.sh
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
tag="${1:-$(date +%Y%m%d-%H%M%S)}"
app="$here/build/BrokenTool.app"
rm -rf "$app"
mkdir -p "$app/Contents/MacOS"
cp "$here/Info.plist" "$app/Contents/Info.plist"
cc -O2 -DBUILD_TAG="\"$tag\"" -framework ApplicationServices -o "$app/Contents/MacOS/BrokenTool" "$here/main.c"
codesign --force --sign - "$app"
echo "Built $app (tag $tag)"
codesign -d -r- "$app" 2>&1 | grep designated
