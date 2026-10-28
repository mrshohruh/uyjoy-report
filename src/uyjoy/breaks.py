"""Series breaks and like-for-like price changes.

A series break is a month from which the source exports were cleaned differently
(declared in config/method.yaml `series_breaks`). Any comparison between a quarter
with months before the break and a quarter with months from it mixes two rule sets,
so it is flagged, and the report shows a like-for-like check next to it: the price
change of the same listings (same id) seen in both quarters, which does not depend
on which rows the export kept.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import Config

MAX_ABS_PCT = 50.0   # a listing id whose price moved more than this is treated as a different flat


def _q(q: str) -> pd.Period:
    return pd.Period(q, "Q")


def crossing(cfg: Config, earlier: str, later: str) -> list[dict]:
    """Breaks that fall between two quarters' data (earlier has months before, later has months from)."""
    out = []
    for b in cfg.method.get("series_breaks") or []:
        m = pd.Period(b["month"], "M")
        if _q(earlier).asfreq("M", "start") < m <= _q(later).asfreq("M", "end"):
            out.append(b)
    return out


def flags(cfg: Config, period: str) -> dict | None:
    qoq = crossing(cfg, str(_q(period) - 1), period)
    yoy = crossing(cfg, str(_q(period) - 4), period)
    if not qoq and not yoy:
        return None
    b = (qoq or yoy)[0]
    return {"month": b["month"], "note_uz": b["note_uz"], "title_uz": b.get("title_uz", ""),
            "keyword_uz": b.get("keyword_uz", "qayta ishlan"), "families": b.get("families", []),
            "qoq": bool(qoq), "yoy": bool(yoy)}


def like_for_like(df: pd.DataFrame, cfg: Config, earlier: str, later: str) -> pd.DataFrame:
    """Mean % price change of listings present in both quarters, by region x market (+ all regions)."""
    cols = ["family", "id", "region", "market", "price"]
    a = df[df.quarter == earlier][cols]
    b = df[df.quarter == later][cols]
    j = a.merge(b, on=["family", "id", "region", "market"], suffixes=("_a", "_b"))
    if j.empty:
        return pd.DataFrame(columns=["unit", "market", "n", "mean_pct", "changed_share"])
    j["pct"] = (j.price_b / j.price_a - 1) * 100
    j = j[j.pct.abs() <= MAX_ABS_PCT]
    sale = j[j.market.isin(["prim", "sec"])].assign(market="sale")
    j = pd.concat([j, sale], ignore_index=True)

    def agg(g):
        return pd.Series({"n": len(g), "mean_pct": g.pct.mean(), "changed_share": (g.pct != 0).mean()})

    by_region = j.groupby(["region", "market"]).apply(agg, include_groups=False).reset_index()
    by_region = by_region.rename(columns={"region": "unit"})
    total = j.groupby("market").apply(agg, include_groups=False).reset_index().assign(unit="Respublika")
    out = pd.concat([total, by_region], ignore_index=True)
    out["n"] = out["n"].astype(int)
    s = cfg.method["sample"]
    out["status"] = np.select([out.n >= s["publish_min"], out.n >= s["flag_min"]], ["ok", "thin"], "hidden")
    out["from"], out["to"] = earlier, later
    return out
