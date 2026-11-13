#!/bin/bash
# Package Sticky.app as a zip for a GitHub release (and the Homebrew cask).
#
#   app/release.sh
#       Ad-hoc signed: Sticky-VERSION-unsigned.zip. Fine for trying it out;
#       macOS blocks it on other Macs until the user allows it in
#       System Settings → Privacy & Security → Open Anyway.
#
#   STICKY_SIGN_IDENTITY="Developer ID Application: Your Name (TEAMID)" \
#   STICKY_NOTARY_PROFILE=sticky app/release.sh
#       Developer ID signed with the hardened runtime, notarized by Apple,
#       ticket stapled: Sticky-VERSION.zip, which opens normally anywhere.
#
# One-time setup for notarization (needs an Apple Developer account):
#   xcrun notarytool store-credentials sticky --apple-id YOU@EXAMPLE.COM --team-id TEAMID
# (it asks for an app-specific password from appleid.apple.com).
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
version="$(sed -n 's/^version = "\(.*\)"/\1/p' "$here/../pyproject.toml")"
app="$here/build/Sticky.app"
dist="$here/build/dist"
rm -rf "$dist" && mkdir -p "$dist"

"$here/build.sh"
xattr -cr "$app"   # no stray extended attributes in the signature or the zip

if [ -n "${STICKY_SIGN_IDENTITY:-}" ]; then
  echo "Signing with: $STICKY_SIGN_IDENTITY"
  codesign --force --options runtime --timestamp --sign "$STICKY_SIGN_IDENTITY" \
    --identifier dev.sticky.bar "$app"
  codesign --verify --strict --verbose=2 "$app"
  zip="$dist/Sticky-$version.zip"
  ditto -c -k --norsrc --noextattr --keepParent "$app" "$zip"
  if [ -n "${STICKY_NOTARY_PROFILE:-}" ]; then
    echo "Submitting to Apple for notarization (usually a few minutes)…"
    xcrun notarytool submit "$zip" --keychain-profile "$STICKY_NOTARY_PROFILE" --wait
    xcrun stapler staple "$app"
    xcrun stapler validate "$app"
    rm "$zip" && ditto -c -k --norsrc --noextattr --keepParent "$app" "$zip"   # re-zip with the stapled ticket
    spctl --assess --type execute --verbose=2 "$app"
  else
    echo "warning: STICKY_NOTARY_PROFILE not set; signed but not notarized" >&2
  fi
else
  zip="$dist/Sticky-$version-unsigned.zip"
  ditto -c -k --norsrc --noextattr --keepParent "$app" "$zip"
fi

echo
echo "Release file: $zip"
echo "sha256:       $(shasum -a 256 "$zip" | cut -d' ' -f1)"
