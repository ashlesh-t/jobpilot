"""Unit tests for the event layer — no network, no LLM."""
import json
import os
from pathlib import Path

import run_events
from engines.base import map_tool_to_stage, RunEvent
from engines.claude_code import ClaudeCodeEngine


def test_emit_noop_without_run_id(tmp_path, monkeypatch):
    monkeypatch.delenv("JOBPILOT_RUN_ID", raising=False)
    # should not raise and should not create anything
    run_events.emit("scrape", "done", "x", total=5)
    assert run_events.run_id() is None


def test_emit_writes_jsonl(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBPILOT_RUN_ID", "utest")
    monkeypatch.setenv("JOBPILOT_RUN_DIR", str(tmp_path))
    run_events.emit("scrape", "started", "begin")
    run_events.emit("scrape", "progress", "internshala", source="internshala", count=20)
    lines = (tmp_path / "events.jsonl").read_text().strip().splitlines()
    assert len(lines) == 2
    rec = json.loads(lines[1])
    assert rec["stage"] == "scrape"
    assert rec["data"]["count"] == 20
    assert rec["run_id"] == "utest"


def test_unknown_stage_downgrades_to_log(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBPILOT_RUN_ID", "utest2")
    monkeypatch.setenv("JOBPILOT_RUN_DIR", str(tmp_path))
    run_events.emit("bogus-stage", "progress", "hi")
    rec = json.loads((tmp_path / "events.jsonl").read_text().strip())
    assert rec["stage"] == "log"


def test_tool_to_stage_mapping():
    assert map_tool_to_stage("Bash", {"command": "python3 scripts/apify_scraper.py"}) == "scrape"
    assert map_tool_to_stage("Bash", {"command": "python3 scripts/dedupe.py"}) == "dedupe"
    assert map_tool_to_stage("Bash", {"command": "python3 scripts/filter.py"}) == "filter"
    assert map_tool_to_stage("Bash", {"command": "python3 scripts/report_generator.py"}) == "report"
    assert map_tool_to_stage("Bash", {"command": "tectonic /tmp/x.tex"}) == "tailor"
    assert map_tool_to_stage("Bash", {"command": "python3 scripts/telegram_notify.py"}) == "notify"
    assert map_tool_to_stage("WebSearch", {"query": "acme salary"}) == "salary"
    assert map_tool_to_stage("Read", {"file_path": "profile.json"}) is None


def test_claude_code_stream_parsing():
    eng = ClaudeCodeEngine()
    events = []
    line = json.dumps({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Bash",
         "input": {"command": "python3 scripts/filter.py"}}]}})
    eng._handle_line(line, events.append)
    stages = [(e.stage, e.status) for e in events]
    assert ("log", "progress") in stages       # tool narration
    assert ("filter", "started") in stages      # inferred stage
    final = eng._handle_line(json.dumps({"type": "result", "result": "Done."}), events.append)
    assert final == "Done."


def test_runevent_to_dict_shape():
    ev = RunEvent("score", "done", "scored 12", data={"n": 12})
    d = ev.to_dict()
    assert d["stage"] == "score" and d["data"]["n"] == 12 and "ts" in d
