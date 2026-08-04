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
from pathlib import Path

from . import secrets

REPO_DIR = Path(__file__).resolve().parent.parent

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


def _run(cmd: list[str], timeout: int = 15,
         cwd: str | None = None) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                              cwd=cwd)
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


def probe_claude_code(user_id: int, *, deep: bool = False, cli: str = "claude") -> BackendInfo:
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

    # If this process's own install directory has been removed (reinstalled/upgraded
    # while still running), spawning any child fails with a confusing, runtime-specific
    # error rather than a clear one — catch it here instead of guessing at "broken".
    if not REPO_DIR.exists():
        info.detail = (
            f"this service's own install directory is gone ({REPO_DIR}) — it was "
            "probably reinstalled/upgraded while still running. Restart it: "
            "`jobpilot stop && jobpilot start`"
        )
        return info

    proc = _run([cli, "--version"], timeout=15, cwd=str(REPO_DIR))
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


def probe_claude_api(user_id: int, *, deep: bool = False) -> BackendInfo:
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

    key = secrets.get(user_id, "ANTHROPIC_API_KEY")
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


def probe_gemini(user_id: int, *, deep: bool = False) -> BackendInfo:
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

    key = secrets.get(user_id, "GEMINI_API_KEY")
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
def probe_generic_cli(user_id: int, *, deep: bool = False) -> BackendInfo:
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
    template = (_load_engine_config().get("command_template") or "").strip()
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


def probe(backend_id: str, user_id: int, *, deep: bool = False) -> BackendInfo:
    fn = PROBES.get(backend_id)
    if fn is None:
        raise ValueError(f"unknown backend {backend_id!r}; expected one of {list(PROBES)}")
    return fn(user_id, deep=deep)


def probe_all(user_id: int, *, deep: bool = False) -> list[dict]:
    """Every backend, in preference order. `deep=True` verifies authentication."""
    return [probe(bid, user_id, deep=deep).as_dict() for bid in PRIORITY]


def best_available(user_id: int, *, deep: bool = False) -> str | None:
    """The highest-priority ready backend, or None if the user must configure one."""
    for info in probe_all(user_id, deep=deep):
        if info["ready"]:
            return info["id"]
    return None


def _engine_config_path() -> Path:
    """Where the machine-wide agent-backend choice is stored.

    Unlike `preferences.json`/`profile.json`, which agent CLI JobPilot runs is an
    instance-level fact (which agent is installed and authenticated on this machine),
    not a per-account preference — every account on this instance shares one backend.
    That is why this lives in its own instance-wide file instead of the per-user
    `settings` table (see the `/api/backends` route in server/routes_settings.py, which
    already treats it this way).
    """
    from .paths import cache_dir
    return cache_dir() / "engine.json"


def _load_engine_config() -> dict:
    path = _engine_config_path()
    try:
        data = json.loads(path.read_text())
        if isinstance(data, dict):
            return data
    except Exception:  # noqa: BLE001
        pass
    return {}


def _save_engine_config(cfg: dict) -> None:
    path = _engine_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, indent=2))


def selected() -> str:
    return _load_engine_config().get("provider", "claude_code")


def select(backend_id: str) -> dict:
    """Persist the chosen backend into the instance-wide engine config."""
    if backend_id not in PROBES:
        raise ValueError(f"unknown backend {backend_id!r}")
    cfg = _load_engine_config()
    cfg["provider"] = backend_id
    _save_engine_config(cfg)
    return cfg


# --------------------------------------------------------------------------- #
# tectonic — the LaTeX engine that turns a tailored .tex into a PDF
# --------------------------------------------------------------------------- #
TECTONIC_DROP_URL = "https://drop-sh.fullyjustified.net"
TECTONIC_SITE_URL = "https://tectonic-typesetting.github.io/en-US/install.html"


def tectonic_install_hints() -> list[str]:
    """Package-manager commands for this machine, best guess first."""
    system = platform.system()
    if system == "Darwin":
        return ["brew install tectonic"]
    if system == "Windows":
        return ["scoop install tectonic", "cargo install tectonic"]
    hints = []
    for binary, command in (("pacman", "sudo pacman -S tectonic"),
                            ("apt", "sudo apt install tectonic"),
                            ("dnf", "sudo dnf install tectonic"),
                            ("zypper", "sudo zypper install tectonic")):
        if shutil.which(binary):
            hints.append(command)
    hints.append("cargo install tectonic")
    return hints


def _local_bin() -> str:
    return os.path.join(os.path.expanduser("~"), ".local", "bin")


def install_tectonic() -> tuple[bool, str]:
    """Best-effort install of the tectonic binary into ~/.local/bin.

    Uses tectonic's official drop-in installer, which places a self-contained binary in
    the working directory — no root, no system package manager, no LaTeX distribution.
    Returns (ok, message) and never raises, mirroring `install_claude_code`.
    """
    if shutil.which("tectonic"):
        return True, "already installed"

    hints = "  or  ".join(tectonic_install_hints())

    if platform.system() == "Windows":
        return False, f"Install it with:  {hints}   ({TECTONIC_SITE_URL})"

    target = _local_bin()
    try:
        os.makedirs(target, exist_ok=True)
    except OSError as exc:
        return False, f"could not create {target}: {exc}"

    # Fetch the installer and run it from a file rather than piping a URL into a shell,
    # so what executes is on disk and inspectable if this ever goes wrong.
    try:
        import httpx
        script = httpx.get(TECTONIC_DROP_URL, timeout=30,
                           follow_redirects=True).raise_for_status().text
    except Exception as exc:  # noqa: BLE001
        return False, (f"could not download the installer ({exc}). "
                       f"Install it with:  {hints}")

    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        script_path = os.path.join(tmp, "install-tectonic.sh")
        with open(script_path, "w") as fh:
            fh.write(script)
        proc = _run(["sh", script_path], timeout=600, cwd=target)

    if proc is None:
        return False, f"the installer timed out. Install it with:  {hints}"
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip()[-300:]
        return False, f"{detail or 'the installer failed'}. Install it with:  {hints}"

    if shutil.which("tectonic"):
        return True, f"installed to {target}"
    if os.path.exists(os.path.join(target, "tectonic")):
        return False, (f"downloaded to {target}, but that directory is not on your PATH. "
                       f'Add it — e.g. export PATH="$HOME/.local/bin:$PATH" in your '
                       "shell profile — then restart JobPilot.")
    return False, f"the installer reported success but no binary appeared in {target}"


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
