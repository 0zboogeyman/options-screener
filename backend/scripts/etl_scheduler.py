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
import json
import logging
import os
import re
import signal
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from app.core.config import settings
from app.core.logging import setup_logging

setup_logging(settings.log_level)
logger = logging.getLogger("etl.scheduler")

from scripts import etl_daily  # noqa: E402  (import after logging setup)


_EVERY_RE = re.compile(r"^@every\s+(\d+)([hm])$", re.IGNORECASE)
_HHMM_RE = re.compile(r"^(\d{1,2}):(\d{2})$")

# 审计 M2：定时失败当日退避重试（固定间隔 30 分钟，最多 3 次）
RETRY_DELAY_MINUTES = 30
MAX_RETRIES = 3

# 审计 M4：调度运行状态文件（保留最近 _RUNS_KEEP 条），
# /api/etl/status 读取最近一条并入响应（容器重启后历史仍可查）。
ETL_RUNS_PATH: Path = Path(settings.data_root).parent / "etl_runs.json"
_RUNS_KEEP = 50


def _append_run_record(record: Dict[str, Any]) -> None:
    """追加一条调度运行记录到状态文件，仅保留最近 _RUNS_KEEP 条。

    可观测能力不影响主流程：读/写失败静默降级（仅告警日志）。
    """
    try:
        runs: list = []
        if ETL_RUNS_PATH.exists():
            try:
                data = json.loads(ETL_RUNS_PATH.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    runs = [r for r in data if isinstance(r, dict)]
            except Exception:
                runs = []
        runs.append(record)
        runs = runs[-_RUNS_KEEP:]
        ETL_RUNS_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = ETL_RUNS_PATH.with_name(ETL_RUNS_PATH.name + ".tmp")
        tmp.write_text(json.dumps(runs, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, ETL_RUNS_PATH)
    except Exception:
        logger.warning("failed to append etl_runs record", exc_info=True)


def _execute_round(date_str: str, run_id: str, stop: "_StopFlag") -> Dict[str, Any]:
    """执行一轮定时 ETL（含退避重试），写运行记录并返回。

    审计 M2：失败后按 RETRY_DELAY_MINUTES 退避重试，最多 MAX_RETRIES 次，
    重试成功即止；全部失败才发 Telegram 告警。
    审计项 5：锁冲突（EtlAlreadyRunningError）属正常跳过——仅 info 日志，
    不告警、不消耗重试次数、不计为失败。
    """
    started = datetime.now(tz=timezone.utc)
    record: Dict[str, Any] = {
        "run_id": run_id,
        "trigger": "scheduler",
        "date": date_str,
        "started_at": started.isoformat(timespec="seconds"),
    }
    attempts = 0  # 失败次数（成功/跳过不计）
    status = "failed"
    error: Optional[str] = None
    while True:
        try:
            asyncio.run(etl_daily.run_once(date_str, bases=settings.etl_bases, notify=True))
            status = "success"
            break
        except etl_daily.EtlAlreadyRunningError:
            # 审计项 5：另一轮 ETL 正在跑（手动触发/跨进程），正常跳过非失败
            logger.info("scheduled ETL skipped: another run in progress (date=%s)", date_str)
            status = "skipped"
            break
        except Exception as exc:  # noqa: BLE001
            attempts += 1
            # 只记异常类名，不写原始异常文本（避免经状态文件/告警泄漏敏感路径）
            error = type(exc).__name__
            logger.exception("scheduled ETL failed (attempt %d)", attempts)
            if attempts > MAX_RETRIES:
                break
            logger.info(
                "scheduled ETL retry %d/%d in %d minutes",
                attempts, MAX_RETRIES, RETRY_DELAY_MINUTES,
            )
            if not _sleep_until(
                datetime.now(tz=timezone.utc) + timedelta(minutes=RETRY_DELAY_MINUTES), stop
            ):
                break  # 等待退避期间收到停机信号：不再重试
    record["finished_at"] = datetime.now(tz=timezone.utc).isoformat(timespec="seconds")
    record["status"] = status
    record["attempts"] = attempts
    record["error"] = error
    if status == "failed" and not stop.is_set():
        try:
            from app.services import notify as notify_mod
            asyncio.run(notify_mod.alert_etl_failure(error or "unknown"))
        except Exception:
            logger.warning("failure alert skipped", exc_info=True)
    _append_run_record(record)
    return record


def _next_run(schedule: str, now: datetime) -> datetime | None:
    """Return the next firing datetime (UTC) strictly after ``now``."""
    schedule = (schedule or "").strip()
    if not schedule or schedule.lower() == "off":
        return None
    m = _EVERY_RE.match(schedule)
    if m:
        n, unit = int(m.group(1)), m.group(2).lower()
        if n < 1:
            raise ValueError(f"Invalid ETL interval: {schedule!r}")
        delta = timedelta(hours=n) if unit == "h" else timedelta(minutes=n)
        return now + delta
    m = _HHMM_RE.match(schedule)
    if m:
        hour, minute = int(m.group(1)), int(m.group(2))
        if hour > 23 or minute > 59:
            raise ValueError(f"Invalid ETL time: {schedule!r}")
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
        run_id = uuid.uuid4().hex[:12]
        logger.info("scheduler firing ETL for date=%s run_id=%s", date_str, run_id)
        _execute_round(date_str, run_id, stop)
    return 0


if __name__ == "__main__":
    sys.exit(main())
