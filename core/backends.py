"""Agent-backend detection, authentication probing, and install guidance.

JobPilot needs *some* agent to run the Layer B reasoning. Four are supported:

    claude_code   Claude Code CLI on a Pro/Max subscription  — no per-token cost
    claude_api    Anthropic API key via the Agent SDK        — metered, exact costs
    gemini        Gemini / Antigravity CLI or API key        — experimental
    generic_cli   Any headless agent CLI, by command template — experimental

`probe(deep=True)` actually verifies *authentication*, not just installation. v1 only
checked that `claude --version` exited 0, which happily reported a logged-out CLI as
ready and then failed at run time.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
from dataclasses import asdict, dataclass, field

from . import secrets

CLAUDE_INSTALL_URL = "https://claude.com/download"
CLAUDE_NPM = "npm install -g @anthropic-ai/claude-code"
ANTHROPIC_KEYS_URL = "https://console.anthropic.com/settings/keys"


@dataclass
class BackendInfo:
    id: str
    label: str
    kind: str                     # cli | api
    metered: bool
    found: bool = False
    authenticated: bool = False
    version: str = ""
    detail: str = ""
    install_hint: str = ""
    auth_hint: str = ""
    experimental: bool = False
    checked_deep: bool = False
    extras: dict = field(default_factory=dict)

    @property
    def ready(self) -> bool:
        return self.found and self.authenticated

    def as_dict(self) -> dict:
        d = asdict(self)
        d["ready"] = self.ready
        return d


def _run(cmd: list[str], timeout: int = 15) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (subprocess.TimeoutExpired, OSError):
        return None


# --------------------------------------------------------------------------- #
# claude_code — CLI on a subscription
# --------------------------------------------------------------------------- #
def _claude_auth_probe(cli: str, timeout: int = 60) -> tuple[bool, str]:
    """Ask the CLI to answer one trivial prompt.

    This is the only reliable signal: `claude --version` succeeds while logged out, and
    there is no stable "am I logged in" subcommand. Deliberately not run on every page
    load — it costs a round trip.
    """
    proc = _run([cli, "-p", "Reply with the single word: ok",
                 "--output-format", "json"], timeout=timeout)
    if proc is None:
        return False, "authentication probe timed out"
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout).strip().splitlines()
        tail = err[-1] if err else f"exit {proc.returncode}"
        lowered = tail.lower()
        if "login" in lowered or "auth" in lowered or "credential" in lowered:
            return False, "not logged in — run `claude login`"
        return False, tail[:200]
    try:
        payload = json.loads(proc.stdout)
        if payload.get("is_error"):
            return False, str(payload.get("result", "probe returned an error"))[:200]
    except json.JSONDecodeError:
        pass
    return True, "authenticated"


def probe_claude_code(*, deep: bool = False, cli: str = "claude") -> BackendInfo:
    info = BackendInfo(
        id="claude_code",
        label="Claude Code CLI (Pro/Max subscription)",
        kind="cli",
        metered=False,
        install_hint=f"{CLAUDE_NPM}   (or download from {CLAUDE_INSTALL_URL})",
        auth_hint="Run `claude login` in a terminal, then re-check.",
    )
    exe = shutil.which(cli)
    if not exe:
        info.detail = f"`{cli}` not found on PATH"
        return info
    info.found = True
    info.extras["path"] = exe

    proc = _run([cli, "--version"], timeout=15)
    if proc is None or proc.returncode != 0:
        info.detail = f"`{cli} --version` failed — the install may be broken"
        return info
    info.version = proc.stdout.strip().splitlines()[0] if proc.stdout.strip() else ""

    if not deep:
        info.detail = f"installed ({info.version}); login not verified"
        # Optimistic without a deep probe, so the UI isn't red before the user asks.
        info.authenticated = True
        return info

    info.checked_deep = True
    ok, why = _claude_auth_probe(cli)
    info.authenticated = ok
    info.detail = why if not ok else f"{info.version} — authenticated"
    return info


def install_claude_code() -> tuple[bool, str]:
    """Best-effort install via npm. Returns (ok, message) — never raises."""
    if shutil.which("claude"):
        return True, "already installed"
    if shutil.which("npm") is None:
        return False, ("npm not found. Install Node.js first, then run "
                       f"`{CLAUDE_NPM}` — or download the native installer from "
                       f"{CLAUDE_INSTALL_URL}")
    proc = _run(["npm", "install", "-g", "@anthropic-ai/claude-code"], timeout=600)
    if proc is None:
        return False, "npm install timed out"
    if proc.returncode != 0:
        return False, (proc.stderr or proc.stdout).strip()[-400:]
    return (True, "installed") if shutil.which("claude") else (
        False, "npm reported success but `claude` is still not on PATH — "
               "check your npm global bin directory is on PATH")


# --------------------------------------------------------------------------- #
# claude_api — metered
# --------------------------------------------------------------------------- #
def _anthropic_key_probe(key: str, timeout: int = 20) -> tuple[bool, str]:
    """One-token /v1/messages call. Distinguishes 'bad key' from 'no network'."""
    try:
        import httpx
    except ImportError:
        return False, "httpx not installed — cannot verify the key"
    try:
        resp = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": "claude-haiku-4-5-20251001", "max_tokens": 1,
                  "messages": [{"role": "user", "content": "hi"}]},
            timeout=timeout,
        )
    except Exception as exc:  # noqa: BLE001
        return False, f"could not reach the Anthropic API: {exc}"
    if resp.status_code == 200:
        return True, "key valid"
    if resp.status_code in (401, 403):
        return False, "key rejected — check it was copied in full"
    if resp.status_code == 429:
        return True, "key valid (rate limited right now)"
    return False, f"HTTP {resp.status_code}: {resp.text[:160]}"


def probe_claude_api(*, deep: bool = False) -> BackendInfo:
    info = BackendInfo(
        id="claude_api",
        label="Anthropic API key (metered)",
        kind="api",
        metered=True,
        install_hint="pip install claude-agent-sdk",
        auth_hint=f"Create a key at {ANTHROPIC_KEYS_URL} and paste it in Setup.",
    )
    try:
        import claude_agent_sdk  # noqa: F401
        info.found = True
    except ImportError:
        info.detail = "claude-agent-sdk not installed"
        return info

    key = secrets.get("ANTHROPIC_API_KEY")
    if not key:
        info.detail = "no ANTHROPIC_API_KEY configured"
        return info
    info.extras["key_masked"] = secrets.mask(key)

    if not deep:
        info.authenticated = True
        info.detail = "key present (not verified)"
        return info

    info.checked_deep = True
    ok, why = _anthropic_key_probe(key)
    info.authenticated = ok
    info.detail = why
    return info


# --------------------------------------------------------------------------- #
# gemini / antigravity
# --------------------------------------------------------------------------- #
GEMINI_CLIS = ("gemini", "antigravity")


def probe_gemini(*, deep: bool = False) -> BackendInfo:
    info = BackendInfo(
        id="gemini",
        label="Google Gemini / Antigravity",
        kind="cli",
        metered=True,
        experimental=True,
        install_hint="npm install -g @google/gemini-cli   (or install Antigravity)",
        auth_hint="Run `gemini` once to sign in, or set GEMINI_API_KEY in Setup.",
    )
    for name in GEMINI_CLIS:
        exe = shutil.which(name)
        if exe:
            info.found = True
            info.extras["cli"] = name
            info.extras["path"] = exe
            proc = _run([name, "--version"], timeout=15)
            if proc is not None and proc.returncode == 0:
                info.version = proc.stdout.strip().splitlines()[0] if proc.stdout.strip() else ""
            break

    key = secrets.get("GEMINI_API_KEY")
    if key:
        info.found = True
        info.extras["key_masked"] = secrets.mask(key)

    if not info.found:
        info.detail = "no gemini/antigravity CLI on PATH and no GEMINI_API_KEY"
        return info

    info.authenticated = bool(key) or bool(info.extras.get("cli"))
    info.checked_deep = deep
    info.detail = ("API key configured" if key
                   else f"{info.extras.get('cli')} CLI found ({info.version or 'version unknown'})")
    return info


# --------------------------------------------------------------------------- #
# generic CLI adapter
# --------------------------------------------------------------------------- #
def probe_generic_cli(*, deep: bool = False) -> BackendInfo:
    from .repo import settings as settings_repo

    info = BackendInfo(
        id="generic_cli",
        label="Custom agent CLI",
        kind="cli",
        metered=False,
        experimental=True,
        install_hint="Set a command template in Settings, e.g. "
                     "`mytool run --prompt {prompt}`",
        auth_hint="Authenticate with your tool's own login command.",
    )
    template = (settings_repo.engine_config().get("command_template") or "").strip()
    if not template:
        info.detail = "no command template configured"
        return info
    info.extras["command_template"] = template
    binary = template.split()[0]
    exe = shutil.which(binary)
    if not exe:
        info.detail = f"`{binary}` not found on PATH"
        return info
    info.found = True
    info.authenticated = True
    info.extras["path"] = exe
    info.detail = f"using `{binary}`"
    return info


# --------------------------------------------------------------------------- #
# Aggregate
# --------------------------------------------------------------------------- #
PROBES = {
    "claude_code": probe_claude_code,
    "claude_api": probe_claude_api,
    "gemini": probe_gemini,
    "generic_cli": probe_generic_cli,
}

PRIORITY = ["claude_code", "claude_api", "gemini", "generic_cli"]


def probe(backend_id: str, *, deep: bool = False) -> BackendInfo:
    fn = PROBES.get(backend_id)
    if fn is None:
        raise ValueError(f"unknown backend {backend_id!r}; expected one of {list(PROBES)}")
    return fn(deep=deep)


def probe_all(*, deep: bool = False) -> list[dict]:
    """Every backend, in preference order. `deep=True` verifies authentication."""
    return [probe(bid, deep=deep).as_dict() for bid in PRIORITY]


def best_available(*, deep: bool = False) -> str | None:
    """The highest-priority ready backend, or None if the user must configure one."""
    for info in probe_all(deep=deep):
        if info["ready"]:
            return info["id"]
    return None


def selected() -> str:
    from .repo import settings as settings_repo
    return settings_repo.engine_config()["provider"]


def select(backend_id: str) -> dict:
    """Persist the chosen backend into the engine config."""
    from .repo import settings as settings_repo

    if backend_id not in PROBES:
        raise ValueError(f"unknown backend {backend_id!r}")
    cfg = settings_repo.engine_config()
    cfg["provider"] = backend_id
    settings_repo.set("engine", cfg)
    return cfg


def environment() -> dict:
    """Machine facts the setup UI and doctor report alongside the backends."""
    return {
        "platform": platform.system(),
        "release": platform.release(),
        "python": platform.python_version(),
        "node": (shutil.which("node") or ""),
        "npm": (shutil.which("npm") or ""),
        "docker": (shutil.which("docker") or ""),
        "tectonic": (shutil.which("tectonic") or ""),
        "home": os.path.expanduser("~"),
    }
