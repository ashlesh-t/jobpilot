"""The built UI is served correctly, works offline, and deep links resolve.

These guard the two ways the UI silently breaks: the bundle not making it into the
install, and the SPA catch-all either swallowing an API route or 404-ing a deep link.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parent.parent
DIST = REPO / "ui" / "dist"

pytestmark = pytest.mark.skipif(
    not (DIST / "index.html").exists(),
    reason="UI not built — run `npm --prefix ui install && npm --prefix ui run build`",
)


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


def test_index_is_served(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "<div id=\"root\">" in res.text


def test_deep_links_return_the_app_not_404(client):
    """React owns routing, so /applications must return index.html, not a 404."""
    for path in ("/applications", "/hunt", "/hunt/20260801T093000", "/me", "/settings"):
        res = client.get(path)
        assert res.status_code == 200, path
        assert "<div id=\"root\">" in res.text, path


def test_api_routes_are_not_swallowed_by_the_spa_fallback(client):
    """The catch-all is registered last; these must still return JSON."""
    assert client.get("/health").json()["ok"] is True
    assert "phases" in client.get("/phases").json()
    assert "rows" in client.get("/doctor").json()
    assert client.get("/runs/does-not-exist").status_code == 404


def test_assets_are_served(client):
    index = client.get("/").text
    assets = re.findall(r'assets/[A-Za-z0-9._-]+', index)
    assert assets, "index.html references no built assets"
    for asset in set(assets):
        res = client.get(f"/{asset}")
        assert res.status_code == 200, asset


def test_bundle_makes_no_external_requests():
    """A CDN reference would break the app on a machine without internet — which is
    exactly the machine a local-first tool has to work on."""
    offenders: list[str] = []
    for path in [DIST / "index.html", *(DIST / "assets").glob("*.css")]:
        for url in re.findall(r'https?://[^\s"\')]+', path.read_text(errors="ignore")):
            if "w3.org" in url or "apple.com/DTDs" in url:
                continue  # XML namespaces, never fetched
            offenders.append(f"{path.name}: {url}")
    assert not offenders, f"external references in the built UI: {offenders}"


def test_theme_is_applied_before_first_paint():
    """Without the inline bootstrap, dark-mode users get a white flash on every load."""
    html = (DIST / "index.html").read_text()
    assert "data-theme" in html
    assert "prefers-color-scheme" in html


def test_both_themes_are_defined_in_the_stylesheet():
    css = "\n".join(p.read_text() for p in (DIST / "assets").glob("*.css"))
    assert "[data-theme=dark]" in css.replace('"', "").replace("'", "")
    assert "--accent" in css
