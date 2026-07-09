# Packaging — native install wrappers

Every wrapper here is **thin**: it only delivers the one PyPI package
[`jobpilot-ai`](https://pypi.org/project/jobpilot-ai/). All behaviour lives in the
Python package, so these files just carry a version + hash and need almost no maintenance.

**The universal path is `pipx install jobpilot-ai`** — one command installs the pipeline
and the optional local web UI together, and works identically on
Linux, macOS, and Windows. The wrappers below are conveniences for users who prefer their OS
package manager.

| File | Channel | Published to | User command | Status |
|---|---|---|---|---|
| `aur/PKGBUILD` | Arch (AUR) | the AUR (`jobpilot-ai` package) | `yay -S jobpilot-ai` | pending — new AUR account registrations are disabled ([details](https://itsfoss.com/news/arch-linux-aur-malware-flood/)); push once registration reopens |
| `homebrew/jobpilot.rb` | macOS / Linux | [`ashlesh-t/homebrew-tap`](https://github.com/ashlesh-t/homebrew-tap) → `Formula/jobpilot.rb` | `brew install ashlesh-t/tap/jobpilot` | live |
| `scoop/jobpilot.json` | Windows | [`ashlesh-t/scoop-bucket`](https://github.com/ashlesh-t/scoop-bucket) → `bucket/jobpilot.json` | `scoop bucket add ashlesh-t https://github.com/ashlesh-t/scoop-bucket && scoop install jobpilot` | live |

All three repos are public — installs pull the manifest/formula straight from GitHub, no
separate registry submission needed for taps/buckets (that's only required to land in
`homebrew-core` or the main `scoop` bucket, which we don't need here).

## Release checklist (per version)

1. `git tag vX.Y.Z && git push --tags` → the `release.yml` workflow builds and publishes the
   sdist + wheel to PyPI.
2. Get the sdist sha256: `pip download --no-deps --no-binary :all: jobpilot-ai==X.Y.Z`
   then `sha256sum jobpilot_ai-X.Y.Z.tar.gz`.
3. Bump `pkgver`/`version` + hash in all three files here.
4. Push `homebrew/jobpilot.rb` → `homebrew-tap/Formula/jobpilot.rb` and
   `scoop/jobpilot.json` → `scoop-bucket/bucket/jobpilot.json` (clone, copy, commit, push to
   `main`). Push `aur/PKGBUILD` (+ a regenerated `.SRCINFO`) to the AUR git repo once an AUR
   account exists.

> `aur/PKGBUILD` cannot be built/tested in CI without Arch (`makepkg`). Homebrew/Scoop
> manifests are likewise best validated on their own OS after pushing.
