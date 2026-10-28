import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from uyjoy import breaks, config, validate  # noqa: E402

CFG = config.load()


def test_break_flags_follow_the_declared_month():
    import dataclasses
    m = dict(CFG.method, series_breaks=[{"month": "2026-07", "note_uz": "x", "families": []}])
    cfg = dataclasses.replace(CFG, method=m)
    assert breaks.flags(CFG, "2026Q3") is None                  # nothing declared in the live config
    f = breaks.flags(cfg, "2026Q3")
    assert f and f["qoq"] and f["yoy"] and f["month"] == "2026-07"
    f4 = breaks.flags(cfg, "2026Q4")
    assert f4 and not f4["qoq"] and f4["yoy"]          # Q3 vs Q4 both new rules; year ago still old
    assert breaks.flags(cfg, "2027Q3") is None          # both sides after the break
    assert breaks.flags(cfg, "2026Q2") is None


def test_like_for_like_uses_only_listings_in_both_quarters():
    rows = []
    for i in range(40):
        rows.append(dict(family="regions_rent", id=i, region="Buxoro", market="rent", price=300.0, quarter="2026Q2"))
        rows.append(dict(family="regions_rent", id=i, region="Buxoro", market="rent", price=303.0, quarter="2026Q3"))
    rows.append(dict(family="regions_rent", id=999, region="Buxoro", market="rent", price=900.0, quarter="2026Q3"))
    t = breaks.like_for_like(pd.DataFrame(rows), CFG, "2026Q2", "2026Q3")
    r = t[(t.unit == "Buxoro") & (t.market == "rent")].iloc[0]
    assert r.n == 40 and round(r.mean_pct, 1) == 1.0 and r.status == "ok"


def test_section_must_mention_the_break():
    sec = {"key": "ijara", "title": "T", "facts": ["report"], "news_topics": [], "note_break": True,
           "slots": {"a": {"words": [1, 50], "about": ""}}}
    facts = {"report": {"series_break": {"month": "2026-07", "qoq": True, "yoy": True}}}
    bad = validate.check_section(sec, {"a": "Narxlar oʻzgardi."}, facts, [])
    ok = validate.check_section(sec, {"a": "Maʼlumotlar boshqa qoidalar asosida qayta ishlangan."}, facts, [])
    assert "series_break" in {i["code"] for i in bad}
    assert "series_break" not in {i["code"] for i in ok}


def test_numbers_used_must_match_their_id():
    facts = {"solishtirma": {"id": "lfl", "qoq": {"ijara": [
        {"id": "lfl.qoq.rent.Respublika", "name": "Respublika", "mean_usd_pct": 0.7},
        {"id": "lfl.qoq.rent.Xorazm", "name": "Xorazm", "mean_usd_pct": 1.7}]}}}
    ok = validate.check_numbers_used([{"text": "0.7%", "id": "lfl.qoq.rent.Respublika.mean_usd_pct"}], facts, [])
    bad = validate.check_numbers_used([{"text": "1.7%", "id": "lfl.qoq.rent.Respublika.mean_usd_pct"}], facts, [])
    assert not ok and bad and bad[0]["level"] == "error"


def test_break_keyword_comes_from_config():
    sec = {"key": "ijara", "title": "T", "facts": ["report"], "news_topics": [], "note_break": True,
           "slots": {"a": {"words": [1, 50], "about": ""}}}
    facts = {"report": {"series_break": {"month": "2026-07", "qoq": True, "yoy": True, "keyword_uz": "tarkibi oʻzgar"}}}
    bad = validate.check_section(sec, {"a": "Maʼlumotlar qayta ishlangan."}, facts, [])
    ok = validate.check_section(sec, {"a": "Manba maʼlumotlari tarkibi oʻzgargan."}, facts, [])
    assert "series_break" in {i["code"] for i in bad} and "series_break" not in {i["code"] for i in ok}
