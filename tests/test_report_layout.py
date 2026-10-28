"""New report layout: derived facts blocks, charts and maps, figure references, news merging."""
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from uyjoy import charts, history, news, render, validate  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def _facts():
    rows = [{"name": "Toshkent shahri", "n": 900, "status": "ok", "qoq_pct": -1.0, "yoy_pct": 5.0},
            {"name": "Xorazm", "n": 30, "status": "ok", "qoq_pct": 20.0, "yoy_pct": 30.0},
            {"name": "Sirdaryo", "n": 70, "status": "thin", "qoq_pct": 10.0, "yoy_pct": 10.0},
            {"name": "Jizzax", "n": 5, "status": "hidden", "qoq_pct": None, "yoy_pct": None}]
    lfl = [{"name": "Respublika", "mean_pct": -2.0, "status": "ok", "n": 500}]
    return {"birlamchi": {"rows": rows, "avg_qoq_pct": 9.7},
            "solishtirma": {"qoq": {"birlamchi": lfl}, "yoy": {"birlamchi": lfl}}}


def test_weighted_change_and_composition():
    nat = history.national_block(_facts())["birlamchi"]
    # (900*-1 + 30*20 + 70*10) / 1000 = 0.4; hidden region left out
    assert nat["weighted_qoq_pct"] == 0.4
    assert nat["simple_qoq_pct"] == 9.7
    assert nat["composition_pp"] == 2.4
    assert nat["n"] == 1000 and nat["tashkent_share_pct"] == 90


def test_premium_block():
    t = pd.DataFrame([
        {"quarter": "2026Q3", "unit": "A", "market": "prim", "median_usd": 1200, "status": "ok"},
        {"quarter": "2026Q3", "unit": "A", "market": "sec", "median_usd": 1000, "status": "ok"},
        {"quarter": "2025Q3", "unit": "A", "market": "prim", "median_usd": 1100, "status": "ok"},
        {"quarter": "2025Q3", "unit": "A", "market": "sec", "median_usd": 1000, "status": "ok"},
        {"quarter": "2026Q3", "unit": "B", "market": "prim", "median_usd": 900, "status": "ok"},
        {"quarter": "2026Q3", "unit": "B", "market": "sec", "median_usd": 1000, "status": "thin"},
    ])
    p = history.premium_block(t, "2026Q3", ["A", "B"], "hudud")
    a, b = p["rows"]
    assert (a["value"], a["prev_year"], a["change_pp"]) == (20.0, 10.0, 10.0)
    assert b["value"] == -10.0 and b["status"] == "thin"
    assert p["highest"] == ["A"] and p["negative"] == []      # thin regions are never headlined


def test_charts_are_valid_svg():
    vals = {"Toshkent shahri": {"value": -0.4, "status": "ok"}, "Xorazm": {"value": 15.0, "status": "ok"},
            "Jizzax": {"value": 6.0, "status": "thin"}}
    svgs = [charts.choropleth(vals, "div"),
            charts.choropleth({"Mirobod": {"value": 24.0, "status": "ok"}}, "seq", file="tashkent_districts.json",
                              fmt_nd=2, sign=False, legend="mln"),
            charts.dumbbell([{"name": "A", "prev": 10, "value": 11, "qoq_pct": 10.0}]),
            charts.heatmap([{"name": "A", "values": [1.0, None, -3.0], "status": ["ok", "hidden", "thin"]}],
                           ["Ch1|2026", "Ch2|2026", "Ch3|2026"]),
            charts.lines([{"name": "x", "values": [1, 2, None, 4], "color": "#000"}], ["a", "b", "c", "d"]),
            charts.grouped_bars([{"name": "g", "values": [1.0, -2.0, 0.5]}], ["a", "b", "c"], ["#111", "#222", "#333"]),
            charts.scatter_yield([{"name": "A", "x": 8.0, "y": 60.0}, {"name": "B", "x": 9.0, "y": 55.0}]),
            charts.small_multiples([{"name": "A", "series": [[1, 2, 3], [2, None, 1]]}], ["q1", "q2", "q3"])]
    for s in svgs:
        assert s.startswith("<svg") and s.endswith("</svg>")
        assert "nan" not in s.lower() and "None" not in s
    # every region of the country map is drawn, Tashkent city as a ringed dot with a callout
    assert svgs[0].count("<path") >= 13 and "Toshkent sh." in svgs[0]


def test_change_colours_are_fixed_steps():
    assert charts.div_color(-6) == charts.DIV[0] and charts.div_color(0) == charts.DIV[3]
    assert charts.div_color(7) == charts.DIV[-1] and charts.div_color(None) == charts.NODATA


def test_figures_numbered_in_reading_order():
    num = render.figures("respublika")
    assert num["fig"]["decomp"]["no"] == 1
    nos = [v["no"] for v in num["fig"].values()]
    assert nos == list(range(1, len(nos) + 1))
    assert num["tab"]["summary"]["no"] == 1


def test_figure_pointer_is_not_a_number():
    issues = validate.check_text("x", "Narx oshdi (7-rasm), 3-jadvalga qarang.", {}, [], None)
    assert not [i for i in issues if i["code"] == "number"]


def test_cite_joins_markers_and_marks_refs():
    news_items = {"n01": {"url": "https://a"}, "n02": {"url": "https://b"}}
    out = render.cite("**Narx.** Stavka 14% [n01][n02] (2-rasm).", {}, news_items)
    assert '<b class="t">Narx.</b>' in out and '1,2</sup>' in out and '<span class="ref">2-rasm</span>' in out


def test_news_add_keeps_ids(tmp_path):
    old = [{"id": "n01", "topic": "stavka", "date": "2026-09-16", "url": "https://cbu.uz/a", "claim_uz": "A",
            "numbers": [], "official": True, "relevance": 5, "outlet": "cbu.uz", "title": "", "geography": "respublika"}]
    extra = [dict(old[0], id=None), {"topic": "ipoteka", "date": "2026-08-01", "url": "https://spot.uz/b",
                                     "claim_uz": "B", "numbers": [{"value": 13.1}]}]
    (tmp_path / "news.json").write_text(json.dumps(old), encoding="utf-8")
    (tmp_path / "extra.json").write_text(json.dumps(extra), encoding="utf-8")
    out = news.add(tmp_path / "news.json", tmp_path / "extra.json", "2026Q3")
    assert [n["id"] for n in out] == ["n01", "n02"] and out[1]["url"] == "https://spot.uz/b"


def test_geo_assets_cover_all_names():
    import yaml
    geo = yaml.safe_load((ROOT / "config" / "geo.yaml").read_text(encoding="utf-8"))
    uz = json.loads((ROOT / "assets" / "geo" / "uz_regions.json").read_text(encoding="utf-8"))
    tsh = json.loads((ROOT / "assets" / "geo" / "tashkent_districts.json").read_text(encoding="utf-8"))
    assert set(geo["region_order"]) == set(uz["regions"])
    assert set(geo["district_order"]) == set(tsh["regions"])
