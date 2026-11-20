# Homebrew cask for the Sticky Mac app. Published copy: amansriven/homebrew-tap,
# Casks/sticky-app.rb. On release: set `version` and `sha256` from the output of
# app/release.sh, and upload the zip to the GitHub release.
#
# The app isn't signed with a Developer ID yet, so the url points at the
# "-unsigned" zip and the caveats explain Gatekeeper's one-time "Open Anyway".
# Once it's notarized: drop "-unsigned" from the url and the Gatekeeper caveat.
#
# No postflight: Homebrew runs install steps in a sandbox with a fake home
# folder, where `sticky install-agent` can't load a LaunchAgent. The app's
# Overview has a Start Recording button instead.
cask "sticky-app" do
  version "0.3.1"
  sha256 "80c9347e6c2be1dc0c3ada6d9fd15ed7f1dba4182c8f567a853b74097796116b"

  url "https://github.com/amansriven/Sticky/releases/download/v#{version}/Sticky-#{version}-unsigned.zip"
  name "Sticky"
  desc "Explains why apps keep asking for permissions, and how to make them stick"
  homepage "https://github.com/amansriven/Sticky"

  depends_on formula: "amansriven/tap/sticky"
  depends_on macos: :sonoma

  app "Sticky.app"

  uninstall quit: "dev.sticky.bar"

  zap launchctl: "dev.sticky.recorder",
      trash:     [
        "~/Library/Application Support/Sticky",
        "~/Library/Logs/Sticky",
        "~/Library/Preferences/dev.sticky.bar.plist",
      ]

  caveats <<~EOS
    Sticky isn't notarized by Apple yet, so the first time you open it macOS
    says it can't check it for malicious software. To open it once:
      1. Open Sticky from Applications and click Done. Not "Move to Trash":
         it's the highlighted button (Return clicks it too) and it deletes
         the app.
      2. In System Settings → Privacy & Security, click "Open Anyway" next to
         the message about Sticky, then confirm.
    After that it opens normally. The source is at
    https://github.com/amansriven/Sticky if you'd rather build it yourself.

    Then click Start Recording in Sticky, or run: sticky install-agent
    Sticky can only explain permission requests it saw, so start it early.

    To stop recording: sticky uninstall-agent
  EOS
end
