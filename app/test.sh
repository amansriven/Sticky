#!/bin/bash
# Run the Swift tests. Passes Swift Testing's macro plugin folder explicitly:
# with the command-line tools (no Xcode) the compiler occasionally failed to
# find it ("plugin for module 'TestingMacros' not found").
set -euo pipefail
cd "$(dirname "$0")"
plugins="$(xcrun --find swift | xargs dirname)/../lib/swift/host/plugins/testing"
swift test -Xswiftc -plugin-path -Xswiftc "$plugins" "$@"
