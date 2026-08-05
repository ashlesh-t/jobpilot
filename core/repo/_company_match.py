"""Company-name normalization shared by contacts.for_company() and jobs.get()'s
contact attachment.

A 300-row spreadsheet of company names will never match `jobs.company` exactly —
casing, legal suffixes ("Inc", "Pvt Ltd") and stray whitespace all vary. Without this,
a contact at "Google LLC" would silently never match a job at "Google", and the UI
would just show "no contacts" — wrong, not obviously wrong.
"""
from __future__ import annotations

import re

_SUFFIXES = (
    "private limited", "pvt ltd", "pvt. ltd.", "pvt ltd.", "ltd", "limited",
    "llc", "inc", "incorporated", "corp", "corporation", "co", "gmbh", "plc",
)
_SUFFIX_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(s) for s in _SUFFIXES) + r")\.?\s*$",
    re.IGNORECASE,
)
_PUNCT_RE = re.compile(r"[.,]")
_WS_RE = re.compile(r"\s+")


def normalize_company(name: str) -> str:
    """"Google LLC" / "google, inc." / "Google Inc" / "  Google  " -> "google"."""
    if not name:
        return ""
    text = _PUNCT_RE.sub("", name).strip()
    # Strip a trailing legal suffix, possibly more than one ("Foo Pvt Ltd Inc").
    while True:
        stripped = _SUFFIX_RE.sub("", text).strip()
        if stripped == text:
            break
        text = stripped
    return _WS_RE.sub(" ", text).strip().lower()
