"""Render facts + draft text + news into the report HTML and PDF.

Tables, charts and maps come straight from facts.json; no number is typed into the template.
Source markers [n03] become numbered superscripts that point to the source list. Figures and tables
are numbered in the order of templates/figures.yaml, the same numbers the writer was given.
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path

import pandas as pd
import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

from . import charts as ch
from .config import CONFIG_DIR, ROOT

TEMPLATES = ROOT / "templates"
SECTION_MARKET = {"birlamchi": "prim", "ikkilamchi": "sec", "ijara": "rent"}
OY = ["yanvar", "fevral", "mart", "aprel", "may", "iyun", "iyul", "avgust", "sentabr", "oktabr", "noyabr", "dekabr"]


def period_uz(q: str) -> str:
    p = pd.Period(q, "Q")
    return f"{p.year}-yil {p.quarter}-chorak"


def col_label(q: str) -> str:
    p = pd.Period(q, "Q")
    return f"{p.year}-Ch{p.quarter}"


def months_uz(q: str) -> str:
    p = pd.Period(q, "Q")
    m = p.quarter * 3
    return f"{OY[m - 3]}–{OY[m - 1]}"


def fmt(v, nd=2):
    return "—" if v is None else f"{v:.{nd}f}"


def fmt_pct(v, nd=1):
    if v is None:
        return ""
    return f"{'+' if v > 0 else ''}{v:.{nd}f}%"


def fmt_int(v):
    return "" if v is None else "{:,}".format(int(v)).replace(",", " ")


def _sign(v):
    return "" if v is None or v == 0 else ("up" if v > 0 else "down")


def figures(scope: str) -> dict:
    spec = yaml.safe_load((TEMPLATES / "figures.yaml").read_text(encoding="utf-8")).get(scope, {})
    out = {"fig": {}, "tab": {}}
    for kind, key in (("figures", "fig"), ("tables", "tab")):
        for i, f in enumerate(spec.get(kind, []), 1):
            out[key][f["key"]] = {"no": i, "title": f["title"], "section": f["section"]}
    return out


def table(block: dict, nd: int, lfl: list[dict] | None = None, hist: list[dict] | None = None,
          color: str = ch.ACCENT) -> dict:
    """Rows for one price table; `lfl` adds the same-listings column, `hist` a sparkline per row."""
    lmap = {r["name"]: r for r in (lfl or []) if r.get("status") in ("ok", "thin") and r.get("mean_pct") is not None}
    hmap = {h["name"]: h for h in (hist or [])}
    rows = [r for r in block["rows"] if r.get("status") != "missing"]
    has_q = any(r.get("qoq_pct") is not None for r in rows)
    has_y = any(r.get("yoy_pct") is not None for r in rows)
    out = []
    for r in rows:
        st = r.get("status")
        val = "—" if st == "hidden" else fmt(r.get("value"), nd) + ("*" if st == "thin" else "")
        h = hmap.get(r["name"])
        out.append({"name": r["name"], "value": val, "n": r.get("n"), "status": st,
                    "qoq": fmt_pct(r.get("qoq_pct")) if st != "hidden" else "",
                    "yoy": fmt_pct(r.get("yoy_pct")) if st != "hidden" else "",
                    "qoq_sign": _sign(r.get("qoq_pct")), "yoy_sign": _sign(r.get("yoy_pct")),
                    "qoq_bg": ch.div_color(r.get("qoq_pct")) if st != "hidden" and r.get("qoq_pct") is not None else "",
                    "spark": ch.sparkline(h["values"], color=color) if h and st != "hidden" else "",
                    "lfl": (fmt_pct(lmap[r["name"]]["mean_pct"]) + ("*" if lmap[r["name"]]["status"] == "thin" else ""))
                    if r["name"] in lmap and st != "hidden" else ""})
    return {"rows": out, "has_q": has_q, "has_y": has_y, "has_lfl": bool(lmap), "unit": block["unit"],
            "has_spark": bool(hist)}


def cite(text: str, order: dict, news: dict) -> str:
    """Escape, then turn [n03] into superscripts numbered per source article, in reading order."""
    t = html.escape(text)
    t = re.sub(r"\*\*(.+?)\*\*", r'<b class="t">\1</b>', t)   # **lead-in** -> bold lead-in

    def sub(m):
        url = news.get(m.group(1), {}).get("url", m.group(1))
        if url not in order:
            order[url] = len(order) + 1
        return f'<sup class="cite">{order[url]}</sup>'
    t = re.sub(r"\[(n\d{2})\]", sub, t)
    t = re.sub(r'(<sup class="cite">(\d+)</sup>)(\s*<sup class="cite">\2</sup>)+', r"\1", t)
    t = re.sub(r'</sup>\s*<sup class="cite">', ",", t)      # [n10][n11] -> 10,11
    return re.sub(r"(\d+-(?:rasm|jadval))", r'<span class="ref">\1</span>', t)


def _vals(block: dict) -> dict:
    return {r["name"]: {"value": r.get("value"), "status": r.get("status", "missing")} for r in block.get("rows", [])}


def _chg(block: dict) -> dict:
    return {r["name"]: {"value": r.get("qoq_pct"), "status": r.get("status", "missing") if r.get("qoq_pct") is not None
                        else "missing"} for r in block.get("rows", [])}


def build_figures(facts: dict) -> dict:
    """Every chart and map of the Respublika report, as SVG strings."""
    f, svg = facts, {}
    tt = f.get("toshkent_tumanlari", {})
    q_labels = [col_label(q) for q in f.get("tarix", {}).get("quarters", [])]
    nat = f.get("respublika", {})
    lab = {"birlamchi": "Birlamchi", "ikkilamchi": "Ikkilamchi", "ijara": "Ijara"}
    svg["decomp"] = ch.grouped_bars(
        [{"name": lab[k], "values": [nat[k]["simple_qoq_pct"], nat[k]["weighted_qoq_pct"], nat[k]["lfl_qoq_pct"]]}
         for k in ("birlamchi", "ikkilamchi", "ijara") if k in nat],
        ["Hududlar oddiy oʻrtachasi", "Eʼlonlar soniga koʻra tortilgan", "Bir xil eʼlonlar"],
        ["#9fb7d6", ch.ACCENT, ch.DIV[0]], w=410, h=250, title="Narx oʻzgarishi va eʼlonlar tarkibi")

    m = f.get("makro") or {}
    ser = m.get("series", [])
    if ser:
        xl = [col_label(r["quarter"]) for r in ser]
        svg["rates"] = ch.lines([
            {"name": "Asosiy stavka", "values": [r["base_rate_pct"] for r in ser], "color": ch.ACCENT_DARK, "width": 2.4,
             "bold": True},
            {"name": "Inflyatsiya", "values": [r["inflation_yoy_pct"] for r in ser], "color": ch.DIV[0], "width": 2}],
            xl, w=330, h=250, unit="%", y_min=0, area={"series": (0, 1), "color": "#dde7f4"}, label_every=3,
            title="Asosiy stavka va inflyatsiya")
        svg["fx"] = ch.lines([{"name": "", "values": [r["usd_uzs"] for r in ser], "color": ch.INK2,
                               "width": 2, "bold": True}], xl, w=330, h=250, nd=0, label_every=3, title="USD/UZS",
                             right_pad=50)
    ann = (m.get("annual") or {}).get("rows", [])
    if ann:
        a = [r for r in ann if r["deals"]]
        svg["deals"] = ch.vbars([str(r["year"]) for r in a], [r["deals"] / 1000 for r in a], w=330, h=250, nd=0,
                                color="#8aa9cf", line=[r["mortgage_share_pct"] for r in a],
                                line_label="ipoteka ulushi", title="Bitimlar, ming|Bitimlar va ipoteka")
        b = [r for r in ann if r["housing_built_k"]]
        svg["build"] = ch.vbars([str(r["year"]) for r in b], [r["housing_built_k"] for r in b],
                                plan=[r["plan"] for r in b], w=330, h=250, nd=1, color=ch.ACCENT,
                                title="Uy-joy qurilishi, ming dona")
        mm = [r for r in ann if r["mortgage_primary_bn"]]
        svg["mortgage"] = ch.stacked_vbars([str(r["year"]) for r in mm],
                                           [[r["mortgage_primary_bn"], r["mortgage_secondary_bn"]] for r in mm],
                                           ["Birlamchi", "Ikkilamchi"], [ch.MARKET["birlamchi"], ch.MARKET["ikkilamchi"]],
                                           w=270, h=250, total_unit=" trln", title="Ipoteka hajmi")

    tsh_geo = "tashkent_districts.json"
    for sec, key in (("birlamchi", "prim"), ("ikkilamchi", "sec"), ("ijara", "rent")):
        if sec not in f:
            continue
        nd = 1 if sec == "ijara" else 2
        if sec == "ijara":
            svg["rent_map"] = ch.choropleth(_vals(f[sec]), "seq", fmt_nd=1, sign=False, legend="ming soʻm/m², oyiga",
                                            title="Ijara narxlari xaritasi")
        else:
            svg[f"{key}_map"] = ch.choropleth(_chg(f[sec]), "div", title=f"{sec} xaritasi")
        t = tt.get(sec)
        if t:
            if sec == "ikkilamchi":
                svg["sec_tsh_map"] = ch.choropleth(_chg(t), "div", file=tsh_geo, title="Toshkent tumanlari, Δ chorak")
            else:
                svg[f"{key}_tsh_map"] = ch.choropleth(_vals(t), "seq", file=tsh_geo, fmt_nd=nd, sign=False,
                                                      legend=t["unit"], title="Toshkent tumanlari")
            if sec != "ijara":
                svg[f"{key}_dumbbell"] = ch.dumbbell(
                    [{"name": r["name"], "prev": r.get("prev_value"), "value": r.get("value"), "qoq_pct": r.get("qoq_pct")}
                     for r in t["rows"] if r.get("status") != "hidden"], w=330, nd=nd,
                    color=ch.MARKET[sec], title="Tumanlar")

    pr = f.get("premium") or {}
    if pr:
        rows = [{"name": r["name"], "value": r["value"], "status": r["status"],
                 "bold": r["name"] == "Toshkent shahri"} for r in pr["rows"] if r["value"] is not None]
        svg["premium"] = ch.hbars(rows, w=410, signed=True, unit="%", title="Birlamchi ustamasi")
    tr = f.get("tarix") or {}
    if tr.get("birlamchi"):
        panels = []
        for a, b in zip(tr["birlamchi"], tr["ikkilamchi"]):
            if all(v is None for v in a["values"] + b["values"]):
                continue
            ok = lambda r: [v if st == "ok" else None for v, st in zip(r["values"], r["status"])]  # noqa: E731
            panels.append({"name": a["name"], "series": [ok(a), ok(b)]})
        svg["multiples"] = ch.small_multiples(panels, [col_label(q) for q in tr["quarters"]], cols=5, w=690, ph=100,
                                              names=["Birlamchi, mln soʻm/m²", "Ikkilamchi"])

    xr = f.get("xonalar_toshkent") or {}
    if xr.get("ijara"):
        svg["rent_rooms"] = ch.value_heatmap(xr["ijara"], [f"{r} xona" if r != "4+" else "4+ xona" for r in xr["rooms"]],
                                             w=330, unit="ming soʻm/m², oyiga", nd=1)

    y = f.get("ijara_rentabelligi") or {}
    if y:
        svg["yield_map"] = ch.choropleth(_vals(y), "seq", fmt_nd=1, sign=False, legend="yillik rentabellik, %",
                                         title="Rentabellik xaritasi")
        sale = {r["name"]: r for r in f.get("birlamchi", {}).get("rows", [])}
        secr = {r["name"]: r for r in f.get("ikkilamchi", {}).get("rows", [])}
        rent = {r["name"]: r for r in f.get("ijara", {}).get("rows", [])}
        pts = []
        tsh_note = ""
        for yr in y["rows"]:
            n = yr["name"]
            if n == "Toshkent shahri":
                sv = [v for v in (sale.get(n, {}).get("value"), secr.get(n, {}).get("value")) if v is not None]
                if sv and rent.get(n, {}).get("value") is not None:
                    tsh_note = (f"Toshkent sh.: {sum(sv) / len(sv):.1f} mln; {rent[n]['value']:.1f} ming; "
                                f"{yr['value']:.1f}% (shkaladan tashqarida)")
                continue
            if yr.get("value") is None or n not in rent or rent[n].get("value") is None:
                continue
            # sale level for the scatter: average of the two markets' medians (the yield uses both markets)
            sv = [v for v in (sale.get(n, {}).get("value"), secr.get(n, {}).get("value")) if v is not None]
            if not sv:
                continue
            pts.append({"name": n, "x": sum(sv) / len(sv), "y": rent[n]["value"], "status": yr["status"],
                        "bold": n == "Toshkent shahri"})
        svg["yield_scatter"] = ch.scatter_yield(pts, w=330, h=300)
        svg["yield_scatter_note"] = tsh_note
        yt = f.get("rentabellik_tarix") or {}
        if yt.get("rows"):
            vals_by = {r["name"]: r["values"] for r in yt["rows"]}
            regs = [r for r in yt["rows"] if r["name"] != "Toshkent shahri"]
            med = []
            for i in range(len(yt["quarters"])):
                col = sorted(v for v in (r["values"][i] for r in regs) if v is not None)
                med.append(round(col[len(col) // 2] if len(col) % 2 else (col[len(col) // 2 - 1] + col[len(col) // 2]) / 2, 1)
                           if col else None)
            svg["yield_trend"] = ch.lines([
                {"name": "Toshkent sh.", "values": vals_by.get("Toshkent shahri", []), "color": ch.ACCENT_DARK, "bold": True,
                 "width": 2.4},
                {"name": "Hududlar medianasi", "values": med, "color": ch.MARKET["ijara"], "width": 2}],
                [col_label(q) for q in yt["quarters"]], w=330, h=250, unit="%", label_every=3)

    ih = f.get("indeks_hududlar") or {}
    ui = f.get("uy_joy_indeksi") or {}
    if ih.get("rows") and ui.get("series"):
        qs = ih["quarters"]
        nat_s = {s["quarter"]: s["value"] for s in ui["series"]}
        rows = {r["name"]: r for r in ih["rows"]}
        hi = [r["name"] for r in ui.get("highest_regions", [])[:2]]
        lo = [r["name"] for r in ui.get("lowest_regions", [])[:2]]
        series = [{"name": "Respublika (UNI)", "values": [nat_s.get(q) for q in qs], "color": ch.INK, "width": 3,
                   "bold": True},
                  {"name": "Toshkent sh.", "values": rows.get("Toshkent shahri", {}).get("values", []),
                   "color": ch.ACCENT, "width": 2}]
        tones_hi, tones_lo = ["#1a8f80", "#5fb3a8"], ["#d68a1f", "#e8b46a"]
        for n, c in zip(hi, tones_hi):
            series.append({"name": n, "values": rows[n]["values"], "color": c, "width": 1.6})
        for n, c in zip(lo, tones_lo):
            series.append({"name": n, "values": rows[n]["values"], "color": c, "width": 1.6, "dash": "4 3"})
        svg["index_lines"] = ch.lines(series, [col_label(q) for q in qs], w=690, h=270, baseline=100, label_every=2,
                                      right_pad=150)
        svg["index_regions"] = ch.hbars([{"name": r["name"], "value": r["value"], "status": "ok",
                                          "bold": r["name"] == "Toshkent shahri"} for r in ih["rows"] if r["value"]],
                                        w=330, value_nd=1, ref=ui.get("value"), ref_label=f"UNI {ui.get('value')}",
                                        color="#8aa9cf", label_w=112, x_min=90)
        tsec = (f.get("tarix") or {}).get("ikkilamchi", [])
        if tsec:
            q8 = tr["quarters"][-8:]
            svg["index_heat"] = ch.heatmap([{"name": r["name"], "values": r["qoq_pct"][-8:], "status": r["status"][-8:],
                                             "bold": r["name"] == "Toshkent shahri"} for r in tsec
                                            if any(v is not None for v in r["qoq_pct"][-8:])],
                                           [f"Ch{q[-1]}|{q[:4]}" for q in q8], w=330, label_w=104)
    return svg


def kpis(facts: dict) -> list[dict]:
    tr = facts.get("tarix") or {}

    def city(sec, unit):
        r = next((x for x in facts.get(sec, {}).get("rows", []) if x["name"] == "Toshkent shahri"), None)
        h = next((x for x in tr.get(sec, []) if x["name"] == "Toshkent shahri"), None)
        if not r:
            return None
        nd = 1 if sec == "ijara" else 2
        return {"label": {"birlamchi": "Birlamchi bozor", "ikkilamchi": "Ikkilamchi bozor", "ijara": "Ijara"}[sec],
                "sub": "Toshkent shahri", "value": fmt(r["value"], nd), "unit": unit,
                "d1": fmt_pct(r.get("qoq_pct")), "d1_sign": _sign(r.get("qoq_pct")), "d1_l": "chorak",
                "d2": fmt_pct(r.get("yoy_pct")), "d2_sign": _sign(r.get("yoy_pct")), "d2_l": "yil",
                "spark": ch.sparkline(h["values"], 118, 30, ch.MARKET[sec]) if h else ""}
    out = [city("birlamchi", "mln soʻm/m²"), city("ikkilamchi", "mln soʻm/m²"), city("ijara", "ming soʻm/m², oyiga")]
    ui = facts.get("uy_joy_indeksi") or {}
    if ui:
        out.append({"label": "Uy-joy narxlari indeksi", "sub": f"{ui['base'][:4]}-yil {ui['base'][-1]}-chorak = 100, USD",
                    "value": fmt(ui.get("value"), 1), "unit": "",
                    "d1": fmt_pct(ui.get("qoq_pct")), "d1_sign": _sign(ui.get("qoq_pct")), "d1_l": "chorak",
                    "d2": fmt_pct(ui.get("yoy_pct")), "d2_sign": _sign(ui.get("yoy_pct")), "d2_l": "yil",
                    "spark": ch.sparkline([s["value"] for s in ui["series"]], 118, 30, ch.INK)})
    m = facts.get("makro") or {}
    if m.get("base_rate_pct") is not None:
        out.append({"label": "Asosiy stavka", "sub": "Markaziy bank, chorak oxirida", "value": fmt(m["base_rate_pct"], 0),
                    "unit": "%", "d1": f"{fmt(m.get('inflation_yoy_pct'), 1)}%", "d1_sign": "", "d1_l": "inflyatsiya",
                    "d2": f"{fmt(m.get('real_rate_pp'), 1)} f.p.", "d2_sign": "", "d2_l": "real stavka",
                    "spark": ch.sparkline([s["base_rate_pct"] for s in m["series"]], 118, 30, ch.ACCENT_DARK)})
    rep = facts["report"]
    if rep.get("usd_uzs_end"):
        fxs = [s.get("usd_uzs") for s in m.get("series", [])]
        out.append({"label": "AQSH dollari kursi", "sub": "chorak oxirida, soʻm", "value": fmt_int(rep["usd_uzs_end"]),
                    "unit": "", "d1": fmt_pct(rep.get("som_vs_usd_pct")), "d1_sign": _sign(rep.get("som_vs_usd_pct")),
                    "d1_l": "soʻm kursi", "d2": "", "d2_sign": "", "d2_l": "",
                    "spark": ch.sparkline(fxs, 118, 30, ch.INK2) if any(fxs) else ""})
    return [k for k in out if k]


def summary_rows(facts: dict) -> list[dict]:
    nat = facts.get("respublika") or {}
    out = []
    for sec, lab, nd, unit in (("birlamchi", "Birlamchi bozor", 2, "mln soʻm/m²"), ("ikkilamchi", "Ikkilamchi bozor", 2,
                                                                                    "mln soʻm/m²"),
                               ("ijara", "Ijara", 1, "ming soʻm/m²")):
        r = next((x for x in facts.get(sec, {}).get("rows", []) if x["name"] == "Toshkent shahri"), {})
        n = nat.get(sec, {})
        out.append({"label": lab, "unit": unit, "tsh": fmt(r.get("value"), nd), "tsh_q": fmt_pct(r.get("qoq_pct")),
                    "simple": fmt_pct(n.get("simple_qoq_pct")), "weighted": fmt_pct(n.get("weighted_qoq_pct")),
                    "weighted_y": fmt_pct(n.get("weighted_yoy_pct")), "lfl": fmt_pct(n.get("lfl_qoq_pct")),
                    "comp": (f"{n['composition_pp']:+.1f} f.p." if n.get("composition_pp") is not None else ""),
                    "n": fmt_int(n.get("n")),
                    "signs": {k: _sign(n.get(k)) for k in ("simple_qoq_pct", "weighted_qoq_pct", "weighted_yoy_pct",
                                                           "lfl_qoq_pct")}})
    return out


def macro_rows(facts: dict, n: int = 6) -> list[dict]:
    ser = (facts.get("makro") or {}).get("series", [])[-n:]
    out, prev = [], None
    full = (facts.get("makro") or {}).get("series", [])
    for r in ser:
        i = full.index(r)
        p = full[i - 1] if i else None
        real = (r["base_rate_pct"] - r["inflation_yoy_pct"]) if None not in (r["base_rate_pct"], r["inflation_yoy_pct"]) else None
        fx_chg = (p["usd_uzs"] / r["usd_uzs"] - 1) * 100 if p and p.get("usd_uzs") and r.get("usd_uzs") else None
        out.append({"q": col_label(r["quarter"]), "rate": fmt(r["base_rate_pct"], 1), "infl": fmt(r["inflation_yoy_pct"], 1),
                    "real": fmt(real, 1), "fx": fmt_int(r.get("usd_uzs")), "fx_chg": fmt_pct(fx_chg), "fx_sign": _sign(fx_chg)})
    return out


def annex_rows(facts: dict) -> list[dict]:
    tt = facts.get("toshkent_tumanlari") or {}
    yl = {r["name"]: r for r in (facts.get("rentabellik_tumanlar") or {}).get("rows", [])}
    pr = {r["name"]: r for r in (facts.get("premium_tumanlar") or {}).get("rows", [])}
    names = [r["name"] for r in tt.get("birlamchi", {}).get("rows", [])]
    out = []
    for n in names:
        row = {"name": n}
        for sec, nd in (("birlamchi", 2), ("ikkilamchi", 2), ("ijara", 1)):
            r = next((x for x in tt.get(sec, {}).get("rows", []) if x["name"] == n), {})
            row[sec] = {"v": fmt(r.get("value"), nd), "q": fmt_pct(r.get("qoq_pct")), "y": fmt_pct(r.get("yoy_pct")),
                        "qs": _sign(r.get("qoq_pct")), "n": fmt_int(r.get("n"))}
        row["yield"] = fmt(yl.get(n, {}).get("value"), 1) + "%" if yl.get(n, {}).get("value") is not None else "—"
        row["premium"] = fmt_pct(pr.get(n, {}).get("value")) or "—"
        out.append(row)
    return out


def render(run_dir: Path, scope: str, pdf: bool = True) -> Path:
    facts = json.loads((run_dir / "facts.json").read_text(encoding="utf-8"))
    draft = json.loads((run_dir / "draft.json").read_text(encoding="utf-8"))
    news = {n["id"]: n for n in json.loads((run_dir / "news.json").read_text(encoding="utf-8"))}
    method = yaml.safe_load((CONFIG_DIR / "method.yaml").read_text(encoding="utf-8"))
    order: dict[str, int] = {}
    reading = ["asosiy_xulosalar", "makro", "ipoteka", "birlamchi", "ikkilamchi", "premium", "ijara", "rentabellik",
               "indeks", "bozor_sharhi"]
    keys = [k for k in reading if k in draft] + [k for k in draft if k not in reading]
    text = {sec: {k: cite(v, order, news) for k, v in draft[sec]["slots"].items()} for sec in keys}
    rep = facts["report"]
    lfl_q = (facts.get("solishtirma") or {}).get("qoq", {})
    tr = facts.get("tarix") or {}
    tth = facts.get("tarix_tumanlar") or {}
    hist = {k: tr.get(k) for k in ("birlamchi", "ikkilamchi", "ijara")}
    ctx = {
        "scope": scope, "period": rep["period"], "period_uz": period_uz(rep["period"]), "months": months_uz(rep["period"]),
        "col": col_label(rep["period"]), "rep": rep, "text": text, "method": method, "facts": facts,
        "partial": rep.get("partial_families", []),
        "t": {k: table(facts[k], 2 if k != "ijara" else 1, lfl_q.get(k), hist.get(k),
                       ch.MARKET[k]) for k in ("birlamchi", "ikkilamchi", "ijara") if k in facts},
        "tt": {k: table(v, 2 if k != "ijara" else 1, None, tth.get(k), ch.MARKET[k])
               for k, v in facts.get("toshkent_tumanlari", {}).items()},
        "brk": rep.get("series_break"),
        "brk_tash": bool(rep.get("series_break")) and any(f.startswith("tashkent") for f in rep["series_break"].get("families", [])),
        "svg": build_figures(facts) if scope == "respublika" else {},
        "kpis": kpis(facts), "summary": summary_rows(facts), "macro_rows": macro_rows(facts), "annex": annex_rows(facts),
        "num": figures(scope), "index": facts.get("uy_joy_indeksi", {}), "nat": facts.get("respublika", {}),
        "makro": facts.get("makro", {}), "premium": facts.get("premium", {}),
        "partial_months": {f: rep["months_present"].get(f, []) for f in rep.get("partial_families", [])},
        "fmt": fmt, "fmt_pct": fmt_pct, "fmt_int": fmt_int,
        "T": lambda sec, slot: Markup(text.get(sec, {}).get(slot, "")),
    }
    ctx["sources"] = [{"no": i, **next(n for n in news.values() if n["url"] == u)}
                      for u, i in sorted(order.items(), key=lambda x: x[1])]
    ctx["data_sources"] = _data_sources(facts)
    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html"]))
    out_html = run_dir / "report.html"
    out_html.write_text(env.get_template(f"{scope}.html").render(**ctx), encoding="utf-8")
    if not pdf:
        return out_html
    out_pdf = run_dir / "report.pdf"
    from playwright.sync_api import sync_playwright  # noqa: PLC0415
    footer = ('<div style="font-size:7.5px;width:100%;padding:0 14mm;display:flex;justify-content:space-between;'
              'color:#4d5868;font-family:Carlito,sans-serif"><span>Oʻzbekistonda uy-joy bozori sharhi · '
              f'{period_uz(rep["period"])}</span><span class="pageNumber"></span></div>')
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        pg.goto(out_html.resolve().as_uri())
        pg.pdf(path=str(out_pdf), format="A4", print_background=True,
               margin={"top": "12mm", "bottom": "14mm", "left": "13mm", "right": "13mm"},
               display_header_footer=True, header_template="<span></span>", footer_template=footer)
        b.close()
    return out_pdf


def _data_sources(facts: dict) -> list[dict]:
    """Where the chart data that does not come from olx.uz was taken from (macro CSVs)."""
    m = facts.get("makro") or {}
    out = []
    if m.get("sources"):
        hosts = sorted({re.sub(r"^https?://(www\.)?", "", u).split("/")[0] for u in m["sources"]})
        out.append({"what": "Asosiy stavka va yillik inflyatsiya (chorak oxiri)", "where": ", ".join(hosts),
                    "urls": m["sources"]})
    if (m.get("annual") or {}).get("source"):
        out.append({"what": "Bitimlar, ipoteka kreditlari, uy-joy qurilishi (yillik)", "where": m["annual"]["source"],
                    "urls": []})
    out.append({"what": "AQSH dollari kursi", "where": "Markaziy bank (cbu.uz), chorak oxiridagi rasmiy kurs", "urls": []})
    return out
