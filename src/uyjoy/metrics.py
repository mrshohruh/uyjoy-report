"""Quarterly medians, changes, sample flags, rental yield and the room-mix-adjusted index."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import Config

SALE = ("prim", "sec")


def _status(n: pd.Series, cfg: Config) -> pd.Series:
    s = cfg.method["sample"]
    return pd.Series(
        np.select([n >= s["publish_min"], n >= s["flag_min"]], ["ok", "thin"], "hidden"), index=n.index
    )


def _shift(q: pd.Series, k: int) -> pd.Series:
    return (pd.PeriodIndex(q, freq="Q") - k).astype(str)


def medians(df: pd.DataFrame, cfg: Config, unit: str, extra: tuple[str, ...] = ()) -> pd.DataFrame:
    """Median price per m2 by quarter x unit x market (+ extra keys such as rooms).

    Markets: prim, sec, rent, and `sale` = prim and sec together (used for yield).
    Changes are computed in so'm, as in the published reports, and in USD.
    """
    if df.empty:
        return pd.DataFrame()
    keys = ["quarter", unit, *extra]
    t = df.groupby([*keys, "market"]).price_sqrm.agg(median_usd="median", n="size").reset_index()
    s = df[df.market.isin(SALE)]
    if not s.empty:
        s = s.groupby(keys).price_sqrm.agg(median_usd="median", n="size").reset_index().assign(market="sale")
        t = pd.concat([t, s], ignore_index=True)
    t = t.rename(columns={unit: "unit"})
    t["rate"] = t["quarter"].map(cfg.rates)
    t["median_uzs"] = t["median_usd"] * t["rate"]
    t["status"] = _status(t["n"], cfg)

    key = ["unit", "market", *extra]
    base = t[[*key, "quarter", "median_uzs", "median_usd", "status"]]
    for label, k in (("qoq", 1), ("yoy", 4)):
        prev = base.assign(quarter=_shift(base["quarter"], -k)).rename(
            columns={"median_uzs": "p_uzs", "median_usd": "p_usd", "status": "p_status"})
        t = t.merge(prev, on=[*key, "quarter"], how="left")
        t[f"{label}_pct"] = (t["median_uzs"] / t["p_uzs"] - 1) * 100
        t[f"{label}_usd_pct"] = (t["median_usd"] / t["p_usd"] - 1) * 100
        t[f"{label}_prev_status"] = t["p_status"]
        t = t.drop(columns=["p_uzs", "p_usd", "p_status"])
    return t.sort_values([*key, "quarter"]).reset_index(drop=True)


def rental_yield(tab: pd.DataFrame) -> pd.DataFrame:
    """Annual gross yield = median rent per m2 x 12 / median sale price per m2 (both markets)."""
    if tab.empty:
        return pd.DataFrame()
    rent = tab[tab.market == "rent"].set_index(["quarter", "unit"])
    sale = tab[tab.market == "sale"].set_index(["quarter", "unit"])
    j = rent[["median_usd", "n", "status"]].join(
        sale[["median_usd", "n", "status"]], lsuffix="_rent", rsuffix="_sale", how="inner")
    j["yield_pct"] = j["median_usd_rent"] * 12 / j["median_usd_sale"] * 100
    order = {"ok": 0, "thin": 1, "hidden": 2}
    j["status"] = np.where(
        j.status_rent.map(order) >= j.status_sale.map(order), j.status_rent, j.status_sale)
    return j.reset_index()


def mix_adjusted_index(df: pd.DataFrame, cfg: Config, unit: str, until: str | None = None) -> pd.DataFrame:
    """Chain index per unit from resale listings, adjusting for the room mix.

    Each quarter-to-quarter link is a geometric mean of stratum (1, 2, 3, 4+ rooms)
    median ratios, weighted by the stratum's average share across the two quarters.
    Strata with fewer than `min_per_stratum` listings in either quarter are skipped;
    with no usable stratum the link falls back to the plain median ratio.
    """
    ic = cfg.method["index"]
    d = df[df.market == ic["market"]]
    if d.empty:
        return pd.DataFrame()
    cell = d.groupby([unit, "quarter", "rooms"]).price_sqrm.agg(med="median", n="size").reset_index()
    total = d.groupby([unit, "quarter"]).price_sqrm.agg(med="median", n="size").reset_index()
    quarters = sorted(d["quarter"].unique(), key=lambda q: pd.Period(q, "Q"))
    if until is not None:
        quarters = [q for q in quarters if pd.Period(q, "Q") <= pd.Period(until, "Q")]
    base = ic["base_period"] if ic["base_period"] in quarters else quarters[0]
    run = [q for q in quarters if pd.Period(q, "Q") >= pd.Period(base, "Q")]
    # The chain needs consecutive quarters; it stops at the first missing one.
    for i, (a, b) in enumerate(zip(run, run[1:])):
        if (pd.Period(b, "Q") - pd.Period(a, "Q")).n != 1:
            run = run[: i + 1]
            break
    rows = []
    for u, cu in cell.groupby(unit):
        if base not in set(cu.quarter):
            rows += [{"unit": u, "quarter": q, "index": np.nan, "link": "no base"} for q in run]
            continue
        level, prev = 100.0, base
        rows.append({"unit": u, "quarter": base, "index": 100.0, "link": "base"})
        for q in run[1:]:
            if prev is None:
                rows.append({"unit": u, "quarter": q, "index": np.nan, "link": "broken"})
                continue
            a = cu[cu.quarter == prev].set_index("rooms")
            b = cu[cu.quarter == q].set_index("rooms")
            ok = [k for k in ic["strata"] if k in a.index and k in b.index
                  and a.at[k, "n"] >= ic["min_per_stratum"] and b.at[k, "n"] >= ic["min_per_stratum"]]
            if ok:
                sa, sb = a.loc[ok, "n"] / a.loc[ok, "n"].sum(), b.loc[ok, "n"] / b.loc[ok, "n"].sum()
                w = (sa + sb) / 2
                link = float(np.exp((w * np.log(b.loc[ok, "med"] / a.loc[ok, "med"])).sum()))
                how = f"mix:{','.join(ok)}"
            else:
                ta = total[(total[unit] == u) & (total.quarter == prev)]
                tb = total[(total[unit] == u) & (total.quarter == q)]
                if ta.empty or tb.empty:
                    rows.append({"unit": u, "quarter": q, "index": np.nan, "link": "missing"})
                    prev = None
                    continue
                link, how = float(tb.med.iloc[0] / ta.med.iloc[0]), "plain"
            level *= link
            rows.append({"unit": u, "quarter": q, "index": level, "link": how})
            prev = q
    out = pd.DataFrame(rows)
    out["base_period"] = base
    out["provisional_base"] = base != ic["base_period"]
    return out


def national_index(idx: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """Population-weighted mean of regional indices; reports which regions were missing."""
    if idx.empty:
        return pd.DataFrame()
    w = cfg.population
    rows = []
    for q, g in idx.dropna(subset=["index"]).groupby("quarter"):
        g = g[g.unit.isin(w.index)]
        ww = w.reindex(g.unit).values
        rows.append({
            "quarter": q, "index": float(np.average(g["index"], weights=ww)),
            "regions": len(g), "missing": sorted(set(w.index) - set(g.unit)),
        })
    return pd.DataFrame(rows).sort_values("quarter", key=lambda s: s.map(lambda x: pd.Period(x, "Q")))
