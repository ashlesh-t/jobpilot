"""Resolve the bundled runtime tree, whether installed (wheel) or run from a checkout.

- Installed via pip/pipx: the repo tree ships at `<site-packages>/jobpilot/bundle/…`
  (see the `force-include` mapping in pyproject.toml).
- Git checkout (dev): no `bundle/` dir exists, so the repo root is the parent of this
  package — the ordinary layout the code already expects.

Either way, `bundle_root()` returns a directory that contains `engines/`, `server/`,
`scripts/`, `skills/`, `config/`, `schema/` at the top level, so every module's
`REPO_DIR = Path(__file__).parent.parent` math and every `config/…` read keep working.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def bundle_root() -> Path:
    pkg = Path(__file__).resolve().parent
    bundled = pkg / "bundle"
    if (bundled / "scripts").is_dir():
        return bundled
    return pkg.parent  # dev checkout: repo root


def runtime_env(extra: dict | None = None) -> dict:
    """os.environ + the sys.path entries the flat intra-repo imports rely on."""
    root = bundle_root()
    entries = [str(root), str(root / "scripts"), str(root / "server"),
               str(root / "scripts" / "scrapers")]
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = os.pathsep.join(entries + ([existing] if existing else []))
    if extra:
        env.update(extra)
    return env


def inject_path() -> Path:
    """Put the runtime dirs on sys.path for in-process imports; return the root."""
    root = bundle_root()
    for p in (root, root / "scripts", root / "server", root / "scripts" / "scrapers"):
        sp = str(p)
        if sp not in sys.path:
            sys.path.insert(0, sp)
    return root
