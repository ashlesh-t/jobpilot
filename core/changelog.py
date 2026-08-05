"""CHANGELOG.md → structured releases.

Both `jobpilot upgrade` (to show what a new version brings) and the About page's
"What's new" section read the same file, so release notes are written once.

The file is newest-first, with `## vX.Y.Z — YYYY-MM-DD` per release, free-form `###`
sections inside, and `---` between releases. Anything that doesn't match is kept as
prose rather than dropped, so an unusual entry degrades to readable text.
"""
from __future__ import annotations

import re
from pathlib import Path

RELEASE_RE = re.compile(r"^##\s+v?(\d+[\w.]*)\s*(?:[—–-]\s*(.+))?$")
SECTION_RE = re.compile(r"^###\s+(.+?)\s*$")
TITLE_RE = re.compile(r'^Release title:\s*"?(.+?)"?\s*(?:\((\w+)\))?$')
BULLET_RE = re.compile(r"^[-*]\s+(.*)$")


def changelog_path() -> Path | None:
    """Find CHANGELOG.md whether we're a wheel install or a git checkout."""
    here = Path(__file__).resolve().parent
    for candidate in (here.parent / "CHANGELOG.md",          # checkout / bundle root
                      here.parent.parent / "CHANGELOG.md"):  # jobpilot/bundle/core → pkg
        if candidate.is_file():
            return candidate
    return None


def version_key(version: str) -> tuple:
    """Sortable key for a dotted version. Non-numeric parts sort before numeric ones."""
    parts: list[tuple[int, int, str]] = []
    for chunk in re.split(r"[.\-+]", version.lstrip("v")):
        if chunk.isdigit():
            parts.append((1, int(chunk), ""))
        elif chunk:
            parts.append((0, 0, chunk))
    return tuple(parts)


def is_newer(candidate: str, current: str) -> bool:
    return version_key(candidate) > version_key(current)


def parse(text: str) -> list[dict]:
    """Split the changelog into releases, newest first (file order is preserved)."""
    releases: list[dict] = []
    release: dict | None = None
    section: dict | None = None
    blank = True                 # a blank line ends a bullet or paragraph

    def close_section() -> None:
        nonlocal section
        if release is not None and section is not None and (section["items"] or section["body"]):
            release["sections"].append(section)
        section = None

    def open_section(heading: str) -> None:
        nonlocal section, blank
        close_section()
        section = {"heading": heading, "items": [], "body": []}
        blank = True

    for raw in text.splitlines():
        line = raw.rstrip()

        match = RELEASE_RE.match(line)
        if match:
            close_section()
            release = {"version": match.group(1), "date": (match.group(2) or "").strip(),
                       "title": "", "kind": "", "sections": []}
            releases.append(release)
            open_section("")
            continue

        if release is None:            # the "# Changelog" preamble
            continue

        heading = SECTION_RE.match(line)
        if heading:
            title = TITLE_RE.match(heading.group(1))
            if title:                  # "### Release title: "…" (major)" is metadata
                release["title"] = title.group(1)
                release["kind"] = (title.group(2) or "").lower()
                open_section("")
            else:
                open_section(heading.group(1))
            continue

        if not line.strip() or line.strip() == "---":
            blank = True
            continue
        if section is None:
            open_section("")

        bullet = BULLET_RE.match(line.strip())
        if bullet:
            section["items"].append(bullet.group(1).strip())
            blank = False
            continue

        # An indented line straight after a bullet is that bullet's wrapped tail, not a
        # new paragraph — the changelog wraps at 90 columns, so most bullets have one.
        indented = line[:1] in (" ", "\t")
        if indented and section["items"] and not blank:
            section["items"][-1] += " " + line.strip()
        elif section["body"] and not blank:
            section["body"][-1] += " " + line.strip()
        else:
            section["body"].append(line.strip())
        blank = False

    close_section()
    for entry in releases:
        entry["sections"] = [s for s in entry["sections"] if s["items"] or s["body"]]
    return releases


def load() -> list[dict]:
    """Parsed releases, or an empty list when the file isn't bundled."""
    path = changelog_path()
    if path is None:
        return []
    try:
        return parse(path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return []


def since(version: str, releases: list[dict] | None = None) -> list[dict]:
    """Releases strictly newer than `version` — what an upgrade would bring."""
    entries = load() if releases is None else releases
    return [r for r in entries if is_newer(r["version"], version)]
