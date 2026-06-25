#!/usr/bin/env python3
"""JobPilot interactive secrets wizard.

Prompts for APIFY_TOKEN, TELEGRAM_BOT_TOKEN, and TELEGRAM_CHAT_ID,
validates each one live, then writes them to ~/.claude/job-hunt-ai/.env.
"""
from __future__ import annotations

import getpass
import os
import sys
from pathlib import Path

# ── ANSI helpers ─────────────────────────────────────────────────────────────
RESET  = "\033[0m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
GREEN  = "\033[32m"
YELLOW = "\033[33m"
RED    = "\033[31m"
CYAN   = "\033[36m"
BLUE   = "\033[34m"

def bold(t: str)   -> str: return f"{BOLD}{t}{RESET}"
def dim(t: str)    -> str: return f"{DIM}{t}{RESET}"
def green(t: str)  -> str: return f"{GREEN}{t}{RESET}"
def yellow(t: str) -> str: return f"{YELLOW}{t}{RESET}"
def red(t: str)    -> str: return f"{RED}{t}{RESET}"
def cyan(t: str)   -> str: return f"{CYAN}{t}{RESET}"
def blue(t: str)   -> str: return f"{BLUE}{t}{RESET}"

WIDTH = 58

def hr(ch: str = "─") -> None:
    print(dim(ch * WIDTH))

def banner() -> None:
    inner = " JobPilot Setup Wizard "
    pad = (WIDTH - len(inner) - 2) // 2
    print()
    print(bold(cyan("╔" + "═" * (WIDTH - 2) + "╗")))
    print(bold(cyan("║")) + " " * pad + bold(inner) + " " * pad + bold(cyan("║")))
    print(bold(cyan("╚" + "═" * (WIDTH - 2) + "╝")))
    print()

def step_header(n: int, total: int, title: str) -> None:
    print()
    hr()
    label = f"  Step {n} of {total}: {title}"
    print(bold(f"{label}"))
    hr()
    print()

def ok(msg: str)   -> None: print(f"  {green('✓')} {msg}")
def warn(msg: str) -> None: print(f"  {yellow('!')} {msg}")
def err(msg: str)  -> None: print(f"  {red('✗')} {msg}")
def info(msg: str) -> None: print(f"  {dim('·')} {msg}")

def prompt(label: str, secret: bool = True, default: str = "") -> str:
    """Prompt for input. Uses getpass (hidden) for secrets."""
    disp = f"  {bold(label)}"
    if default:
        disp += dim(f"  [keep: ****{default[-4:]}]")
    disp += "  "
    if secret:
        try:
            value = getpass.getpass(disp)
        except (KeyboardInterrupt, EOFError):
            print()
            sys.exit(0)
    else:
        try:
            value = input(disp).strip()
        except (KeyboardInterrupt, EOFError):
            print()
            sys.exit(0)
    return value or default

def pause(msg: str = "Press Enter to continue...") -> None:
    try:
        input(f"\n  {dim(msg)}")
    except (KeyboardInterrupt, EOFError):
        print()
        sys.exit(0)

def spinner(msg: str, fn):
    """Run fn() while showing a spinner. Returns fn()'s result."""
    frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    result = [None]
    exc    = [None]

    import threading
    done = threading.Event()

    def worker():
        try:
            result[0] = fn()
        except Exception as e:
            exc[0] = e
        finally:
            done.set()

    t = threading.Thread(target=worker, daemon=True)
    t.start()

    i = 0
    sys.stdout.write(f"\r  {cyan(frames[0])} {msg}")
    sys.stdout.flush()
    while not done.wait(0.08):
        sys.stdout.write(f"\r  {cyan(frames[i % len(frames)])} {msg}")
        sys.stdout.flush()
        i += 1
    sys.stdout.write("\r" + " " * (WIDTH) + "\r")
    sys.stdout.flush()

    if exc[0]:
        raise exc[0]
    return result[0]

# ── Data dir ─────────────────────────────────────────────────────────────────

def jobpilot_dir() -> Path:
    raw = os.environ.get("JOBPILOT_DIR", "~/.claude/job-hunt-ai")
    return Path(os.path.expanduser(raw))

# ── .env helpers ──────────────────────────────────────────────────────────────

def load_env(env_path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    if not env_path.is_file():
        return result
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, _, v = line.partition("=")
            result[k.strip()] = v.strip()
    return result

def write_env(env_path: Path, values: dict[str, str]) -> None:
    lines = [
        "# JobPilot secrets — managed by setup.sh",
        "# To change a key: re-run ./setup.sh   OR   edit this file directly.",
        "# File location: " + str(env_path),
        "",
    ]
    for k, v in values.items():
        lines.append(f"{k}={v}")
    lines.append("")
    env_path.write_text("\n".join(lines))

# ── Validators ───────────────────────────────────────────────────────────────

def validate_apify(token: str) -> str:
    """Returns the account username on success, raises on failure."""
    import urllib.request, json, urllib.error
    req = urllib.request.Request(
        "https://api.apify.com/v2/users/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read())
            return data.get("data", {}).get("username", "unknown")
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise ValueError("Token rejected by Apify (401 Unauthorized).")
        raise ValueError(f"Apify returned HTTP {e.code}.")
    except Exception as e:
        raise ValueError(f"Could not reach Apify: {e}")

def validate_telegram_bot(token: str) -> str:
    """Returns the bot name on success, raises on failure."""
    import urllib.request, json, urllib.error
    url = f"https://api.telegram.org/bot{token}/getMe"
    try:
        with urllib.request.urlopen(url, timeout=8) as r:
            data = json.loads(r.read())
            if not data.get("ok"):
                raise ValueError("Telegram rejected the token.")
            return data["result"].get("username", "unknown")
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise ValueError("Token rejected by Telegram (401).")
        raise ValueError(f"Telegram returned HTTP {e.code}.")
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"Could not reach Telegram: {e}")

def fetch_chat_id(token: str) -> str | None:
    """Calls getUpdates and returns the first chat_id found, or None."""
    import urllib.request, json
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    try:
        with urllib.request.urlopen(url, timeout=8) as r:
            data = json.loads(r.read())
            results = data.get("result", [])
            if results:
                msg = results[-1]
                return str(msg.get("message", {}).get("chat", {}).get("id", ""))
    except Exception:
        pass
    return None

# ── Steps ────────────────────────────────────────────────────────────────────

def step_apify(existing: str) -> str:
    step_header(1, 3, "Apify Token")
    print("  Apify scrapes job boards (LinkedIn, Indeed, etc.) for you.")
    print("  The free tier gives ~$5 credit/month — enough for one run per day.")
    print()
    print(f"  {bold('How to get it:')}")
    print(f"    1. Sign up free at  {cyan('https://console.apify.com')}")
    print(f"    2. Go to  {bold('Settings → Integrations')}")
    print(f"    3. Copy your  {bold('Personal API Token')}")
    print()

    while True:
        token = prompt("Paste your Apify token:", secret=True, default=existing)
        if not token:
            err("Token cannot be empty.")
            continue

        try:
            username = spinner("Validating token…", lambda: validate_apify(token))
            ok(f"Token accepted — Apify account: {bold(username)}")
            return token
        except ValueError as e:
            err(str(e))
            print()
            try:
                again = input(f"  {yellow('Try again?')} [Y/n]  ").strip().lower()
            except (KeyboardInterrupt, EOFError):
                sys.exit(0)
            if again == "n":
                if existing:
                    warn("Keeping your previous token.")
                    return existing
                sys.exit(1)

def step_telegram_bot(existing: str) -> tuple[str, str]:
    """Returns (bot_token, chat_id)."""
    step_header(2, 3, "Telegram Bot Token")
    print("  JobPilot sends your daily digest to a Telegram bot you own.")
    print()
    print(f"  {bold('How to get a bot token:')}")
    print(f"    1. Open Telegram and message  {cyan('@BotFather')}")
    print(f"       ({cyan('https://t.me/BotFather')})")
    print(f"    2. Send  {bold('/newbot')}  and follow the prompts")
    print(f"    3. BotFather replies with a token like:")
    print(f"       {dim('123456789:AAH_xxxxxxxxxxxxxxxxxxxxx')}")
    print()

    while True:
        token = prompt("Paste your Telegram bot token:", secret=True, default=existing)
        if not token:
            err("Token cannot be empty.")
            continue

        try:
            bot_name = spinner("Validating bot token…", lambda: validate_telegram_bot(token))
            ok(f"Bot confirmed — @{bold(bot_name)}")
            break
        except ValueError as e:
            err(str(e))
            print()
            try:
                again = input(f"  {yellow('Try again?')} [Y/n]  ").strip().lower()
            except (KeyboardInterrupt, EOFError):
                sys.exit(0)
            if again == "n":
                if existing:
                    warn("Keeping your previous token.")
                    return existing, ""
                sys.exit(1)

    # Auto-detect chat ID
    step_header(3, 3, "Telegram Chat ID")
    print("  JobPilot needs your personal chat ID to know where to send messages.")
    print()
    print(f"  {bold('Quick way — let the wizard fetch it for you:')}")
    print(f"    1. Open Telegram")
    print(f"    2. Send ANY message to your bot (e.g. \"hi\")")
    print(f"    3. Come back here and press Enter")
    print()

    try:
        input(f"  {dim('Press Enter once you have messaged your bot...')}")
    except (KeyboardInterrupt, EOFError):
        sys.exit(0)
    print()

    chat_id = spinner("Fetching chat ID from Telegram…", lambda: fetch_chat_id(token))

    if chat_id:
        ok(f"Chat ID detected: {bold(chat_id)}")
        print()
        try:
            confirm = input(f"  Use this chat ID? [Y/n]  ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            sys.exit(0)
        if confirm != "n":
            return token, chat_id

    # Fallback: manual entry
    warn("Could not auto-detect. You can find it manually:")
    print()
    print(f"    Open this URL in a browser (replace <TOKEN> with your bot token):")
    print(f"    {cyan('https://api.telegram.org/bot<TOKEN>/getUpdates')}")
    print(f"    Look for  {bold('\"chat\":{\"id\":123456789}')}")
    print()

    while True:
        cid = prompt("Paste your chat ID:", secret=False, default="")
        if cid.lstrip("-").isdigit():
            return token, cid
        err("Chat ID must be a number (may be negative for groups).")

# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    data_dir = jobpilot_dir()
    env_path = data_dir / ".env"

    banner()

    print(f"  This wizard collects your API keys and stores them in:")
    print(f"    {bold(str(env_path))}")
    print()
    print(f"  {dim('To change a key later:  re-run ./setup.sh')}")
    print(f"  {dim('Or edit the file above directly.')}")

    # Load what's already there
    existing = load_env(env_path)
    has_keys = any(existing.get(k) for k in ("APIFY_TOKEN", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"))

    if has_keys:
        print()
        warn("Existing keys found. You will be asked to confirm or replace each one.")

    pause()

    apify_token = step_apify(existing.get("APIFY_TOKEN", ""))

    bot_token, chat_id = step_telegram_bot(
        existing.get("TELEGRAM_BOT_TOKEN", "")
    )
    if not chat_id:
        chat_id = existing.get("TELEGRAM_CHAT_ID", "")

    # Write .env
    secrets: dict[str, str] = {
        "APIFY_TOKEN":          apify_token,
        "TELEGRAM_BOT_TOKEN":   bot_token,
        "TELEGRAM_CHAT_ID":     chat_id,
    }
    # Preserve any extra keys already in the file (e.g. GOOGLE_SERVICE_ACCOUNT_JSON)
    for k, v in existing.items():
        if k not in secrets:
            secrets[k] = v

    write_env(env_path, secrets)

    print()
    hr("═")
    print()
    ok(bold("All secrets saved."))
    print()
    info(f"Stored in: {str(env_path)}")
    info("To change a key: re-run  ./setup.sh  or edit the file above.")
    print()
    print(f"  {bold('Next steps:')}")
    print()
    print(f"  {cyan('1.')} Connect Google Drive in Claude Desktop:")
    print(f"     {bold('Settings → Connections → Google Drive')}")
    print()
    print(f"  {cyan('2.')} Create a folder called  {bold('jobpilot-resume')}  in your Google Drive")
    print(f"     and upload your resume as a PDF file into it.")
    print()
    print(f"  {cyan('3.')} Run  {cyan('/job-setup')}  inside Claude Desktop.")
    print(f"     It will find your resume and guide you through the rest.")
    print()
    hr("═")
    print()

if __name__ == "__main__":
    main()
