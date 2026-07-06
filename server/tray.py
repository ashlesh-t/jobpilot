"""Optional tray launcher — `python -m server.tray`.

A menu-bar/tray icon that starts the service in a background thread and opens the browser.
The web app remains the product; this is just a convenience launcher for users who prefer
a click over a terminal. Requires the optional `pystray` + `Pillow` extras.
"""
from __future__ import annotations

import os
import sys
import threading
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

HOST = os.environ.get("JOBPILOT_HOST", "127.0.0.1")
PORT = int(os.environ.get("JOBPILOT_PORT", "8787"))
URL = f"http://{HOST}:{PORT}"


def _serve() -> None:
    import uvicorn
    from app import app
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")


def main() -> None:
    try:
        import pystray
        from PIL import Image, ImageDraw
    except Exception:
        print("Tray extras not installed. Run: pip install pystray Pillow")
        print(f"Falling back to foreground service at {URL}")
        _serve()
        return

    threading.Thread(target=_serve, daemon=True).start()

    # simple generated icon (indigo rounded square with a check)
    img = Image.new("RGB", (64, 64), "#4f46e5")
    d = ImageDraw.Draw(img)
    d.line((16, 34, 28, 46), fill="white", width=6)
    d.line((28, 46, 48, 20), fill="white", width=6)

    def _open(icon, item):
        webbrowser.open(URL)

    def _quit(icon, item):
        icon.stop()
        os._exit(0)

    menu = pystray.Menu(
        pystray.MenuItem("Open JobPilot", _open, default=True),
        pystray.MenuItem("Quit", _quit),
    )
    webbrowser.open(URL)
    pystray.Icon("JobPilot", img, "JobPilot", menu).run()


if __name__ == "__main__":
    main()
