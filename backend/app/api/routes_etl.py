"""手动 ETL 触发与运行状态查询。

设计要点：
  * POST /api/etl/run    触发一次 ETL（投递到常驻工作线程，立即返回不阻塞）；
    ETL 内部有跨进程文件锁（etl_daily._EtlLock），与 etl-scheduler 的定时
    触发互斥——拿到锁才真正执行，拿不到会在 last_error 中体现。
  * GET  /api/etl/status 查询运行状态（前端轮询用）。
  * 后台执行模型：模块级 daemon 工作线程 + queue。为什么不挂在请求事件
    循环上（asyncio.create_task）：请求循环的生命周期不该决定后台任务
    生死（TestClient 每请求独立循环会杀死任务；真实 uvicorn 下虽可用，
    但 CPU 密集的 SVI 拟合仍需隔离）。独立线程 + 独立事件循环是确定性
    最强、测试/生产行为一致的方案。
  * 配置 ADMIN_TOKEN 后两端点均须带 X-Admin-Token 头，否则 401；
    未配置（本地开发）放行——公网部署务必配置。
  * 缓存无需显式失效：链缓存以 manifest asof_ts 为版本号、SVI 缓存以文件
    mtime 为 key，ETL 落新数据后下次扫描自然读到新版。
"""
from __future__ import annotations

import asyncio
import json
import logging
import queue
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request

from ..core.config import settings
from ..core.ratelimit import limiter

logger = logging.getLogger(__name__)

router = APIRouter()

# 单 uvicorn 进程内的运行状态（worker=1，模块级单例足够；
# worker 线程写、请求线程读，dict 整体赋值在 GIL 下原子，展示性状态无锁）
_ETL_STATE: Dict[str, Any] = {
    "running": False,
    "last_started": None,    # ISO 8601 UTC
    "last_finished": None,   # ISO 8601 UTC
    "last_error": None,      # 最近一次失败的简要信息
    "last_trigger": None,    # "manual"
}

_TASK_QUEUE: "queue.Queue[tuple]" = queue.Queue()
_WORKER_LOCK = threading.Lock()
_WORKER_STARTED = False

# 手动触发限流（独立于扫描端点，每次调用都会打 Deribit API）
_RUN_RATE_LIMIT = "6/hour"
_STATUS_RATE_LIMIT = "60/minute"


def _check_admin_token(request: Request) -> None:
    expected = settings.admin_token
    if not expected:
        return
    provided = request.headers.get("X-Admin-Token", "")
    if not secrets.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="invalid admin token")


def _utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds")


def _worker_loop() -> None:
    """常驻 ETL 工作线程：从队列取任务，独立事件循环执行。"""
    from scripts import etl_daily  # 延迟导入：脚本依赖 app 包上下文

    while True:
        date_str, bases = _TASK_QUEUE.get()
        try:
            logger.info("manual ETL started date=%s", date_str)
            asyncio.run(etl_daily.run_once(date_str, bases=bases))
            _ETL_STATE.update(running=False, last_finished=_utc_now_iso(), last_error=None)
            logger.info("manual ETL finished date=%s", date_str)
        except etl_daily.EtlAlreadyRunningError:
            # 锁竞争（另一进程/调度器正在跑 ETL）属正常跳过，不污染失败状态
            _ETL_STATE.update(running=False, last_finished=_utc_now_iso(), last_error=None)
            logger.info("manual ETL skipped: another run in progress (date=%s)", date_str)
        except Exception as exc:  # noqa: BLE001 — 状态必须落盘，worker 线程不能死
            # 不向状态里写入原始异常文本（防止经 /etl/status 泄漏敏感路径/SQL 等）；
            # 仅记录分类错误码，完整 traceback 落服务端日志。
            _ETL_STATE.update(running=False, last_finished=_utc_now_iso(), last_error="etl_failed")
            logger.error("manual ETL failed: %s", exc, exc_info=True)
        finally:
            _TASK_QUEUE.task_done()


def _ensure_worker() -> None:
    global _WORKER_STARTED
    with _WORKER_LOCK:
        if not _WORKER_STARTED:
            t = threading.Thread(target=_worker_loop, name="etl-worker", daemon=True)
            t.start()
            _WORKER_STARTED = True


@router.post("/etl/run")
@limiter.limit(_RUN_RATE_LIMIT)
def trigger_etl(request: Request) -> Dict[str, Any]:
    _check_admin_token(request)

    # 先确保 worker 线程已启动（_ensure_worker 内部自带 _WORKER_LOCK，需在
    # 外层加锁前调用，避免非重入锁死锁）。worker 阻塞在队列 get 上，提前
    # 启动无副作用。
    _ensure_worker()
    date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    # TOCTOU 修复：running 的"检查并置位"必须原子，否则并发请求可能同时
    # 通过 running=False 检查、双双入队，导致同一时刻两轮 ETL 抢文件锁。
    with _WORKER_LOCK:
        if _ETL_STATE["running"]:
            raise HTTPException(status_code=409, detail="ETL already running")
        _ETL_STATE.update(
            running=True,
            last_started=_utc_now_iso(),
            last_error=None,
            last_trigger="manual",
        )
        _TASK_QUEUE.put((date_str, settings.etl_bases))
    logger.info("manual ETL queued date=%s", date_str)
    return {"status": "started", "last_started": _ETL_STATE["last_started"]}


@router.get("/etl/status")
@limiter.limit(_STATUS_RATE_LIMIT)
def etl_status(request: Request) -> Dict[str, Any]:
    _check_admin_token(request)
    state = dict(_ETL_STATE)
    # 审计 M4：并入最近一次调度运行记录（etl_runs.json 由 etl_scheduler 写入，
    # 容器重启后历史仍可查；读取失败静默降级）
    state["last_scheduled"] = _read_last_scheduled()
    return state


def _read_last_scheduled() -> Optional[Dict[str, Any]]:
    try:
        runs_path = Path(settings.data_root).parent / "etl_runs.json"
        if not runs_path.exists():
            return None
        data = json.loads(runs_path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return None
        for rec in reversed(data):
            if isinstance(rec, dict) and rec.get("trigger") == "scheduler":
                return {k: rec.get(k) for k in ("run_id", "date", "started_at", "finished_at", "status", "attempts", "error") if rec.get(k) is not None}
        return None
    except Exception:
        return None
