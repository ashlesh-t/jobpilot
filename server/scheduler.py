"""Scheduler — fire runs at the user's chosen times, and survive the machine being off.

Three things v1 couldn't do:

  * **Slots are rows, not preference strings.** They're created, edited and deleted from
    the UI, each with its own timezone, mode and enabled flag.
  * **Catch-up.** If the machine was off when a slot was due, the run happens once when
    it comes back — not once per missed slot, and not at all if the miss is stale.
  * **Network retry.** No connection at fire time means a retry ladder, not a recorded
    failure. The run shows as "waiting for network" rather than pretending it succeeded.

The APScheduler timers are rebuilt from `schedule_slots` at every start, so the rows are
the source of truth and the jobstore is disposable.
"""
from __future__ import annotations

import asyncio
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

REPO_DIR = Path(__file__).resolve().parent.parent
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

from run_manager import RunBusyError, manager  # noqa: E402

DEFAULT_TZ = "Asia/Kolkata"

#: How long after a missed slot a catch-up run is still worth doing. Past this, the
#: postings have moved on and a surprise run is just noise.
CATCHUP_GRACE_HOURS = 6

#: Backoff for "the machine is awake but has no internet".
RETRY_LADDER_SECONDS = (60, 300, 900, 1800)


def _tz(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name or DEFAULT_TZ)
    except Exception:
        return ZoneInfo(DEFAULT_TZ)


def has_network(host: str = "1.1.1.1", port: int = 53, timeout: float = 3.0) -> bool:
    """Cheap reachability probe — a DNS-port TCP connect, no DNS lookup of its own."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


class Scheduler:
    def __init__(self):
        self._sched = AsyncIOScheduler(timezone=_tz(DEFAULT_TZ))
        self._started = False
        self._catchup_task: asyncio.Task | None = None

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    def start(self) -> None:
        if not self._started:
            self._sched.start()
            self._started = True
        self.reconfigure()
        self._schedule_catchup()

    def shutdown(self) -> None:
        if self._catchup_task and not self._catchup_task.done():
            self._catchup_task.cancel()
        if self._started:
            self._sched.shutdown(wait=False)
            self._started = False

    def reconfigure(self) -> None:
        """Rebuild every timer from the schedule_slots rows."""
        from core.repo import schedule as schedule_repo

        self._sched.remove_all_jobs()
        for slot in schedule_repo.list_all(enabled_only=True):
            try:
                hour, minute = (int(x) for x in slot["time"].split(":"))
            except (ValueError, AttributeError):
                continue
            self._sched.add_job(
                _fire,
                CronTrigger(hour=hour, minute=minute, day_of_week=slot["days"] or "*",
                            timezone=_tz(slot["timezone"])),
                id=f"slot-{slot['id']}",
                args=[slot["id"]],
                replace_existing=True,
                # Covers a slot that fires while the process is busy or briefly paused;
                # a machine that was *off* is handled by catch-up instead.
                misfire_grace_time=3600,
            )

    # ------------------------------------------------------------------ #
    # Catch-up
    # ------------------------------------------------------------------ #
    def _schedule_catchup(self) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._catchup_task = loop.create_task(self._run_catchup())

    async def _run_catchup(self) -> None:
        """Serve slots missed while the machine was off, once each."""
        from core.repo import schedule as schedule_repo
        from core.repo import settings as settings_repo

        await asyncio.sleep(5)  # let the service finish coming up first
        try:
            grace = int(settings_repo.get("catchup_grace_hours", CATCHUP_GRACE_HOURS)
                        or CATCHUP_GRACE_HOURS)
        except (TypeError, ValueError):
            grace = CATCHUP_GRACE_HOURS
        if grace <= 0:
            return  # catch-up disabled

        try:
            due = schedule_repo.missed_since_downtime(grace_hours=grace)
        except Exception:  # noqa: BLE001
            return
        if not due:
            return

        # At most one catch-up run per startup — firing several back to back would
        # queue runs the user never asked for.
        slot = due[0]
        occurrence = slot.get("occurrence")
        print(f"[scheduler] catching up '{slot['name']}' (was due {occurrence})")
        schedule_repo.record_fire(
            slot["id"],
            outcome="catchup",
            when=_parse(occurrence),
        )
        await _start(slot, trigger="catchup")

    # ------------------------------------------------------------------ #
    # Introspection
    # ------------------------------------------------------------------ #
    def jobs(self) -> list[dict]:
        return [
            {
                "id": job.id,
                "slot_id": job.args[0] if job.args else None,
                "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
            }
            for job in self._sched.get_jobs()
        ]

    def next_runs(self, count: int = 7) -> list[dict]:
        """The next few firings across all slots, for the timeline preview."""
        from core.repo import schedule as schedule_repo

        slots = {s["id"]: s for s in schedule_repo.list_all()}
        upcoming = []
        for job in self._sched.get_jobs():
            slot_id = job.args[0] if job.args else None
            slot = slots.get(slot_id)
            trigger = job.trigger
            when = job.next_run_time
            for _ in range(count):
                if when is None:
                    break
                upcoming.append({
                    "slot_id": slot_id,
                    "name": slot["name"] if slot else job.id,
                    "at": when.isoformat(),
                })
                when = trigger.get_next_fire_time(when, when)
        upcoming.sort(key=lambda item: item["at"])
        return upcoming[:count]

    @property
    def running(self) -> bool:
        return self._started


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


# --------------------------------------------------------------------------- #
# Firing
# --------------------------------------------------------------------------- #
async def _fire(slot_id: int) -> None:
    from core.repo import schedule as schedule_repo

    slot = schedule_repo.get(slot_id)
    if slot is None or not slot["enabled"]:
        return
    schedule_repo.record_fire(slot_id, outcome="started")
    await _start(slot, trigger="schedule")


async def _start(slot: dict, *, trigger: str) -> None:
    """Start a run for one slot, waiting out a missing network rather than failing."""
    from core.repo import schedule as schedule_repo

    for attempt, delay in enumerate((0, *RETRY_LADDER_SECONDS)):
        if delay:
            await asyncio.sleep(delay)
        if not await asyncio.to_thread(has_network):
            schedule_repo.set_outcome(slot["id"], "waiting for network")
            print(f"[scheduler] no network for '{slot['name']}' — retry {attempt + 1}")
            continue
        try:
            run = await manager.start_run(
                mode=slot.get("mode", "auto"),
                trigger=trigger,
                slot_name=slot["name"],
            )
        except RunBusyError:
            # A run is already going; stacking another would just queue duplicate work.
            schedule_repo.set_outcome(slot["id"], "skipped — already running")
            return
        except Exception as exc:  # noqa: BLE001
            schedule_repo.set_outcome(slot["id"], f"failed: {exc}"[:120])
            return
        schedule_repo.record_fire(slot["id"], run_id=run["id"], outcome="started")
        return

    schedule_repo.set_outcome(slot["id"], "gave up — no network")


scheduler = Scheduler()
