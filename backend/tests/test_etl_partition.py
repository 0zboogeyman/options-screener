"""ETL 分区清理与重试谓词回归测试。

覆盖：
  D-1  同日去重仅在"最新分区完整（有 manifest 且 rows>0）"时删除旧分区，
       失败残留的坏分区不再顶掉完整好分区
  D-4  _retryable 统一重试谓词：429 与 5xx 可重试、其余 4xx 快速失败
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx
import pytest

from scripts import etl_daily


def _today_part(name: str) -> str:
    today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    return f"dt={today}-{name}"


def _write_manifest(part_dir, rows: int) -> None:
    (part_dir / "manifest.json").write_text(
        json.dumps({"rows": rows, "bases": ["BTC"]}), encoding="utf-8"
    )


class TestSameDayDedupGuard:
    """审计 D-1：坏分区不得顶掉完整好分区。"""

    def test_incomplete_newest_keeps_old_good(self, monkeypatch, tmp_path):
        monkeypatch.setattr(etl_daily, "DATA_ROOT", tmp_path)
        old = tmp_path / _today_part("08")
        new = tmp_path / _today_part("14")
        old.mkdir()
        new.mkdir()
        _write_manifest(old, rows=1234)   # 旧分区完整
        # 新分区无 manifest（失败残留）

        etl_daily.cleanup_old_partitions(keep_days=1000)

        assert old.exists(), "完整好分区不应被失败残留的坏分区顶掉"
        assert new.exists(), "失败残留分区保持原样等待重跑"

    def test_complete_newest_supersedes_old(self, monkeypatch, tmp_path):
        monkeypatch.setattr(etl_daily, "DATA_ROOT", tmp_path)
        old = tmp_path / _today_part("08")
        new = tmp_path / _today_part("14")
        old.mkdir()
        new.mkdir()
        _write_manifest(old, rows=1234)
        _write_manifest(new, rows=2000)   # 新分区完整

        etl_daily.cleanup_old_partitions(keep_days=1000)

        assert not old.exists(), "新分区完整时旧分区应被去重"
        assert new.exists()

    def test_expired_incomplete_not_deleted(self, monkeypatch, tmp_path):
        """超期清理只针对完整分区，避免误删仍在写入的分区。"""
        monkeypatch.setattr(etl_daily, "DATA_ROOT", tmp_path)
        old = tmp_path / "dt=2020-01-01-08"   # 远早于 keep_days
        old.mkdir()
        _write_manifest(old, rows=100)
        broken = tmp_path / "dt=2020-01-02-08"
        broken.mkdir()                         # 无 manifest

        etl_daily.cleanup_old_partitions(keep_days=30)

        assert not old.exists()
        assert broken.exists(), "不完整分区不做超期清理决策"


class TestRetryable:
    """审计 D-4：429/5xx 重试，其余 4xx 快速失败。"""

    def _status_error(self, code: int) -> httpx.HTTPStatusError:
        req = httpx.Request("GET", "https://example.com")
        resp = httpx.Response(code, request=req)
        return httpx.HTTPStatusError("err", request=req, response=resp)

    def test_429_retryable(self):
        assert etl_daily._retryable(self._status_error(429)) is True

    def test_5xx_retryable(self):
        assert etl_daily._retryable(self._status_error(502)) is True

    def test_4xx_fast_fail(self):
        for code in (400, 404, 422):
            assert etl_daily._retryable(self._status_error(code)) is False

    def test_timeout_retryable(self):
        assert etl_daily._retryable(httpx.TimeoutException("t")) is True
