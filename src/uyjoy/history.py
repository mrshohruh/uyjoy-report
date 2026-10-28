"""Extra blocks for the facts pack: history series, the national (listing-weighted) change and its
split into price and composition, the new-build premium, yield and index history, rooms and the
macro context.

Everything here is derived from the same tables as the core facts (see pipeline.compute), so a run
rebuilt from tables.xlsx gives the same numbers. Values are rounded as the report prints them.
"""
from __future__ import annotations

import math

import pandas as pd

from . import macro
from .config import Config

UNITS = {"prim": (1e6, 2), "sec": (1e6, 2), "sale": (1e6, 2), "rent": (1e3, 1)}
SECTION = {"prim": "birlamchi", "sec": "ikkilamchi", "rent": "ijara"}
RANK = {"ok": 0, "thin": 1, "hidden": 2}


def _r(x, nd=1):
    if x is None:
        return None
    try:
        if math.isnan(float(x)):
            return None
    except (TypeError, ValueError):
        return None
    return round(float(x), nd)


def quarters_back(period: str, n: int) -> list[str]:
    p = pd.Period(period, "Q")
    return [str(p - k) for k in range(n - 1, -1, -1)]


def _worse(*st):
    return max(st, key=lambda s: RANK.get(s, 2))


def series_block(tab: pd.DataFrame, period: str, order: list[str], n_q: int = 12) -> dict:
    """Per unit and market: value, quarterly change and status for the last n_q quarters."""
    qs = quarters_back(period, n_q)
    out = {"quarters": qs}
    if tab is None or tab.empty:
        return out
    t = tab[tab.quarter.isin(qs)]
    for m, sec in SECTION.items():
        div, nd = UNITS[m]
        rows = []
        for name in order:
            u = t[(t.unit == name) & (t.market == m)].set_index("quarter")
            vals, chg, st = [], [], []
            for q in qs:
                if q in u.index:
                    r = u.loc[q]
                    hidden = r.status == "hidden"
                    vals.append(None if hidden else _r(r.median_uzs / div, nd))
                    ps = r.get("qoq_prev_status")
                    chg.append(_r(r.qoq_pct) if not hidden and isinstance(ps, str) and ps != "hidden" else None)
                    st.append(r.status)
                else:
                    vals.append(None)
                    chg.append(None)
                    st.append("missing")
            rows.append({"name": name, "values": vals, "qoq_pct": chg, "status": st})
        out[sec] = rows
    return out


def national_block(facts: dict) -> dict:
    """Listing-weighted average change across regions, next to the simple average and the same-listings change.

    Weights are the number of listings in the current quarter, over regions that are not hidden. The gap
    between the weighted median change and the same-listings change is a rough measure of how much of the
    move comes from which listings are on the site (composition), not from listed prices changing.
    """
    lfl = (facts.get("solishtirma") or {}).get("qoq", {})
    lfl_y = (facts.get("solishtirma") or {}).get("yoy", {})
    out = {"id": "respublika", "about": "eʼlonlar soniga koʻra tortilgan oʻrtacha oʻzgarish; tarkib taʼsiri = "
                                        "tortilgan oʻzgarish − bir xil eʼlonlar oʻzgarishi (foiz punkt)"}
    for sec in ("birlamchi", "ikkilamchi", "ijara"):
        blk = facts.get(sec)
        if not blk:
            continue
        rows = [r for r in blk["rows"] if r.get("status") in ("ok", "thin") and r.get("qoq_pct") is not None]
        n = sum(r["n"] for r in rows)
        w_q = sum(r["n"] * r["qoq_pct"] for r in rows) / n if n else None
        rows_y = [r for r in blk["rows"] if r.get("status") in ("ok", "thin") and r.get("yoy_pct") is not None]
        ny = sum(r["n"] for r in rows_y)
        w_y = sum(r["n"] * r["yoy_pct"] for r in rows_y) / ny if ny else None
        nat = next((r for r in lfl.get(sec, []) if r["name"] == "Respublika"), None)
        nat_y = next((r for r in lfl_y.get(sec, []) if r["name"] == "Respublika"), None)
        l_q = nat["mean_pct"] if nat else None
        out[sec] = {
            "id": f"respublika.{sec}",
            "simple_qoq_pct": blk.get("avg_qoq_pct"),
            "weighted_qoq_pct": _r(w_q),
            "weighted_yoy_pct": _r(w_y),
            "lfl_qoq_pct": l_q,
            "lfl_yoy_pct": nat_y["mean_pct"] if nat_y else None,
            "composition_pp": _r(w_q - l_q) if w_q is not None and l_q is not None else None,
            "n": n,
            "tashkent_share_pct": _r(100 * next((r["n"] for r in rows if r["name"] == "Toshkent shahri"), 0) / n, 0)
            if n else None,
        }
    return out


def premium_block(tab: pd.DataFrame, period: str, order: list[str], prefix: str) -> dict:
    """New-build premium: primary over secondary median per m², in %, now and a year ago."""
    if tab is None or tab.empty:
        return {}
    yq = str(pd.Period(period, "Q") - 4)
    rows = []
    for name in order:
        def get(q, m):
            r = tab[(tab.unit == name) & (tab.market == m) & (tab.quarter == q)]
            return r.iloc[0] if not r.empty else None
        p, s, py, sy = get(period, "prim"), get(period, "sec"), get(yq, "prim"), get(yq, "sec")
        if p is None or s is None:
            continue
        st = _worse(p.status, s.status)
        val = None if st == "hidden" else _r((p.median_usd / s.median_usd - 1) * 100)
        prev = None
        if py is not None and sy is not None and _worse(py.status, sy.status) != "hidden":
            prev = _r((py.median_usd / sy.median_usd - 1) * 100)
        rows.append({"id": f"{prefix}.premium.{name}", "name": name, "value": val, "prev_year": prev,
                     "change_pp": _r(val - prev) if val is not None and prev is not None else None, "status": st})
    ok = [r for r in rows if r["status"] == "ok" and r["value"] is not None]
    return {"id": f"{prefix}.premium", "unit": "%", "about": "birlamchi bozor narxining ikkilamchidan "
            "ustamasi: birlamchi median ÷ ikkilamchi median − 1", "rows": rows,
            "highest": [r["name"] for r in sorted(ok, key=lambda r: -r["value"])[:3]],
            "lowest": [r["name"] for r in sorted(ok, key=lambda r: r["value"])[:3]],
            "negative": [r["name"] for r in ok if r["value"] < 0]}


def yield_history(y: pd.DataFrame, period: str, order: list[str], n_q: int = 12) -> dict:
    qs = quarters_back(period, n_q)
    out = {"quarters": qs, "rows": []}
    if y is None or y.empty:
        return out
    yq = str(pd.Period(period, "Q") - 4)
    for name in order:
        u = y[y.unit == name].set_index("quarter")
        vals = [(_r(u.loc[q].yield_pct) if q in u.index and u.loc[q].status != "hidden" else None) for q in qs]
        cur = vals[-1]
        prev = _r(u.loc[yq].yield_pct) if yq in u.index and u.loc[yq].status != "hidden" else None
        out["rows"].append({"name": name, "values": vals,
                            "change_pp_yoy": _r(cur - prev) if cur is not None and prev is not None else None})
    return out


def district_yield(y: pd.DataFrame, period: str, order: list[str]) -> dict:
    rows = []
    if y is not None and not y.empty:
        cur = y[y.quarter == period].set_index("unit")
        for name in order:
            if name in cur.index:
                r = cur.loc[name]
                rows.append({"id": f"tuman.yield.{name}", "name": name, "status": r.status,
                             "value": None if r.status == "hidden" else _r(r.yield_pct)})
    ok = [r for r in rows if r["status"] == "ok" and r["value"] is not None]
    return {"unit": "%", "rows": rows,
            "highest": [r["name"] for r in sorted(ok, key=lambda r: -r["value"])[:3]],
            "lowest": [r["name"] for r in sorted(ok, key=lambda r: r["value"])[:3]]}


def index_history(reg: pd.DataFrame, nat: pd.DataFrame, period: str, order: list[str]) -> dict:
    if reg is None or reg.empty:
        return {}
    p = pd.Period(period, "Q")
    qs = sorted({q for q in reg.quarter if pd.Period(q, "Q") <= p}, key=lambda q: pd.Period(q, "Q"))
    yq = str(p - 4)
    out = {"quarters": qs, "rows": []}
    for name in order:
        u = reg[reg.unit == name].set_index("quarter")
        vals = [(_r(u.loc[q]["index"]) if q in u.index and not pd.isna(u.loc[q]["index"]) else None) for q in qs]
        cur, prev = vals[-1] if vals else None, (_r(u.loc[yq]["index"]) if yq in u.index else None)
        out["rows"].append({"id": f"indeks.hudud.{name}", "name": name, "values": vals, "value": cur,
                            "yoy_pct": _r((cur / prev - 1) * 100) if cur and prev else None})
    return out


def rooms_block(rooms: pd.DataFrame, period: str, order: list[str]) -> dict:
    """Tashkent districts × room count, current quarter, every market."""
    if rooms is None or rooms.empty:
        return {}
    r = rooms[rooms.quarter == period]
    strata = ["1", "2", "3", "4+"]
    have = [s for s in strata if s in set(r.rooms.astype(str))]
    out = {"rooms": have}
    for m, sec in SECTION.items():
        div, nd = UNITS[m]
        rows = []
        for name in order:
            cells = []
            for s in have:
                c = r[(r.unit == name) & (r.market == m) & (r.rooms.astype(str) == s)]
                if c.empty:
                    cells.append({"value": None, "status": "missing", "n": 0})
                else:
                    c = c.iloc[0]
                    cells.append({"value": None if c.status == "hidden" else _r(c.median_uzs / div, nd),
                                  "status": c.status, "n": int(c.n)})
            rows.append({"name": name, "cells": cells})
        out[sec] = rows
    return out


def extras(facts: dict, tables: dict, period: str, scope: str, cfg: Config) -> dict:
    g = cfg.geo
    if scope == "respublika":
        regions = tables.get("regions")
        facts["tarix"] = series_block(regions, period, g["region_order"])
        facts["respublika"] = national_block(facts)
        facts["premium"] = premium_block(regions, period, g["region_order"], "hudud")
        facts["rentabellik_tarix"] = yield_history(tables.get("yield_hudud"), period, g["region_order"])
        if tables.get("districts") is not None and not tables["districts"].empty:
            facts["tarix_tumanlar"] = series_block(tables["districts"], period, g["district_order"], 8)
            facts["premium_tumanlar"] = premium_block(tables["districts"], period, g["district_order"], "tuman")
            facts["rentabellik_tumanlar"] = district_yield(tables.get("yield_tuman"), period, g["district_order"])
        facts["indeks_hududlar"] = index_history(tables.get("index_regional"), tables.get("index"), period,
                                                 g["region_order"])
        facts["xonalar_toshkent"] = rooms_block(tables.get("rooms"), period, g["district_order"])
    m = macro.block(period)
    if m:
        facts["makro"] = m
    return facts
