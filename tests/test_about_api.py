"""About endpoints and the CHANGELOG parser behind them."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("JOBPILOT_DIR", str(tmp_path))
    monkeypatch.delenv("JOBPILOT_DATABASE_URL", raising=False)

    from core import db
    db.dispose()
    db.init_db()

    import scheduler
    monkeypatch.setattr(scheduler.scheduler, "start", lambda: None)
    monkeypatch.setattr(scheduler.scheduler, "shutdown", lambda: None)

    import app as app_module
    with TestClient(app_module.app) as c:
        yield c
    db.dispose()


# --------------------------------------------------------------------------- #
# /api/about
# --------------------------------------------------------------------------- #
def test_about_describes_this_install(client, tmp_path):
    payload = client.get("/api/about").json()

    assert payload["version"]
    assert payload["data_dir"] == str(tmp_path)
    assert payload["db_backend"] in ("SQLite", "PostgreSQL")
    assert payload["install_source"] in ("pipx", "pip", "local", "checkout")
    assert payload["issues_url"].startswith("https://github.com/")

    names = {tool["name"] for tool in payload["tools"]}
    assert "AI backend" in names
    assert "PDF compiler (tectonic)" in names
    for tool in payload["tools"]:
        assert set(tool) == {"name", "found", "detail", "required", "hint"}


def test_about_never_exposes_a_database_password(client, monkeypatch):
    from core import db
    monkeypatch.setattr(
        db, "resolve_url",
        lambda: "postgresql://jobpilot:sup3rsecret@127.0.0.1:5433/jobpilot")
    import routes_about
    monkeypatch.setattr(routes_about, "resolve_url", db.resolve_url)

    payload = client.get("/api/about").json()
    assert "sup3rsecret" not in payload["db_url"]
    assert payload["db_url"] == "127.0.0.1:5433/jobpilot"


def test_health_reports_the_version(client):
    payload = client.get("/health").json()
    assert payload["ok"] is True
    assert payload["version"]


# --------------------------------------------------------------------------- #
# /api/about/changelog
# --------------------------------------------------------------------------- #
def test_changelog_endpoint_parses_the_real_file(client):
    payload = client.get("/api/about/changelog").json()

    assert payload["bundled"] is True
    assert payload["releases"], "the repo ships a CHANGELOG.md"
    latest = payload["releases"][0]
    assert latest["version"]
    assert latest["sections"]
    # Nothing published can be newer than the version we're running.
    assert payload["newer"] == []


SAMPLE = """# Changelog

## v2.1.0 — 2026-08-10

### Release title: "Rough Edges" (minor)

Some prose about the release.

### Added
- A thing
- Another thing

---

## v2.0.0 — 2026-08-02

### Fixed
- An old bug
"""


def test_parse_splits_releases_titles_and_sections():
    from core import changelog

    releases = changelog.parse(SAMPLE)
    assert [r["version"] for r in releases] == ["2.1.0", "2.0.0"]

    newest = releases[0]
    assert newest["date"] == "2026-08-10"
    assert newest["title"] == "Rough Edges"
    assert newest["kind"] == "minor"

    prose = newest["sections"][0]
    assert prose["heading"] == ""
    assert prose["body"] == ["Some prose about the release."]

    added = next(s for s in newest["sections"] if s["heading"] == "Added")
    assert added["items"] == ["A thing", "Another thing"]


WRAPPED = """# Changelog

## v2.1.0 — 2026-08-10

### Added
- **A wrapped bullet.** The changelog wraps at 90 columns, so the tail of this
  bullet lands on its own line and must stay part of the bullet.
- A short one.

A paragraph that also
wraps across lines.
"""


def test_wrapped_bullets_stay_one_bullet():
    """Continuation lines used to become stray prose rendered above the bullets."""
    from core import changelog

    section = changelog.parse(WRAPPED)[0]["sections"][0]

    assert len(section["items"]) == 2
    assert section["items"][0].endswith("must stay part of the bullet.")
    assert "\n" not in section["items"][0]
    assert section["items"][1] == "A short one."
    # The paragraph after a blank line is its own body entry, joined back together.
    assert section["body"] == ["A paragraph that also wraps across lines."]


def test_the_real_changelog_parses_into_whole_bullets():
    """The shipped file wraps nearly every bullet; none may leak into `body`."""
    from core import changelog

    releases = {r["version"]: r for r in changelog.load()}
    section = next(s for s in releases["2.1.0"]["sections"]
                   if s["heading"] == "Setup actually completes")

    assert section["body"] == []           # every line here belongs to a bullet
    assert len(section["items"]) == 3
    assert all(item.startswith("**") and item.endswith(".") for item in section["items"])


def test_version_comparison_is_numeric_not_lexical():
    from core import changelog

    assert changelog.is_newer("2.10.0", "2.9.0")     # lexically "2.10" < "2.9"
    assert changelog.is_newer("2.0.0", "1.7.0")
    assert not changelog.is_newer("2.0.0", "2.0.0")
    assert not changelog.is_newer("1.6.2", "2.0.0")


def test_since_returns_only_newer_releases():
    from core import changelog

    releases = changelog.parse(SAMPLE)
    assert [r["version"] for r in changelog.since("2.0.0", releases)] == ["2.1.0"]
    assert changelog.since("2.1.0", releases) == []


def test_changelog_is_found_from_the_installed_layout():
    from core import changelog

    path = changelog.changelog_path()
    assert path is not None and path.name == "CHANGELOG.md"


# --------------------------------------------------------------------------- #
# version plumbing
# --------------------------------------------------------------------------- #
def test_package_version_matches_pyproject():
    """Two hand-synced copies drift silently; the About page would then lie."""
    import tomllib
    from pathlib import Path

    from jobpilot import __version__

    root = Path(__file__).resolve().parent.parent
    pyproject = tomllib.loads((root / "pyproject.toml").read_text())
    assert pyproject["project"]["version"] == __version__


def test_app_version_resolves():
    from core.version import app_version

    assert app_version() != "unknown"
