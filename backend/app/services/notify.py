"""Telegram Bot 推送：每日策略精选 + 异常警报。

启用条件：settings.telegram_bot_token 与 telegram_chat_id 均配置。
未配置时所有函数静默返回（个人本地开发不打扰）。

调用约定：
  * 仅由 etl-scheduler（定时 ETL）以 notify=True 触发，每日一条精选；
    手动触发 /api/etl/run 不推送（用户就在页面上），也避免同日重复推送。
  * 全部网络异常静默吞掉——推送失败绝不能影响 ETL 主流程。

Telegram Bot API：POST https://api.telegram.org/bot<token>/sendMessage
（纯文本发送，不用 parse_mode，避免 Markdown 转义坑）。
"""
from __future__ import annotations

import logging
from typing import Dict, List

import httpx

from ..core.config import settings

logger = logging.getLogger(__name__)

_API_BASE = "https://api.telegram.org"
_TIMEOUT = 15.0
# DVOL 日环比跳变超过该比例触发警报
_DVOL_JUMP_ALERT = 0.20


def _enabled() -> bool:
    return bool(settings.telegram_bot_token and settings.telegram_chat_id)


async def send_message(text: str) -> bool:
    """发送纯文本消息；未配置或网络失败返回 False。"""
    if not _enabled():
        return False
    url = f"{_API_BASE}/bot{settings.telegram_bot_token}/sendMessage"
    payload = {
        "chat_id": settings.telegram_chat_id,
        "text": text[:4000],  # Telegram 单条上限 4096
        "disable_web_page_preview": True,
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.post(url, json=payload)
            if r.status_code != 200:
                logger.warning("Telegram send failed: %s %s", r.status_code, r.text[:200])
                return False
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Telegram send error: %s", exc)
        return False


# ---------------------------------------------------------------------------
# 每日策略精选
# ---------------------------------------------------------------------------

def _fmt_ic(c: Dict, i: int) -> str:
    ks = "/".join(f"{k:,.0f}" for k in c["strikes"])
    return (
        f"{i}. {c['expiry_date']} ({c['dte']:.0f}d) {ks}\n"
        f"   胜率 {c['pop'] * 100:.0f}% · APR {c['apr_on_max_loss'] * 100:.0f}% "
        f"· 收 ${c['credit_usd']:.0f} · 评分 {c['score']:.0f}"
    )


def _fmt_strangle(c: Dict, i: int) -> str:
    ks = "/".join(f"{k:,.0f}" for k in c["strikes"])
    apr = f"{c['apr_on_im'] * 100:.0f}%" if c.get("apr_on_im") else "—"
    return (
        f"{i}. {c['expiry_date']} ({c['dte']:.0f}d) {ks}\n"
        f"   胜率 {c['pop'] * 100:.0f}% · APR(保证金) {apr} "
        f"· 收 ${c['credit_usd']:.0f} · 尾部 ${c['tail_loss_est_usd']:.0f}"
    )


def _fmt_csp(c: Dict, i: int) -> str:
    return (
        f"{i}. {c['expiry_date']} K={c['strike']:,.0f}\n"
        f"   折扣 {c['discount_pct'] * 100:.1f}% · APR {c['apr'] * 100:.0f}% "
        f"· 收 ${c['premium']:.0f} · 评分 {c['score']:.0f}"
    )


def _daily_picks_for_base(date: str, base: str) -> List[str]:
    """同步扫描取各策略 top（供线程池调用，避免阻塞事件循环）。"""
    from .loader import load_chain_for
    from .multi_leg import scan_iron_condor, scan_strangle
    from .single_leg import scan_csp
    from .vol_history import current_iv_metrics, load_svi_surface

    chain, meta = load_chain_for(date=date, base=base)
    svi = load_svi_surface(date, base)
    ivp = current_iv_metrics(base).get("ivp")

    lines: List[str] = []
    dvol_txt = f"{meta.dvol_index:.1f}%" if meta.dvol_index else "—"
    ivp_txt = f"{ivp * 100:.0f}%" if ivp is not None else "—"
    lines.append(f"📊 {base} 每日策略精选（{date}）")
    lines.append(f"现货 ${meta.spot_price:,.0f} · DVOL {dvol_txt} · IVP {ivp_txt}")

    try:
        ic = scan_iron_condor(chain, meta, svi, return_count=2, ivp=ivp)
        if ic["candidates"]:
            lines.append("\n🦅 铁秃鹰")
            lines += [_fmt_ic(c, i + 1) for i, c in enumerate(ic["candidates"])]
    except Exception:
        logger.warning("picks: IC scan failed base=%s", base, exc_info=True)

    try:
        st = scan_strangle(chain, meta, svi, side="short", return_count=2, ivp=ivp)
        if st["short"]:
            lines.append("\n⚡ 宽跨 Short（理论亏损无限，注意仓位）")
            lines += [_fmt_strangle(c, i + 1) for i, c in enumerate(st["short"])]
    except Exception:
        logger.warning("picks: strangle scan failed base=%s", base, exc_info=True)

    try:
        # 与前端 UI 同口径（默认 max_spread_bps=500 过紧会漏掉多数候选）
        csp = scan_csp(chain, meta, max_spread_bps=1500, return_count=2)
        if csp["candidates"]:
            lines.append("\n💰 低吸收租（CSP）")
            lines += [_fmt_csp(c, i + 1) for i, c in enumerate(csp["candidates"])]
    except Exception:
        logger.warning("picks: CSP scan failed base=%s", base, exc_info=True)

    lines.append("\n仅教育参考，非投资建议")
    return lines


async def push_daily_picks(date: str, bases: List[str]) -> None:
    """ETL 完成后推送每日策略精选（每币种一条消息）。"""
    if not _enabled():
        return
    import asyncio

    loop = asyncio.get_running_loop()
    for base in bases:
        try:
            lines = await loop.run_in_executor(None, _daily_picks_for_base, date, base)
            ok = await send_message("\n".join(lines))
            logger.info("Telegram daily picks base=%s sent=%s", base, ok)
        except Exception:
            logger.warning("Telegram daily picks failed base=%s", base, exc_info=True)


# ---------------------------------------------------------------------------
# 异常警报
# ---------------------------------------------------------------------------

async def alert_etl_failure(error: str) -> None:
    """ETL 失败警报（数据将 stale）。"""
    await send_message(f"⚠️ ETL 执行失败，今日数据可能未更新：\n{error[:500]}")


async def check_dvol_jump(date: str, bases: List[str]) -> None:
    """DVOL 日环比跳变 >20% 时警报。"""
    if not _enabled():
        return
    import pandas as pd
    from .vol_history import load_dvol_history

    for base in bases:
        try:
            df = load_dvol_history(base)
            if len(df) < 2:
                continue
            prev, cur = float(df["close"].iloc[-2]), float(df["close"].iloc[-1])
            if prev <= 0:
                continue
            change = (cur - prev) / prev
            if abs(change) >= _DVOL_JUMP_ALERT:
                direction = "飙升" if change > 0 else "骤降"
                await send_message(
                    f"🌡️ {base} DVOL {direction} {abs(change) * 100:.0f}%："
                    f"{prev:.1f}% → {cur:.1f}%（{date}）"
                )
        except Exception:
            logger.warning("DVOL jump check failed base=%s", base, exc_info=True)
