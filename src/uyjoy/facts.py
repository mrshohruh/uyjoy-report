"""Turn the computed tables into the facts pack: the only numbers the writer may use.

Every value is rounded exactly as the report prints it, and carries an `id` path so
the text checker can trace each number in the Uzbek text back to this file.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from . import breaks
from .config import Config

UNITS = {"prim": ("mln soʻm/m²", 1e6, 2), "sec": ("mln soʻm/m²", 1e6, 2),
         "sale": ("mln soʻm/m²", 1e6, 2), "rent": ("ming soʻm/m²", 1e3, 1)}
SECTION = {"prim": "birlamchi", "sec": "ikkilamchi", "rent": "ijara"}


def _r(x, nd=1):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(float(x), nd)


def _prev_q(q: str, k: int = 1) -> str:
    return str(pd.Period(q, "Q") - k)


def _streak(series: pd.DataFrame, period: str) -> tuple[str | None, int]:
    """Consecutive quarters (ending at period) whose so'm change has the same sign."""
    s = series.set_index("quarter").sort_index(key=lambda i: i.map(lambda q: pd.Period(q, "Q")))
    if period not in s.index or pd.isna(s.at[period, "qoq_pct"]):
        return None, 0
    sign = np.sign(s.at[period, "qoq_pct"])
    n, q = 0, period
    while q in s.index and not pd.isna(s.at[q, "qoq_pct"]) and np.sign(s.at[q, "qoq_pct"]) == sign \
            and s.at[q, "status"] == "ok":
        n += 1
        q = _prev_q(q)
    return ("up" if sign > 0 else "down"), n


def market_block(tab: pd.DataFrame, period: str, market: str, order: list[str], prefix: str) -> dict:
    unit_label, div, nd = UNITS[market]
    t = tab[(tab.market == market)]
    cur = t[t.quarter == period].set_index("unit")
    prev = t[t.quarter == _prev_q(period)].set_index("unit")
    rows = []
    for name in order:
        if name not in cur.index:
            rows.append({"name": name, "status": "missing"})
            continue
        r = cur.loc[name]
        hidden = r.status == "hidden"
        pr = prev.loc[name] if name in prev.index else None
        prev_hidden = pr is None or pr.status == "hidden"
        row = {
            "id": f"{prefix}.{market}.{name}",
            "name": name,
            "value": None if hidden else _r(r.median_uzs / div, nd),
            "value_usd": None if hidden else _r(r.median_usd, 0 if market != "rent" else 2),
            "qoq_pct": None if hidden or prev_hidden else _r(r.qoq_pct),
            "yoy_pct": None if hidden else _r(r.yoy_pct),
            "qoq_usd_pct": None if hidden or prev_hidden else _r(r.qoq_usd_pct),
            "prev_value": None if prev_hidden else _r(pr.median_uzs / div, nd),
            "prev_qoq_pct": None if prev_hidden else _r(pr.qoq_pct),
            "n": int(r.n),
            "status": r.status,
        }
        d, k = _streak(t[t.unit == name], period)
        row["streak"] = {"direction": d, "quarters": k} if k >= 2 else None
        rows.append(row)

    ok = [r for r in rows if r.get("status") == "ok" and r.get("qoq_pct") is not None]
    up = sorted([r for r in ok if r["qoq_pct"] > 0], key=lambda r: -r["qoq_pct"])[:3]
    down = sorted([r for r in ok if r["qoq_pct"] < 0], key=lambda r: r["qoq_pct"])[:3]
    flips = [r["name"] for r in ok if r.get("prev_qoq_pct") is not None
             and np.sign(r["qoq_pct"]) != np.sign(r["prev_qoq_pct"]) and r["prev_qoq_pct"] != 0]
    priced = [r for r in rows if r.get("status") == "ok" and r.get("value") is not None]
    return {
        "unit": unit_label,
        "rows": rows,
        "top_up": [r["name"] for r in up],
        "top_down": [r["name"] for r in down],
        "direction_flips": flips,
        "streaks": [{"name": r["name"], **r["streak"]} for r in rows if r.get("streak")],
        "most_expensive": [r["name"] for r in sorted(priced, key=lambda r: -r["value"])[:3]],
        "cheapest": [r["name"] for r in sorted(priced, key=lambda r: r["value"])[:3]],
        "avg_qoq_pct": _r(float(np.mean([r["qoq_pct"] for r in ok]))) if ok else None,
        "avg_yoy_pct": _r(float(np.mean(yy))) if (yy := [r["yoy_pct"] for r in rows if r.get("status") == "ok"
                                                       and r.get("yoy_pct") is not None]) else None,
        "top_up_yoy": [r["name"] for r in sorted([r for r in rows if r.get("status") == "ok" and (r.get("yoy_pct") or 0) > 0],
                                                  key=lambda r: -r["yoy_pct"])[:3]],
        "top_down_yoy": [r["name"] for r in sorted([r for r in rows if r.get("status") == "ok" and (r.get("yoy_pct") or 0) < 0],
                                                    key=lambda r: r["yoy_pct"])[:3]],
        "rising_count": sum(1 for r in ok if r["qoq_pct"] > 0),
        "falling_count": sum(1 for r in ok if r["qoq_pct"] < 0),
        "thin": [r["name"] for r in rows if r.get("status") == "thin"],
        "hidden": [r["name"] for r in rows if r.get("status") == "hidden"],
    }


def yield_block(y: pd.DataFrame, period: str, order: list[str], prefix: str) -> dict:
    cur = y[y.quarter == period].set_index("unit") if not y.empty else pd.DataFrame()
    rows = []
    for name in order:
        if name not in cur.index:
            continue
        r = cur.loc[name]
        rows.append({"id": f"{prefix}.yield.{name}", "name": name,
                     "value": None if r.status == "hidden" else _r(r.yield_pct),
                     "status": r.status})
    ok = [r for r in rows if r["status"] == "ok" and r["value"] is not None]
    return {
        "unit": "%",
        "rows": rows,
        "highest": [r["name"] for r in sorted(ok, key=lambda r: -r["value"])[:4]],
        "lowest": [r["name"] for r in sorted(ok, key=lambda r: r["value"])[:3]],
        "spread_pp": _r(max(r["value"] for r in ok) - min(r["value"] for r in ok)) if ok else None,
    }


def build(period: str, scope: str, cfg: Config, tables: dict, inventory: pd.DataFrame,
          clean_log: pd.DataFrame) -> dict:
    g = cfg.geo
    rate = cfg.rate(period)
    prev_rate = cfg.rates.get(_prev_q(period))
    months = inventory[inventory.quarter == period].groupby("family").month.apply(sorted).to_dict()
    facts = {
        "report": {
            "period": period,
            "scope": scope,
            "method": cfg.method["version"],
            "usd_uzs_end": rate,
            "usd_uzs_prev_end": None if prev_rate is None else float(prev_rate),
            "som_vs_usd_pct": None if prev_rate is None else _r((prev_rate / rate - 1) * 100),
            "months_present": months,
            "partial_families": [f for f, m in months.items() if len(m) < 3],
            "series_break": breaks.flags(cfg, period),
        },
    }
    if scope == "respublika":
        tab, order, prefix = tables["regions"], g["region_order"], "hudud"
    else:
        tab, order, prefix = tables["districts"], g["district_order"], "tuman"
        city = tables["regions"]
        facts["city_total"] = {m: market_block(city[city.unit == "Toshkent shahri"], period, m,
                                               ["Toshkent shahri"], "shahar")["rows"][0]
                               for m in ("prim", "sec", "rent")}
    for m in ("prim", "sec", "rent"):
        facts[SECTION[m]] = market_block(tab, period, m, order, prefix)
    facts["ijara_rentabelligi"] = yield_block(tables["yield_" + prefix], period, order, prefix)

    if scope == "respublika" and "districts" in tables and not tables["districts"].empty:
        facts["toshkent_tumanlari"] = {SECTION[m]: market_block(tables["districts"], period, m,
                                                                g["district_order"], "tuman")
                                       for m in ("prim", "sec", "rent")}
    if scope == "toshkent" and "rooms" in tables and not tables["rooms"].empty:
        r = tables["rooms"]
        r = r[(r.quarter == period) & (r.market.isin(["prim", "sec", "rent"]))]
        facts["xonalar_kesimida"] = [
            {"id": f"xona.{x.market}.{x.unit}.{x.rooms}", "district": x.unit, "market": x.market,
             "rooms": x.rooms, "n": int(x.n), "status": x.status,
             "value": None if x.status == "hidden" else _r(x.median_uzs / UNITS[x.market][1], UNITS[x.market][2]),
             "qoq_pct": None if x.status == "hidden" else _r(x.qoq_pct)}
            for x in r.itertuples()]

    if "index" in tables and not tables["index"].empty:
        ni = tables["index"]
        ser = {x.quarter: x for x in ni.itertuples() if pd.Period(x.quarter, "Q") <= pd.Period(period, "Q")}
        cur = ser.get(period)

        def chg(k):
            p = ser.get(_prev_q(period, k))
            return _r((cur.index / p.index - 1) * 100) if cur is not None and p is not None else None

        reg = tables["index_regional"]
        rq = reg[reg.quarter == period].dropna(subset=["index"]).sort_values("index", ascending=False)
        facts["uy_joy_indeksi"] = {
            "id": "indeks",
            "base": reg["base_period"].iloc[0],
            "currency": "USD",
            "value": _r(cur.index) if cur is not None else None,
            "qoq_pct": chg(1),
            "yoy_pct": chg(4),
            "since_base_pct": _r(cur.index - 100) if cur is not None else None,
            "regions_used": int(cur.regions) if cur is not None else 0,
            "regions_missing": list(cur.missing) if cur is not None else [],
            "highest_regions": [{"name": u, "value": _r(v)} for u, v in zip(rq.unit[:3], rq["index"][:3])],
            "lowest_regions": [{"name": u, "value": _r(v)} for u, v in zip(rq.unit[-3:][::-1], rq["index"][-3:][::-1])],
            "series": [{"quarter": q, "value": _r(x.index)} for q, x in ser.items()],
        }

    facts["solishtirma"] = lfl_block(tables, scope, g, cfg)

    log = clean_log[clean_log.quarter == period] if not clean_log.empty else clean_log
    facts["data_quality"] = {
        "removed_by_rule": log.groupby(["family", "rule"]).rows.sum().reset_index().to_dict("records")
        if not log.empty else [],
    }
    return facts


def lfl_block(tables: dict, scope: str, g: dict, cfg: Config) -> dict:
    """Like-for-like changes (same listing ids in both quarters), shown when a series break is crossed."""
    names = {"prim": "birlamchi", "sec": "ikkilamchi", "sale": "sotuv", "rent": "ijara"}
    order = ["Respublika", *g["region_order"]] if scope == "respublika" else ["Toshkent shahri"]
    out = {"id": "lfl", "about": "bir xil eʼlonlarning ikki davr orasidagi oʻrtacha narx oʻzgarishi; "
                                 "mean_pct soʻmda (chorak oxiri kursi), mean_usd_pct dollarda"}
    for label in ("qoq", "yoy"):
        t = tables.get(f"lfl_{label}")
        if t is None or t.empty:
            continue
        blk = {"from": t["from"].iloc[0], "to": t["to"].iloc[0]}
        fx = cfg.rate(blk["to"]) / cfg.rate(blk["from"])   # tables convert at quarter-end rates; do the same
        for m, nm in names.items():
            rows = []
            for unit in order:
                r = t[(t.unit == unit) & (t.market == m)]
                if r.empty:
                    continue
                r = r.iloc[0]
                rows.append({"id": f"lfl.{label}.{m}.{unit}", "name": unit, "n": int(r.n), "status": r.status,
                             "mean_pct": None if r.status == "hidden" else _r(((1 + r.mean_pct / 100) * fx - 1) * 100),
                             "mean_usd_pct": None if r.status == "hidden" else _r(r.mean_pct),
                             "changed_share_pct": None if r.status == "hidden" else _r(r.changed_share * 100, 0)})
            blk[nm] = rows
        out[label] = blk
    return out
