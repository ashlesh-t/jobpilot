"""Scheduler — fire /job-search at the user's IST slots via APScheduler.

Reads `schedule_slots_ist` from preferences and installs one cron job per slot in
Asia/Kolkata. Each entry is either a plain `"HH:MM"` string (original shape, still
supported) or `{"name": "...", "time": "HH:MM"}` (written by `jobpilot start`, which lets
several slots share the same clock time under distinct, disambiguated names). Each firing
calls RunManager.start_run(mode="auto"); the skill's own run_state.json logic then
alternates full vs native. Reconfigured live when the UI edits the schedule.
"""
from __future__ import annotations

from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from common import load_prefs  # noqa: E402
from run_manager import manager, RunBusyError  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")


class Scheduler:
    def __init__(self):
        self._sched = AsyncIOScheduler(timezone=IST)
        self._started = False

    def start(self) -> None:
        if not self._started:
            self._sched.start()
            self._started = True
        self.reconfigure()

    def shutdown(self) -> None:
        if self._started:
            self._sched.shutdown(wait=False)
            self._started = False

    def reconfigure(self) -> None:
        """Rebuild jobs from the current preferences.schedule_slots_ist."""
        self._sched.remove_all_jobs()
        for slot in load_prefs().get("schedule_slots_ist", []) or []:
            if isinstance(slot, dict):
                time_str = slot.get("time", "")
                label = slot.get("name") or time_str
            else:
                time_str = slot
                label = slot
            try:
                hh, mm = str(time_str).split(":")
                trigger = CronTrigger(hour=int(hh), minute=int(mm), timezone=IST)
            except Exception:
                continue
            self._sched.add_job(_fire, trigger, id=f"slot-{label}",
                                replace_existing=True, misfire_grace_time=3600)

    def jobs(self) -> list[dict]:
        return [
            {"id": j.id, "next_run": j.next_run_time.isoformat() if j.next_run_time else None}
            for j in self._sched.get_jobs()
        ]


async def _fire() -> None:
    try:
        await manager.start_run(mode="auto")
    except RunBusyError:
        pass  # a run is already active — skip this slot rather than stack runs


scheduler = Scheduler()
