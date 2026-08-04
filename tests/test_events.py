"""Unit tests for the event layer — no network, no LLM."""
import asyncio
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


def test_claude_code_defaults_to_bypass_permissions(monkeypatch):
    monkeypatch.delenv("JOBPILOT_CLAUDE_PERMISSION_MODE", raising=False)
    assert ClaudeCodeEngine().permission_mode == "bypassPermissions"

    monkeypatch.setenv("JOBPILOT_CLAUDE_PERMISSION_MODE", "acceptEdits")
    assert ClaudeCodeEngine().permission_mode == "acceptEdits"  # env/arg still override


def test_claude_code_available_detects_a_deleted_install_dir(monkeypatch):
    """A service reinstalled/upgraded while still running ends up with its own cwd
    pointing at a directory that no longer exists — spawning `claude --version` into
    that fails with a confusing, runtime-specific error (observed: Bun's own mangled
    ENOENT) instead of a clear one. Regression guard for that failure class."""
    import engines.claude_code as cc

    monkeypatch.setattr(cc.shutil, "which", lambda _: "/usr/bin/claude")
    monkeypatch.setattr(cc, "REPO_DIR", Path("/nonexistent/deleted/jobpilot-bundle"))
    ok, reason = ClaudeCodeEngine().available()
    assert ok is False
    assert "reinstalled/upgraded" in reason
    assert "jobpilot stop && jobpilot start" in reason


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


async def test_claude_code_grants_access_to_the_data_dir(tmp_path, monkeypatch):
    """Regression guard: without --add-dir, every phase fails to read/write
    filtered.json, preferences.json, discovered.json etc. because Claude Code only
    trusts the cwd by default and the data dir lives outside REPO_DIR."""
    monkeypatch.setenv("JOBPILOT_DIR", str(tmp_path))

    eng = ClaudeCodeEngine()
    monkeypatch.setattr(eng, "available", lambda: (True, ""))

    class FakeStdout:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

    class FakeProc:
        stdout = FakeStdout()
        stderr = None
        returncode = 0

        async def wait(self):
            return 0

    captured = {}

    async def fake_exec(*cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return FakeProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    await eng.run("do the thing", "run123", lambda ev: None)

    cmd = captured["cmd"]
    assert "--add-dir" in cmd
    assert cmd[cmd.index("--add-dir") + 1] == str(tmp_path)

    # A single stream-json line carrying a big tool result (a fetched page, a long JD)
    # routinely exceeds asyncio's default 64 KiB reader limit — regression guard for
    # "Separator is found, but chunk is longer than limit" killing the whole phase.
    from engines.base import SUBPROCESS_STREAM_LIMIT
    assert captured["kwargs"]["limit"] == SUBPROCESS_STREAM_LIMIT
    assert SUBPROCESS_STREAM_LIMIT > 65536
