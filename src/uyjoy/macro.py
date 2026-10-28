"""Macro context (policy rate, inflation, exchange rate, deals, mortgages, construction) for the facts pack.

The values live in config/macro/*.csv with a source for every quarterly value (see config/macro/README.md).
"""
from __future__ import annotations

import math

import pandas as pd

from .config import CONFIG_DIR

DIR = CONFIG_DIR / "macro"
ANNUAL_SOURCE = ("Oʻzbekiston ipotekani qayta moliyalashtirish kompaniyasi, 2025-yil 4-chorak sharhi "
                 "(MB, IITM, Urbanizatsiya va uy-joy bozorini barqaror rivojlantirish milliy qoʻmitasi maʼlumotlari)")


def _f(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(x) else x


def block(period: str) -> dict:
    qf, af = DIR / "quarterly.csv", DIR / "annual.csv"
    if not qf.exists():
        return {}
    q = pd.read_csv(qf, dtype={"quarter": str})
    p = pd.Period(period, "Q")
    q = q[q.quarter.map(lambda s: pd.Period(s, "Q") <= p)].sort_values("quarter")
    rates = pd.read_csv(CONFIG_DIR / "usd_uzs_quarter_end.csv", dtype={"period": str}).set_index("period")["rate"]
    rows = [{"quarter": r.quarter, "base_rate_pct": _f(r.base_rate_pct), "inflation_yoy_pct": _f(r.inflation_yoy_pct),
             "usd_uzs": _f(rates.get(r.quarter))} for r in q.itertuples()]
    cur = next((r for r in rows if r["quarter"] == period), None)
    prev = next((r for r in rows if r["quarter"] == str(p - 1)), None)
    out = {"id": "makro", "series": rows, "sources": sorted(set(q.base_rate_source) | set(q.inflation_source))}
    if cur:
        out["base_rate_pct"] = cur["base_rate_pct"]
        out["inflation_yoy_pct"] = cur["inflation_yoy_pct"]
        if cur["base_rate_pct"] is not None and cur["inflation_yoy_pct"] is not None:
            out["real_rate_pp"] = round(cur["base_rate_pct"] - cur["inflation_yoy_pct"], 1)
        if prev and prev["inflation_yoy_pct"] is not None and cur["inflation_yoy_pct"] is not None:
            out["inflation_change_pp"] = round(cur["inflation_yoy_pct"] - prev["inflation_yoy_pct"], 1)
    if af.exists():
        a = pd.read_csv(af)
        out["annual"] = {"source": ANNUAL_SOURCE, "rows": [
            {"year": int(r.year), "deals": _f(r.deals), "mortgages": _f(r.mortgages),
             "mortgage_share_pct": round(100 * r.mortgages / r.deals, 1) if _f(r.deals) and _f(r.mortgages) else None,
             "housing_built_k": _f(r.housing_built_k), "plan": bool(r.housing_plan),
             "mortgage_primary_bn": _f(r.mortgage_primary_bn), "mortgage_secondary_bn": _f(r.mortgage_secondary_bn)}
            for r in a.itertuples()]}
    return out
