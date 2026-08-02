"""Presentation layer for the setup wizard — console, banner, progress rail, panels.

Everything here degrades: if Rich isn't importable we fall back to plain print, so the
wizard still runs in a stripped-down environment rather than crashing on cosmetics.
"""
from __future__ import annotations

import sys

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    from rich.theme import Theme
    RICH = True
except ImportError:  # pragma: no cover - cosmetic fallback
    RICH = False
    Console = Panel = Table = Text = Theme = None  # type: ignore

BRAND = "#5B7CFA"

_THEME = {
    "brand": BRAND,
    "muted": "grey58",
    "ok": "green",
    "warn": "yellow",
    "fail": "red",
    "step": f"bold {BRAND}",
    "hint": "italic grey58",
} if RICH else {}

console = Console(theme=Theme(_THEME), highlight=False) if RICH else None

LOGO = r"""
   ██  ██████  ██████     ██████  ██ ██       ██████  ████████
   ██ ██    ██ ██   ██    ██   ██ ██ ██      ██    ██    ██
   ██ ██    ██ ██████     ██████  ██ ██      ██    ██    ██
██ ██ ██    ██ ██         ██      ██ ██      ██    ██    ██
 ███   ██████  ██         ██      ██ ███████  ██████     ██
"""


def _plain(msg: str = "") -> None:
    print(msg)


def out(msg: str = "", style: str | None = None) -> None:
    if console is None:
        _plain(_strip_markup(msg))
        return
    console.print(msg, style=style)


def _strip_markup(msg: str) -> str:
    import re
    return re.sub(r"\[/?[a-z0-9 #._-]+\]", "", msg)


def banner(subtitle: str = "Automated job-hunting, end to end") -> None:
    if console is None:
        _plain(LOGO)
        _plain(f"  {subtitle}\n")
        return
    console.print(Text(LOGO, style=f"bold {BRAND}"))
    console.print(f"  [muted]{subtitle}[/muted]\n")


def rail(steps: list[str], current: int) -> None:
    """A one-line progress rail: ● done  ◉ current  ○ pending."""
    if console is None:
        _plain(f"Step {current + 1}/{len(steps)} — {steps[current]}")
        return
    marks = []
    for i, name in enumerate(steps):
        if i < current:
            marks.append(f"[ok]●[/ok] [muted]{name}[/muted]")
        elif i == current:
            marks.append(f"[brand]◉[/brand] [step]{name}[/step]")
        else:
            marks.append(f"[muted]○ {name}[/muted]")
    console.print("  " + "  [muted]›[/muted]  ".join(marks))
    console.print()


def step_header(index: int, total: int, title: str, help_text: str = "") -> None:
    if console is None:
        _plain(f"\n=== Step {index}/{total}: {title} ===")
        if help_text:
            _plain(f"    {help_text}")
        return
    console.rule(f"[step]Step {index}/{total} · {title}[/step]", style=BRAND)
    if help_text:
        console.print(f"  [hint]{help_text}[/hint]")
    console.print()


def info(msg: str) -> None:
    out(f"  [muted]{msg}[/muted]")


def success(msg: str) -> None:
    out(f"  [ok]✓[/ok] {msg}")


def warn(msg: str) -> None:
    out(f"  [warn]![/warn] {msg}")


def error(msg: str) -> None:
    out(f"  [fail]✗[/fail] {msg}")


def bullet(msg: str) -> None:
    out(f"    [muted]•[/muted] {msg}")


def panel(body: str, title: str = "", style: str = BRAND) -> None:
    if console is None:
        _plain(f"\n--- {title} ---\n{_strip_markup(body)}\n")
        return
    console.print(Panel(body, title=title or None, border_style=style, padding=(1, 2)))


def summary_table(rows: list[tuple[str, str, str]]) -> None:
    """rows = [(label, status, detail)] where status is ok|warn|fail|skip."""
    icons = {"ok": "[ok]✓[/ok]", "warn": "[warn]![/warn]",
             "fail": "[fail]✗[/fail]", "skip": "[muted]–[/muted]"}
    if console is None:
        for label, status, detail in rows:
            _plain(f"  [{status:4}] {label}: {detail}")
        return
    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column(width=2)
    table.add_column(style="bold", min_width=22)
    table.add_column(style="muted", overflow="fold")
    for label, status, detail in rows:
        table.add_row(icons.get(status, " "), label, detail)
    console.print(table)


class spinner:
    """`with spinner("Checking…"):` — a status line that degrades to a plain print."""

    def __init__(self, message: str):
        self.message = message
        self._status = None

    def __enter__(self):
        if console is None:
            print(f"  {self.message}", end="", flush=True)
            return self
        self._status = console.status(f"[muted]{self.message}[/muted]", spinner="dots")
        self._status.__enter__()
        return self

    def __exit__(self, *exc):
        if self._status is not None:
            self._status.__exit__(*exc)
        elif console is None:
            print()
        return False


def qr(data: str) -> None:
    """Render a QR code in the terminal so a phone can open the link directly."""
    try:
        import qrcode
    except ImportError:
        return
    code = qrcode.QRCode(border=1)
    code.add_data(data)
    code.make(fit=True)
    code.print_ascii(out=sys.stdout, invert=True)


def link(url: str, label: str = "") -> str:
    """OSC-8 hyperlink where the terminal supports it, plain URL otherwise."""
    if console is None:
        return url
    return f"[link={url}]{label or url}[/link]"
