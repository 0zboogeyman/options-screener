#!/usr/bin/env python3
"""Container-internal ETL scheduler.

Run by supervisord alongside uvicorn/node. Computes the next firing time
from settings.etl_schedule and invokes etl_daily.run_once() in-process.

Supported schedule formats (configured via ETL_SCHEDULE env):
  * "HH:MM"        daily fire at HH:MM (UTC). Default: 08:05 (= 16:05 Taipei/Beijing, UTC+8)
  * "@every Nh"    fire every N hours (e.g. @every 6h)
  * "@every Nm"    fire every N minutes (e.g. @every 30m)
  * "off"          disable the scheduler loop; process exits immediately
"""
from __future__ import annotations

import asyncio
import logging
import re
import signal
import sys
import time
from datetime import datetime, timedelta, timezone

from app.core.config import settings
from app.core.logging import setup_logging

setup_logging(settings.log_level)
logger = logging.getLogger("etl.scheduler")

from scripts import etl_daily  # noqa: E402  (import after logging setup)


_EVERY_RE = re.compile(r"^@every\s+(\d+)([hm])$", re.IGNORECASE)
_HHMM_RE = re.compile(r"^(\d{1,2}):(\d{2})$")


def _next_run(schedule: str, now: datetime) -> datetime | None:
    """Return the next firing datetime (UTC) strictly after ``now``."""
    schedule = (schedule or "").strip()
    if not schedule or schedule.lower() == "off":
        return None
    m = _EVERY_RE.match(schedule)
    if m:
        n, unit = int(m.group(1)), m.group(2).lower()
        delta = timedelta(hours=n) if unit == "h" else timedelta(minutes=n)
        return now + delta
    m = _HHMM_RE.match(schedule)
    if m:
        hour, minute = int(m.group(1)), int(m.group(2))
        today = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        return today if today > now else today + timedelta(days=1)
    raise ValueError(f"Invalid ETL schedule: {schedule!r}")


class _StopFlag:
    def __init__(self) -> None:
        self._set = False

    def set(self) -> None:
        self._set = True

    def is_set(self) -> bool:
        return self._set


def _sleep_until(target: datetime, stop: _StopFlag) -> bool:
    secs = max(0.0, (target - datetime.now(tz=timezone.utc)).total_seconds())
    logger.info("next ETL at %s (sleeping %.0fs)", target.isoformat(), secs)
    deadline = time.monotonic() + secs
    while time.monotonic() < deadline:
        if stop.is_set():
            return False
        time.sleep(min(5.0, deadline - time.monotonic()))
    return True


def main() -> int:
    stop = _StopFlag()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())

    schedule = settings.etl_schedule
    logger.info("etl-scheduler starting with schedule=%s", schedule)
    if schedule.strip().lower() == "off":
        logger.info("schedule=off, exiting")
        return 0

    while not stop.is_set():
        now = datetime.now(tz=timezone.utc)
        try:
            nxt = _next_run(schedule, now)
        except ValueError as exc:
            logger.error("%s; scheduler stops", exc)
            return 2
        if nxt is None:
            return 0
        if not _sleep_until(nxt, stop):
            return 0
        if stop.is_set():
            return 0
        date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        logger.info("scheduler firing ETL for date=%s", date_str)
        try:
            asyncio.run(etl_daily.run_once(date_str, bases=settings.etl_bases))
        except Exception:  # noqa: BLE001
            logger.exception("scheduled ETL failed; will retry next cycle")
    return 0


if __name__ == "__main__":
    sys.exit(main())
