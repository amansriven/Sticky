# Homebrew formula for Sticky. The published copy lives in the tap repository
# (github.com/amansriven/homebrew-tap, Formula/sticky.rb); keep them in sync.
# On release: update `url` to the new tag and `sha256` to the tarball's hash.
class Sticky < Formula
  include Language::Python::Virtualenv

  desc "Explain why macOS keeps asking for permissions, and make them stick"
  homepage "https://github.com/amansriven/Sticky"
  url "https://github.com/amansriven/Sticky/archive/refs/tags/v0.2.0.tar.gz"
  sha256 "2a0b98b59397559c4e5c76814e0a678d875797c7f30c539745283dac11639351"
  license "MIT"

  depends_on :macos
  depends_on "python@3.15"

  def install
    virtualenv_install_with_resources
  end

  def caveats
    <<~EOS
      Sticky only sees permission requests made while it is recording.
      Start recording in the background (runs as you; no sudo or Full Disk Access):
        sticky install-agent

      After upgrading Sticky, run `sticky install-agent` again to restart the
      recorder on the new version.

      When an app keeps asking for a permission, or silently lost one:
        sticky why <app>
    EOS
  end

  test do
    assert_match version.to_s, shell_output("#{bin}/sticky --version")
    (testpath/"empty.ndjson").write ""
    assert_match "0 requests", shell_output("#{bin}/sticky parse #{testpath}/empty.ndjson 2>&1")
    assert_match "apple", shell_output("#{bin}/sticky inspect /System/Applications/TextEdit.app")
    ENV["STICKY_DB"] = testpath/"sticky.db"
    assert_match '"problems": []', shell_output("#{bin}/sticky report --since all")
    assert_match "Nothing is ignored", shell_output("#{bin}/sticky ignores")
  end
end
