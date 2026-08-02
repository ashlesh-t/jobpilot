"""Interaction helpers for the setup wizard.

Every prompt understands two universal commands:
  `<`  go back to the previous step (raises GoBack)
  `^C` abort — the wizard exits cleanly and tells you how to resume

Uses questionary when available (arrow-key selects, masked input) and falls back to
plain `input()`/`getpass` otherwise, so the wizard never hard-depends on a TTY library.
"""
from __future__ import annotations

import getpass
import sys

from . import theme

try:
    import questionary
    from questionary import Style as QStyle
    QUESTIONARY = True
except ImportError:  # pragma: no cover - fallback path
    QUESTIONARY = False
    questionary = None  # type: ignore

BACK_TOKEN = "<"

_QS_STYLE = QStyle([
    ("qmark", f"fg:{theme.BRAND} bold"),
    ("question", "bold"),
    ("answer", f"fg:{theme.BRAND} bold"),
    ("pointer", f"fg:{theme.BRAND} bold"),
    ("highlighted", f"fg:{theme.BRAND} bold"),
    ("selected", "fg:#22c55e"),
    ("instruction", "fg:#888888 italic"),
]) if QUESTIONARY else None


class GoBack(Exception):
    """The user asked to return to the previous step."""


class Aborted(Exception):
    """The user pressed Ctrl-C / Ctrl-D."""


def _hint(text: str, allow_back: bool) -> str:
    parts = [p for p in (text, "type < to go back" if allow_back else "") if p]
    return " · ".join(parts)


def ask_text(message: str, *, default: str = "", help_text: str = "",
             allow_back: bool = True, allow_empty: bool = True,
             validate=None) -> str:
    """Free-text input. `validate` returns None on success or an error string."""
    while True:
        try:
            if QUESTIONARY:
                answer = questionary.text(
                    message, default=default, style=_QS_STYLE,
                    instruction=_hint(help_text, allow_back) or None,
                ).unsafe_ask()
            else:
                suffix = f" [{default}]" if default else ""
                answer = input(f"  {message}{suffix}: ").strip() or default
        except (KeyboardInterrupt, EOFError):
            raise Aborted from None

        if answer is None:
            raise Aborted
        answer = answer.strip()
        if allow_back and answer == BACK_TOKEN:
            raise GoBack
        if not answer and not allow_empty:
            theme.warn("This one is required.")
            continue
        if validate and answer:
            problem = validate(answer)
            if problem:
                theme.warn(problem)
                continue
        return answer


def ask_secret(message: str, *, help_text: str = "", allow_back: bool = True,
               allow_empty: bool = False) -> str:
    """Masked input. The value is never echoed, logged, or defaulted."""
    while True:
        try:
            if QUESTIONARY:
                answer = questionary.password(
                    message, style=_QS_STYLE,
                    instruction=_hint(help_text, allow_back) or None,
                ).unsafe_ask()
            else:
                answer = getpass.getpass(f"  {message}: ")
        except (KeyboardInterrupt, EOFError):
            raise Aborted from None

        if answer is None:
            raise Aborted
        answer = answer.strip()
        if allow_back and answer == BACK_TOKEN:
            raise GoBack
        if not answer and not allow_empty:
            theme.warn("This one is required — or type < to go back.")
            continue
        return answer


def ask_select(message: str, choices: list[dict], *, help_text: str = "",
               allow_back: bool = True, default: str | None = None) -> str:
    """Single choice. `choices` = [{"value", "label", "hint"?, "disabled"?}]."""
    if QUESTIONARY:
        options = []
        for c in choices:
            title = c["label"]
            if c.get("hint"):
                title = f"{title}  —  {c['hint']}"
            options.append(questionary.Choice(
                title=title, value=c["value"], disabled=c.get("disabled")))
        if allow_back:
            options.append(questionary.Choice(title="← Go back", value=BACK_TOKEN))
        try:
            answer = questionary.select(
                message, choices=options, style=_QS_STYLE, default=default,
                instruction=help_text or None,
            ).unsafe_ask()
        except (KeyboardInterrupt, EOFError):
            raise Aborted from None
        if answer is None:
            raise Aborted
        if answer == BACK_TOKEN:
            raise GoBack
        return answer

    # Plain fallback: numbered list.
    theme.out(f"  {message}")
    enabled = [c for c in choices if not c.get("disabled")]
    for i, c in enumerate(enabled, 1):
        hint = f"  — {c['hint']}" if c.get("hint") else ""
        theme.out(f"    {i}) {c['label']}{hint}")
    while True:
        raw = ask_text("Choose a number", allow_back=allow_back, allow_empty=False)
        if raw.isdigit() and 1 <= int(raw) <= len(enabled):
            return enabled[int(raw) - 1]["value"]
        theme.warn(f"Enter a number between 1 and {len(enabled)}.")


def ask_confirm(message: str, *, default: bool = True, allow_back: bool = False) -> bool:
    if QUESTIONARY:
        try:
            answer = questionary.confirm(message, default=default,
                                         style=_QS_STYLE).unsafe_ask()
        except (KeyboardInterrupt, EOFError):
            raise Aborted from None
        if answer is None:
            raise Aborted
        return bool(answer)

    suffix = "[Y/n]" if default else "[y/N]"
    raw = ask_text(f"{message} {suffix}", allow_back=allow_back, allow_empty=True)
    if not raw:
        return default
    return raw.lower().startswith("y")


def pause(message: str = "Press Enter to continue") -> None:
    try:
        input(f"  {message}… ")
    except (KeyboardInterrupt, EOFError):
        raise Aborted from None


def is_interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()
