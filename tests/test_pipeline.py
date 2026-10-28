import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from uyjoy import clean, config, facts, ingest, metrics  # noqa: E402

CFG = config.load()


def listing(i, quarter="2025Q1", state="Buxoro Viloyati", market="Вторичный рынок", price=50000.0,
            area=50.0, rooms=2, floor=3, total_floors=5, city="Buxoro shahri", district=None, sana="2025-01-15"):
    return {"id": i, "url": f"u{i}", "sana": pd.Timestamp(sana), "yil": 2025, "oy": 1, "created_time": None,
            "top_ad": False, "state": state, "location_uz": city, "district": district,
            "type_of_market": market, "price": price, "currency": "UYE", "total_area": area,
            "price_sqrm": price / area, "number_of_rooms": rooms, "floor": floor, "total_floors": total_floors,
            "month": "2025-01", "quarter": quarter}


def frame(rows, family="regions_sale"):
    return ingest.standardise(pd.DataFrame(rows), family, CFG)


def test_detect_family_and_month(tmp_path):
    for fam, state, mkt in [("regions_sale", "Buxoro Viloyati", "Новостройки"),
                            ("regions_rent", "Buxoro Viloyati", None),
                            ("tashkent_sale", "Toshkent shahri", "Новостройки"),
                            ("tashkent_rent", "Toshkent shahri", None)]:
        p = tmp_path / f"{fam}.parquet"
        pd.DataFrame({"state": [state], "type_of_market": pd.Series([mkt], dtype="string"),
                      "yil": [2026], "oy": [9]}).to_parquet(p)
        assert ingest.detect_family(p) == fam
        assert ingest.detect_month(p) == "2026-09"


def test_clean_keeps_one_row_per_id_and_drops_reposts():
    rows = [listing(1, sana="2025-01-05", price=50000), listing(1, sana="2025-02-05", price=52000),
            listing(2, price=60000), listing(3, price=60000)]          # 3 is a repost of 2
    out, log = clean.clean(frame(rows), CFG)
    assert sorted(out.id) == [1, 3] or sorted(out.id) == [1, 2]
    assert out.loc[out.id == 1, "price"].item() == 52000              # latest observation kept
    assert set(log.rule) == {"same id seen again in quarter", "repost under new id"}


def test_clean_scope_and_caps():
    rows = [listing(1, area=150), listing(2, rooms=6), listing(3, total_floors=3),
            listing(4, price=200000, area=100), listing(5)]
    out, _ = clean.clean(frame(rows), CFG)
    assert list(out.id) == [5]


def test_status_thresholds_and_changes():
    rows = [listing(i, price=50000) for i in range(30)]                                   # Q1: n=30, 1000 $/m2
    rows += [listing(100 + i, quarter="2025Q2", price=55000, floor=1 + i % 4, area=50 + i % 7 * 0.1)
             for i in range(12)]                                                             # Q2: n=12
    df = frame(rows)
    df["price_sqrm"] = df.price / df.total_area
    t = metrics.medians(df, CFG, "region")
    sec = t[t.market == "sec"].set_index("quarter")
    assert sec.at["2025Q1", "status"] == "ok" and sec.at["2025Q2", "status"] == "thin"
    expected = (sec.at["2025Q2", "median_usd"] * CFG.rate("2025Q2")) / (1000 * CFG.rate("2025Q1")) - 1
    assert sec.at["2025Q2", "qoq_pct"] == pytest.approx(expected * 100)


def test_yield_uses_both_sale_markets():
    sale = frame([listing(i, market="Новостройки", price=60000) for i in range(30)]
                 + [listing(100 + i, price=40000) for i in range(30)])
    rent = frame([listing(200 + i, market=None, price=500) for i in range(30)], family="regions_rent")
    t = metrics.medians(pd.concat([sale, rent]), CFG, "region")
    y = metrics.rental_yield(t)
    # new builds 1200 $/m2, resale 800 $/m2 -> combined median 1000; rent 10 $/m2 a month
    assert y.yield_pct.item() == pytest.approx(10 * 12 / 1000 * 100)   # 12%, not 10% (new builds only)


def test_index_ignores_pure_mix_shift():
    # Prices per m2 never change, but Q2 has many more 1-room flats (dearer per m2).
    q1 = [listing(i, rooms=1, price=60000) for i in range(10)] + [listing(20 + i, rooms=3, price=40000) for i in range(30)]
    q2 = [listing(100 + i, quarter="2025Q2", rooms=1, price=60000) for i in range(30)] + \
         [listing(200 + i, quarter="2025Q2", rooms=3, price=40000) for i in range(10)]
    df = frame(q1 + q2)
    plain = df[df.quarter == "2025Q2"].price_sqrm.median() / df[df.quarter == "2025Q1"].price_sqrm.median()
    assert plain > 1.2                                   # a plain median would report +50%
    idx = metrics.mix_adjusted_index(df, CFG, "region")
    assert idx.set_index("quarter").at["2025Q2", "index"] == pytest.approx(100.0)


def test_rankings_ignore_thin_cells():
    tab = pd.DataFrame([
        {"quarter": q, "unit": u, "market": "sec", "median_usd": v, "median_uzs": v * 12000, "n": n,
         "status": s, "qoq_pct": c, "yoy_pct": np.nan, "qoq_usd_pct": c}
        for q, u, v, n, s, c in [
            ("2025Q1", "A", 900, 100, "ok", np.nan), ("2025Q2", "A", 1000, 100, "ok", 11.1),
            ("2025Q1", "B", 900, 15, "thin", np.nan), ("2025Q2", "B", 1500, 15, "thin", 66.7),
        ]])
    b = facts.market_block(tab, "2025Q2", "sec", ["A", "B"], "hudud")
    assert b["top_up"] == ["A"] and b["thin"] == ["B"]
    assert next(r for r in b["rows"] if r["name"] == "A")["value"] == 12.0
