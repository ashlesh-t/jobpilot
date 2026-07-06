# Packaging — native install wrappers

Every wrapper here is **thin**: it only delivers the one PyPI package
[`claude-jobpilot`](https://pypi.org/project/claude-jobpilot/). All behaviour lives in the
Python package, so these files just carry a version + hash and need almost no maintenance.

**The universal path is `pipx install "claude-jobpilot[server]"`** — it works identically on
Linux, macOS, and Windows. The wrappers below are conveniences for users who prefer their OS
package manager.

| File | Channel | Publish to | User command |
|---|---|---|---|
| `aur/PKGBUILD` | Arch (AUR) | the AUR (`claude-jobpilot` package) | `yay -S claude-jobpilot` |
| `homebrew/jobpilot.rb` | macOS / Linux | a tap repo `ashlesh-t/homebrew-tap` → `Formula/jobpilot.rb` | `brew install ashlesh-t/tap/jobpilot` |
| `scoop/jobpilot.json` | Windows | a scoop bucket repo | `scoop install jobpilot` |

## Release checklist (per version)

1. `git tag vX.Y.Z && git push --tags` → the `release.yml` workflow builds and publishes the
   sdist + wheel to PyPI.
2. Get the sdist sha256: `pip download --no-deps --no-binary :all: claude-jobpilot==X.Y.Z`
   then `sha256sum claude_jobpilot-X.Y.Z.tar.gz`.
3. Bump `pkgver`/`version` + hash in all three files here.
4. Push the AUR PKGBUILD, the tap formula, and the scoop manifest to their respective repos.

> These three files cannot be built/tested in CI without the target ecosystems (makepkg /
> Homebrew / scoop). Validate each on its platform after the first PyPI publish. Until then,
> `pipx install "claude-jobpilot[server]"` is the supported cross-platform install.
