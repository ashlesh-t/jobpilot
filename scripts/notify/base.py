"""Notifier interface — one method surface every delivery channel implements."""
from __future__ import annotations

import abc
from pathlib import Path


class Notifier(abc.ABC):
    #: stable id used in preferences.notify_channels + API ("telegram" | "discord" | …)
    name: str = "base"
    #: human label for the UI
    label: str = "Base"

    @abc.abstractmethod
    def available(self) -> tuple[bool, str]:
        """Return (configured_and_usable, reason_if_not)."""
        raise NotImplementedError

    @abc.abstractmethod
    def send_digest(self, text: str) -> None:
        """Send the plain-text run digest."""
        raise NotImplementedError

    @abc.abstractmethod
    def send_document(self, path: Path, caption: str = "") -> None:
        """Send a file (XLSX report, tailored resume PDF)."""
        raise NotImplementedError

    def test(self) -> None:
        """Send a connectivity test message. Default delegates to send_digest."""
        self.send_digest("JobPilot connected ✓")
