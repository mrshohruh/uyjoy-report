"""Run the agent's method v1 for every month, quarter and year, and write dashboard_data.json.

Uses the agent's own code (uyjoy.ingest, uyjoy.clean, uyjoy.metrics, uyjoy.breaks) unchanged.
The only generalisation is the period: each listing is labelled with its month, quarter or
year, and that label takes the place of the quarter everywhere the method groups by quarter
(de-duplication, outlier trimming, medians, sample flags, like-for-like). For quarters this is
exactly what the agent does, so 2026-Q3 reproduces the published report.

Rounding, sample rules and when a change is left blank follow uyjoy/facts.py.
Prices are converted to so'm at the CBU rate in force on the period's last day.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# Put this folder inside uyjoy-report (as uyjoy-report/dashboard), or set UYJOY_AGENT to the agent folder.
import os  # noqa: E402
AGENT = Path(os.environ.get("UYJOY_AGENT", Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(AGENT / "src"))
from uyjoy import breaks, ingest, metrics  # noqa: E402
from uyjoy import clean as clean_mod  # noqa: E402
from uyjoy.config import load  # noqa: E402

DATA = Path(sys.argv[1]) if len(sys.argv) > 1 else AGENT / "data" / "parquet"
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).parent / "dashboard_data.json"
FIRST, LAST = "2024-01", "2026-09"

cfg = load()
month_rates = pd.read_csv(Path(__file__).parent / "usd_uzs_month_end.csv", dtype={"period": str}).set_index("period")["rate"]
G = cfg.geo
S = cfg.method["sample"]
UNITS = {"prim": (1e6, 2), "sec": (1e6, 2), "sale": (1e6, 2), "rent": (1e3, 1)}


def r_(x, nd=1):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(float(x), nd)


def status(n):
    return np.select([n >= S["publish_min"], n >= S["flag_min"]], ["ok", "thin"], "hidden")


# ---------------------------------------------------------------- load once
NEED = ["id", "sana", "family", "quarter", "month", "region", "district", "market", "price", "price_sqrm",
        "total_area", "number_of_rooms", "floor", "total_floors", "geo", "location_uz", "rooms"]
frames = []
for fam in ingest.FAMILIES:
    d = ingest.load_family(DATA, fam, cfg)[NEED]
    for c in ("family", "quarter", "month", "region", "district", "market", "geo", "location_uz", "rooms"):
        d[c] = d[c].astype("category")
    frames.append(d)
    del d
raw = pd.concat(frames, ignore_index=True)
for c in ("family", "month", "region", "district", "market", "geo", "location_uz", "rooms"):
    raw[c] = raw[c].astype(str).astype("category")
raw["district"] = raw["district"].astype(str).replace("None", None)
del frames
raw = raw[raw.month.astype(str) <= LAST]
months_by_family = raw.groupby("family").month.apply(lambda s: set(s.unique())).to_dict()
print("rows loaded", len(raw), {f: (min(m), max(m), len(m)) for f, m in months_by_family.items()})


# ---------------------------------------------------------------- period definitions
def period_defs():
    """label -> (kind, months, rate, prev_label, yoy_label)."""
    defs = {}
    for p in pd.period_range("2023-01", LAST, freq="M"):
        lab = str(p)
        defs[("M", lab)] = dict(months=[lab], rate=float(month_rates[lab]), prev=str(p - 1), yoy=str(p - 12))
    for q in pd.period_range("2023Q1", pd.Period(LAST, "M").asfreq("Q"), freq="Q"):
        ms = [str(m) for m in pd.period_range(q.asfreq("M", "start"), q.asfreq("M", "end"), freq="M")]
        defs[("Q", str(q))] = dict(months=ms, rate=float(cfg.rates[str(q)]), prev=str(q - 1), yoy=str(q - 4))
    last = pd.Period(LAST, "M")
    for y in range(2023, last.year + 1):
        end = min(pd.Period(f"{y}-12", "M"), last)
        ms = [str(m) for m in pd.period_range(f"{y}-01", end, freq="M")]
        lab = str(y) if end.month == 12 else f"{y}:1-{end.month}"
        cmp_ = str(y - 1) if end.month == 12 else f"{y - 1}:1-{end.month}"
        defs[("Y", lab)] = dict(months=ms, rate=float(month_rates[str(end)]), prev=cmp_, yoy=cmp_)
        if end.month != 12:  # the same months one year earlier, for the year-to-date comparison
            ms0 = [str(m - 12) for m in pd.period_range(f"{y}-01", end, freq="M")]
            defs[("Y", cmp_)] = dict(months=ms0, rate=float(month_rates[str(end - 12)]), prev=None, yoy=None)
    return defs


DEFS = period_defs()


def complete(fam, months):
    return set(months) <= months_by_family.get(fam, set())


# ---------------------------------------------------------------- per period kind
def medians_kind(df, kind, unit):
    """metrics.medians with the period label in place of the quarter (same aggregation)."""
    keys = ["quarter", unit]
    t = df.groupby([*keys, "market"]).price_sqrm.agg(median_usd="median", n="size").reset_index()
    s = df[df.market.isin(metrics.SALE)]
    s = s.groupby(keys).price_sqrm.agg(median_usd="median", n="size").reset_index().assign(market="sale")
    t = pd.concat([t, s], ignore_index=True).rename(columns={unit: "unit"})
    t["rate"] = t["quarter"].map(lambda q: DEFS[(kind, q)]["rate"])
    t["median_uzs"] = t["median_usd"] * t["rate"]
    t["status"] = status(t["n"])
    return t


def run_kind(kind):
    # The method groups every cleaning step by period, so cleaning each period on its own
    # gives the same rows as cleaning them all together, with far less memory.
    rows = []
    for (k, lab), d in DEFS.items():
        if k != kind:
            continue
        x = raw[raw.month.isin(d["months"])].copy()
        if x.empty:
            continue
        for c in ("family", "region", "market", "geo", "location_uz", "rooms", "month"):
            x[c] = x[c].astype(str)
        x["quarter"] = lab
        x, _log = clean_mod.clean(x, cfg)
        for c in ("family", "region", "market", "geo", "location_uz", "rooms", "month", "quarter"):
            x[c] = x[c].astype("category")
        rows.append(x)
    df = pd.concat(rows, ignore_index=True)
    for c in ("family", "region", "market", "geo", "location_uz", "rooms", "month", "quarter"):
        df[c] = df[c].astype(str)
    reg = medians_kind(df, kind, "region")
    tsh = df[df.family.str.startswith("tashkent")]
    dist = medians_kind(tsh, kind, "district")
    return df, reg, dist


def fam_of(unit_kind, market, unit):
    if unit_kind == "district" or unit == "Toshkent shahri":
        return "tashkent_rent" if market == "rent" else "tashkent_sale"
    return "regions_rent" if market == "rent" else "regions_sale"


def lookup(tab):
    return {(r.quarter, r.unit, r.market): r for r in tab.itertuples()}


def cell(L, kind, lab, unit, market, unit_kind):
    """One table cell, rounded and blanked exactly as facts.market_block does."""
    d = DEFS[(kind, lab)]
    fam = fam_of(unit_kind, market, unit)
    div, nd = UNITS[market]
    r = L.get((lab, unit, market))
    if r is None or not complete(fam, d["months"]):
        return None
    hidden = r.status == "hidden"

    def chg(other):
        if other is None or not complete(fam, DEFS[(kind, other)]["months"]):
            return None, None, None
        p = L.get((other, unit, market))
        if p is None:
            return None, None, None
        return (r.median_uzs / p.median_uzs - 1) * 100, p.status, (r.median_usd / p.median_usd - 1) * 100

    q, qs, qu = chg(d["prev"])
    y, _, yu = chg(d["yoy"])
    return {
        "v": None if hidden else r_(r.median_uzs / div, nd),
        "usd": None if hidden else r_(r.median_usd, 0 if market != "rent" else 2),
        "dq": None if hidden or q is None or qs == "hidden" else r_(q),
        "dy": None if hidden or y is None else r_(y),
        "dq_usd": None if hidden or qu is None or qs == "hidden" else r_(qu),
        "dy_usd": None if hidden or yu is None else r_(yu),
        "n": int(r.n), "s": r.status,
    }


def lfl_rows(df, kind, earlier, later):
    if earlier is None:
        return {}
    t = breaks.like_for_like(df, cfg, earlier, later)
    if t.empty:
        return {}
    fx = DEFS[(kind, later)]["rate"] / DEFS[(kind, earlier)]["rate"]
    out = {}
    for x in t.itertuples():
        fam = fam_of("region", x.market, x.unit) if x.unit != "Respublika" else None
        if fam and not (complete(fam, DEFS[(kind, earlier)]["months"]) and complete(fam, DEFS[(kind, later)]["months"])):
            continue
        out[(x.unit, x.market)] = {
            "uzs": None if x.status == "hidden" else r_(((1 + x.mean_pct / 100) * fx - 1) * 100),
            "usd": None if x.status == "hidden" else r_(x.mean_pct),
            "n": int(x.n), "s": x.status,
        }
    return out


MK = {"prim": "primary", "sec": "secondary", "rent": "rent"}
out = {"method": cfg.method["version"], "first": FIRST, "last": LAST, "periods": {}, "data": {}, "index": {}}

for kind in ("M", "Q", "Y"):
    df, reg, dist = run_kind(kind)
    LR, LD = lookup(reg), lookup(dist)
    labels = [lab for (k, lab) in DEFS if k == kind]
    if kind == "M":
        show = [l for l in labels if FIRST <= l <= LAST]
    elif kind == "Q":
        show = [l for l in labels if pd.Period(l, "Q") >= pd.Period(FIRST, "M").asfreq("Q")]
    else:
        show = [l for l in labels if not (":" in l and DEFS[("Y", l)]["prev"] is None) and l[:4] >= FIRST[:4]]
    out["periods"][kind] = show
    out["data"][kind] = {}
    for lab in show:
        d = DEFS[(kind, lab)]
        P = {"rate": d["rate"], "months": d["months"], "regions": {}, "districts": {}, "yield": {}, "same": {}, "summary": {}}
        lfl_q = lfl_rows(df, kind, d["prev"], lab) if kind != "Y" else lfl_rows(df, kind, d["yoy"], lab)
        for m, mname in MK.items():
            P["regions"][mname] = {u: cell(LR, kind, lab, u, m, "region") for u in G["region_order"]}
            P["districts"][mname] = {u: cell(LD, kind, lab, u, m, "district") for u in G["district_order"]}
            P["same"][mname] = {u: lfl_q.get((u, m)) for u in ["Respublika", *G["region_order"]]}
            ok = [c for c in P["regions"][mname].values() if c and c["s"] == "ok" and c["dq"] is not None]
            oky = [c for c in P["regions"][mname].values() if c and c["s"] == "ok" and c["dy"] is not None]
            P["summary"][mname] = {
                "avg_dq": r_(float(np.mean([c["dq"] for c in ok]))) if ok else None,
                "avg_dy": r_(float(np.mean([c["dy"] for c in oky]))) if oky else None,
                "rising": sum(c["dq"] > 0 for c in ok), "falling": sum(c["dq"] < 0 for c in ok),
                "listings": int(sum(c["n"] for c in P["regions"][mname].values() if c)),
            }
        # yield, exactly metrics.rental_yield on this period's table
        y = metrics.rental_yield(reg[reg.quarter == lab])
        for x in y.itertuples():
            fams = [fam_of("region", "rent", x.unit), fam_of("region", "prim", x.unit)]
            if all(complete(f, d["months"]) for f in fams):
                P["yield"][x.unit] = {"v": None if x.status == "hidden" else r_(x.yield_pct), "s": x.status}
        out["data"][kind][lab] = P
    print(kind, "periods", len(show), show[0], "…", show[-1])

# quarterly room-mix-adjusted index, exactly as the agent builds it
dfq, regq, _ = run_kind("Q")
idx = metrics.mix_adjusted_index(dfq, cfg, "region", until=str(pd.Period(LAST, "M").asfreq("Q")))
nat = metrics.national_index(idx, cfg)
out["index"] = {
    "base": str(idx["base_period"].iloc[0]),
    "national": [{"q": x.quarter, "v": r_(x.index), "regions": int(x.regions),
                  "dq": r_((x.index / nat.iloc[i - 1]["index"] - 1) * 100) if i >= 1 else None,
                  "dy": r_((x.index / nat.iloc[i - 4]["index"] - 1) * 100) if i >= 4 else None}
                 for i, x in enumerate(nat.itertuples())],
    "regional": {u: [{"q": x.quarter, "v": r_(x.index)} for x in g.itertuples()] for u, g in idx.groupby("unit")},
}
OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
print("wrote", OUT, OUT.stat().st_size, "bytes")
