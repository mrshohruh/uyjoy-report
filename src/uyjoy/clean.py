"""Apply method v1 cleaning rules. Every rule logs how many rows it removed."""
from __future__ import annotations

import pandas as pd

from .config import Config


def clean(df: pd.DataFrame, cfg: Config) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (clean rows, log of rows removed per rule, family and quarter)."""
    if df.empty:
        return df, pd.DataFrame()
    m = cfg.method
    log = []

    def step(name: str, keep: pd.Series):
        nonlocal df
        removed = df[~keep]
        if len(removed):
            c = removed.groupby(["family", "quarter"]).size().rename("rows").reset_index()
            c["rule"] = name
            log.append(c)
        df = df[keep]

    lo_r, hi_r = m["scope"]["rooms"]
    lo_a, hi_a = m["scope"]["area_m2"]
    step("buildings under min floors", df.total_floors >= m["scope"]["min_total_floors"])
    step("rooms out of range", df.number_of_rooms.between(lo_r, hi_r))
    step("area out of range", df.total_area.between(lo_a, hi_a))
    step("floor above building height", df.floor <= df.total_floors)
    caps = df.family.map(m["price_caps_usd"])
    step("price above family cap", df.price <= caps)

    # One row per listing id per quarter, keeping the latest observation.
    df = df.sort_values(["sana", "id"])
    step("same id seen again in quarter", ~df.duplicated(["family", "quarter", "id"], keep="last"))
    step("repost under new id",
         ~df.duplicated(["family", "quarter", *m["repost_key"]], keep="last"))

    lo, hi = m["outlier_ratio"]
    med = df.groupby(["family", "quarter", "geo", "market"]).price_sqrm.transform("median")
    ratio = df.price_sqrm / med
    step("price per m2 outlier", ratio.between(lo, hi))

    log_df = pd.concat(log, ignore_index=True) if log else pd.DataFrame(columns=["family", "quarter", "rows", "rule"])
    return df.reset_index(drop=True), log_df
