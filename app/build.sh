#!/bin/bash
# Build Sticky.app (the menu bar app) with the command-line tools; no Xcode needed.
#   app/build.sh            release build into app/build/Sticky.app
# Run it with:  open app/build/Sticky.app
# To use a sticky command other than Homebrew's (e.g. a source checkout):
#   open --env STICKY_BIN=/path/to/sticky app/build/Sticky.app
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
cd "$here"
version="$(sed -n 's/^version = "\(.*\)"/\1/p' ../pyproject.toml)"

swift build -c release --product StickyBar 2>&1 | grep -vE 'ld: warning: search path' || true
bin="$(swift build -c release --show-bin-path)/StickyBar"

app="$here/build/Sticky.app"
rm -rf "$app"
mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources"
cp "$bin" "$app/Contents/MacOS/StickyBar"
cat > "$app/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>CFBundleIdentifier</key>
	<string>dev.sticky.bar</string>
	<key>CFBundleName</key>
	<string>Sticky</string>
	<key>CFBundleDisplayName</key>
	<string>Sticky</string>
	<key>CFBundleExecutable</key>
	<string>StickyBar</string>
	<key>CFBundlePackageType</key>
	<string>APPL</string>
	<key>CFBundleShortVersionString</key>
	<string>$version</string>
	<key>CFBundleVersion</key>
	<string>$version</string>
	<key>LSMinimumSystemVersion</key>
	<string>14.0</string>
	<key>LSUIElement</key>
	<true/>
	<key>NSHumanReadableCopyright</key>
	<string>MIT License</string>
</dict>
</plist>
PLIST
# Ad-hoc signed for local use. A public build needs a Developer ID signature
# and notarization; an ad-hoc app is exactly what Sticky's R6 warns about.
codesign --force --sign - --identifier dev.sticky.bar "$app" 2>&1 | grep -v 'replacing existing signature' || true
echo "Built $app ($version)"
