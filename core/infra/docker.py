"""Docker-managed PostgreSQL for JobPilot.

`jobpilot setup` calls `ensure_postgres()`. If Docker is present and usable, it creates
(or restarts) a small `postgres:16-alpine` container backed by a named volume and returns
a DSN. If Docker is missing, not running, or the container never becomes healthy, the
caller falls back to SQLite — no user is ever hard-blocked on Docker.

Nothing here is on a request path; every call shells out to `docker` and is slow by
design, so results are cached in cache/database.json rather than re-probed.
"""
from __future__ import annotations

import json
import shutil
import socket
import subprocess
import time
from dataclasses import dataclass, field

CONTAINER = "jobpilot-postgres"
VOLUME = "jobpilot-pgdata"
IMAGE = "postgres:16-alpine"
DB_NAME = "jobpilot"
DB_USER = "jobpilot"
DB_PASSWORD = "jobpilot"      # local-only, bound to 127.0.0.1; not a secret worth keyring
DEFAULT_PORT = 5433           # 5432 is usually taken by a system Postgres
PORT_SCAN_LIMIT = 20


@dataclass
class DockerStatus:
    installed: bool = False
    running: bool = False
    container_exists: bool = False
    container_running: bool = False
    port: int | None = None
    image: str = IMAGE
    detail: str = ""
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "installed": self.installed,
            "running": self.running,
            "container_exists": self.container_exists,
            "container_running": self.container_running,
            "port": self.port,
            "image": self.image,
            "detail": self.detail,
            "errors": self.errors,
        }


# --------------------------------------------------------------------------- #
# Shell helpers
# --------------------------------------------------------------------------- #
def _docker_bin() -> str | None:
    return shutil.which("docker")


def _run(args: list[str], timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout)


def docker_available() -> tuple[bool, str]:
    """True only if the CLI exists *and* the daemon answers — installed isn't enough."""
    if _docker_bin() is None:
        return False, "docker CLI not found on PATH"
    try:
        proc = _run(["info", "--format", "{{.ServerVersion}}"], timeout=15)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return False, f"docker not responding: {exc}"
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip().splitlines()
        hint = detail[-1] if detail else "docker daemon unreachable"
        return False, hint
    return True, f"docker {proc.stdout.strip()}"


# --------------------------------------------------------------------------- #
# Container inspection
# --------------------------------------------------------------------------- #
def _inspect() -> dict | None:
    try:
        proc = _run(["inspect", CONTAINER], timeout=20)
    except (subprocess.TimeoutExpired, OSError):
        return None
    if proc.returncode != 0:
        return None
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    return data[0] if data else None


def _mapped_port(info: dict) -> int | None:
    try:
        bindings = info["NetworkSettings"]["Ports"]["5432/tcp"]
        return int(bindings[0]["HostPort"]) if bindings else None
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def status() -> DockerStatus:
    st = DockerStatus()
    st.installed = _docker_bin() is not None
    ok, detail = docker_available()
    st.running = ok
    st.detail = detail
    if not ok:
        return st
    info = _inspect()
    if info is None:
        st.detail = f"{detail}; container '{CONTAINER}' not created"
        return st
    st.container_exists = True
    st.container_running = bool(info.get("State", {}).get("Running"))
    st.port = _mapped_port(info)
    st.detail = f"{detail}; container {'running' if st.container_running else 'stopped'}"
    return st


# --------------------------------------------------------------------------- #
# Lifecycle
# --------------------------------------------------------------------------- #
def _free_port(preferred: int = DEFAULT_PORT) -> int:
    for port in range(preferred, preferred + PORT_SCAN_LIMIT):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def dsn(port: int) -> str:
    return f"postgresql+psycopg://{DB_USER}:{DB_PASSWORD}@127.0.0.1:{port}/{DB_NAME}"


def _create_container(port: int) -> tuple[bool, str]:
    args = [
        "run", "-d",
        "--name", CONTAINER,
        "--restart", "unless-stopped",          # comes back with Docker after a reboot
        "-e", f"POSTGRES_USER={DB_USER}",
        "-e", f"POSTGRES_PASSWORD={DB_PASSWORD}",
        "-e", f"POSTGRES_DB={DB_NAME}",
        "-v", f"{VOLUME}:/var/lib/postgresql/data",
        "-p", f"127.0.0.1:{port}:5432",         # never exposed beyond loopback
        "--health-cmd", f"pg_isready -U {DB_USER} -d {DB_NAME}",
        "--health-interval", "5s",
        "--health-retries", "10",
        IMAGE,
    ]
    try:
        proc = _run(args, timeout=180)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return False, f"docker run failed: {exc}"
    if proc.returncode != 0:
        return False, (proc.stderr or proc.stdout).strip()
    return True, "container created"


def wait_healthy(port: int, timeout: int = 90) -> tuple[bool, str]:
    """Poll `pg_isready` inside the container until it answers or we give up."""
    deadline = time.monotonic() + timeout
    last = "not started"
    while time.monotonic() < deadline:
        try:
            proc = _run(["exec", CONTAINER, "pg_isready", "-U", DB_USER, "-d", DB_NAME],
                        timeout=15)
            if proc.returncode == 0:
                return True, "postgres accepting connections"
            last = (proc.stdout or proc.stderr).strip() or "not ready"
        except (subprocess.TimeoutExpired, OSError) as exc:
            last = str(exc)
        time.sleep(2)
    return False, f"timed out after {timeout}s waiting for postgres ({last})"


def start() -> tuple[bool, str]:
    try:
        proc = _run(["start", CONTAINER], timeout=60)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return False, str(exc)
    if proc.returncode != 0:
        return False, (proc.stderr or proc.stdout).strip()
    return True, "container started"


def stop() -> tuple[bool, str]:
    try:
        proc = _run(["stop", CONTAINER], timeout=60)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return False, str(exc)
    return proc.returncode == 0, (proc.stderr or proc.stdout).strip() or "stopped"


def remove(*, delete_data: bool = False) -> tuple[bool, str]:
    """Remove the container. `delete_data=True` also drops the volume — irreversible."""
    try:
        _run(["rm", "-f", CONTAINER], timeout=60)
        if delete_data:
            _run(["volume", "rm", VOLUME], timeout=60)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return False, str(exc)
    return True, "container removed" + (" (data volume deleted)" if delete_data else "")


def ensure_postgres(*, preferred_port: int = DEFAULT_PORT,
                    timeout: int = 90) -> tuple[str | None, str]:
    """Bring up Postgres and return `(dsn, message)`. `(None, reason)` means fall back.

    Reuses an existing container as-is when it is already healthy, so repeated
    `jobpilot setup` runs are fast and never disturb a working database.
    """
    ok, detail = docker_available()
    if not ok:
        return None, detail

    info = _inspect()
    if info is not None:
        port = _mapped_port(info) or preferred_port
        if not info.get("State", {}).get("Running"):
            started, msg = start()
            if not started:
                return None, f"could not start existing container: {msg}"
        healthy, msg = wait_healthy(port, timeout)
        if not healthy:
            return None, msg
        return dsn(port), f"reusing container '{CONTAINER}' on port {port}"

    port = _free_port(preferred_port)
    created, msg = _create_container(port)
    if not created:
        return None, msg
    healthy, msg = wait_healthy(port, timeout)
    if not healthy:
        return None, msg
    return dsn(port), f"created container '{CONTAINER}' on port {port}"


def provision(*, preferred_port: int = DEFAULT_PORT) -> dict:
    """Full setup step: try Postgres, else SQLite, persist the choice, migrate.

    Returns {"backend", "url", "message", "docker"} — the shape the setup TUI and the
    /api/setup/status endpoint both render.
    """
    from .. import db

    url, message = ensure_postgres(preferred_port=preferred_port)
    backend = "postgres"
    if url is None:
        backend, url = "sqlite", db.sqlite_url()
        message = f"Docker unavailable — using SQLite ({message})"

    db.save_url(url, backend=backend, container=CONTAINER if backend == "postgres" else "")
    db.dispose()
    db.init_db(url)
    return {"backend": backend, "url": url, "message": message,
            "docker": status().as_dict()}
