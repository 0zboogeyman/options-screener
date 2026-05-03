from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ..services.loader import list_available_dates, list_expiries_for, get_manifest


router = APIRouter()


@router.get("/meta/dates")
def get_dates():
    return {"dates": list_available_dates()}


@router.get("/expiries")
def get_expiries(
    base: str = Query(..., regex="^(BTC|ETH)$"),
    date: str = Query(..., description="YYYY-MM-DD"),
):
    try:
        expiries = list_expiries_for(date=date, base=base)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="date/base not found")
    return {"date": date, "base": base, "expiries": expiries}


@router.get("/meta/asof")
def get_asof(
    base: str = Query(..., regex="^(BTC|ETH)$"),
    date: str = Query(..., description="YYYY-MM-DD"),
):
    try:
        manifest = get_manifest(date=date)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="manifest not found for date")

    asof = manifest.get("asof_ts")
    bases = manifest.get("bases", [])
    expiries = manifest.get("expiries", {}).get(base, []) if manifest else []
    return {"date": date, "base": base, "asof_ts": asof, "expiries": expiries}

