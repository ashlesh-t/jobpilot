"""Salary research (Layer B helper).

Given (company, role, location), searches public salary sources and parses LPA ranges.
Uses DuckDuckGo's free HTML endpoint to avoid API keys. If network/parse fails it returns a
conservative estimate with empty sources so the pipeline keeps moving.

Note: actual LLM-driven web search (when run inside Claude) can override/augment this — the
script provides a zero-LLM fallback for scheduled runs.
"""
from __future__ import annotations

import json
import re
import sys

import requests

SEARCH_TEMPLATES = [
    "{company} {role} salary India AmbitionBox",
    "{company} {role} LPA Glassdoor",
    "{role} fresher salary {location} reddit developersIndia",
]


def ddg_search(query: str) -> list:
    """Return a list of (title, snippet, url) from DuckDuckGo HTML. Empty on failure."""
    try:
        resp = requests.post(
            "https://html.duckduckgo.com/html/",
            data={"q": query},
            headers={"User-Agent": "Mozilla/5.0 (JobPilot)"},
            timeout=20,
        )
        resp.raise_for_status()
        html = resp.text
    except Exception as exc:  # noqa: BLE001
        print(f"[salary] search failed for '{query}': {exc}", file=sys.stderr)
        return []
    results = []
    for m in re.finditer(
        r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html, re.S
    ):
        url = m.group(1)
        title = re.sub(r"<[^>]+>", "", m.group(2))
        results.append((title, "", url))
    snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', html, re.S)
    for i, sn in enumerate(snippets):
        if i < len(results):
            results[i] = (results[i][0], re.sub(r"<[^>]+>", "", sn), results[i][2])
    return results


def parse_lpa(text: str) -> list:
    """Extract LPA figures from text. Returns a list of floats."""
    vals = []
    for m in re.finditer(
        r"(\d+(?:\.\d+)?)\s*(?:-|to|–)\s*(\d+(?:\.\d+)?)\s*(?:lpa|lakhs?|l)\b", text, re.I
    ):
        vals.extend([float(m.group(1)), float(m.group(2))])
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*(?:lpa|lakhs?)\b", text, re.I):
        vals.append(float(m.group(1)))
    return [v for v in vals if 1 <= v <= 200]


def research(company: str, role: str, location: str = "Bengaluru") -> dict:
    all_vals = []
    sources = []
    for tmpl in SEARCH_TEMPLATES:
        query = tmpl.format(company=company, role=role, location=location)
        for title, snippet, url in ddg_search(query)[:5]:
            all_vals.extend(parse_lpa(title + " " + snippet))
            if url and url not in sources:
                sources.append(url)
        if len(all_vals) >= 6:
            break

    if all_vals:
        all_vals.sort()
        min_lpa = round(all_vals[0], 1)
        max_lpa = round(all_vals[-1], 1)
        median_lpa = round(all_vals[len(all_vals) // 2], 1)
    else:
        # Conservative fallback when nothing parsed
        min_lpa, median_lpa, max_lpa = 6.0, 10.0, 15.0

    demand_target_low = min_lpa + (max_lpa - min_lpa) * 0.4
    demand_estimate = (
        f"Based on market data, you can reasonably demand "
        f"{demand_target_low:.0f}-{max_lpa:.0f} LPA"
    )

    return {
        "min_lpa": min_lpa,
        "max_lpa": max_lpa,
        "median_lpa": median_lpa,
        "demand_estimate": demand_estimate,
        "sources": sources[:6],
    }


def main() -> None:
    if len(sys.argv) < 3:
        print("usage: python3 salary_research.py <company> <role> [location]", file=sys.stderr)
        sys.exit(1)
    company = sys.argv[1]
    role = sys.argv[2]
    location = sys.argv[3] if len(sys.argv) > 3 else "Bengaluru"
    print(json.dumps(research(company, role, location), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
