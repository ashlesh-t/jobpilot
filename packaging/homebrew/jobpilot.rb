# Homebrew formula for a tap: `brew install ashlesh-t/tap/jobpilot`.
# Thin wrapper — installs the PyPI package into an isolated virtualenv and links `jobpilot`.
# Put this in a tap repo named `homebrew-tap` (ashlesh-t/homebrew-tap) as Formula/jobpilot.rb.
class Jobpilot < Formula
  include Language::Python::Virtualenv

  desc "Automated job-hunt pipeline for Claude Code (scrape → score → tailor → notify)"
  homepage "https://github.com/ashlesh-t/jobpilot"
  url "https://files.pythonhosted.org/packages/source/c/claude-jobpilot/claude_jobpilot-1.6.0.tar.gz"
  sha256 "REPLACE_WITH_SDIST_SHA256"   # `brew fetch` / shasum -a 256 on publish
  license "MIT"

  depends_on "python@3.12"

  def install
    # Simple, maintainable install: create a venv and pip-install the package (+deps) into it.
    venv = virtualenv_create(libexec, "python3.12")
    system libexec/"bin/pip", "install", "claude-jobpilot[server]==#{version}"
    bin.install_symlink libexec/"bin/jobpilot"
  end

  test do
    assert_match "jobpilot", shell_output("#{bin}/jobpilot --version")
  end
end
