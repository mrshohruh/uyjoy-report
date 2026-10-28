"""Render facts + draft text + news into the report HTML and PDF.

Tables and charts come straight from facts.json; no number is typed into the template.
Source markers [n03] become numbered superscripts that point to the source list.
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path

import pandas as pd
import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape

from .config import CONFIG_DIR, ROOT

TEMPLATES = ROOT / "templates"
C = {"ink": "#0b0b0b", "ink2": "#52514e", "grid": "#e1e0d9", "axis": "#c3c2b7",
     "blue": "#2a78d6", "blue_light": "#86b6ef", "surface": "#fcfcfb"}


def period_uz(q: str) -> str:
    p = pd.Period(q, "Q")
    return f"{p.year}-yil {p.quarter}-chorak"


def col_label(q: str) -> str:
    p = pd.Period(q, "Q")
    return f"{p.year}-Ch{p.quarter}"


def fmt(v, nd=2):
    return "—" if v is None else f"{v:.{nd}f}"


def fmt_pct(v):
    if v is None:
        return ""
    return f"{'+' if v > 0 else ''}{v:.1f}%"


def table(block: dict, nd: int, lfl: list[dict] | None = None) -> dict:
    """Rows for one price table. `lfl`: like-for-like rows (shown as an extra column across a series break)."""
    lmap = {r["name"]: r for r in (lfl or []) if r.get("status") in ("ok", "thin") and r.get("mean_pct") is not None}
    rows = [r for r in block["rows"] if r.get("status") != "missing"]
    has_q = any(r.get("qoq_pct") is not None for r in rows)
    has_y = any(r.get("yoy_pct") is not None for r in rows)
    out = []
    for r in rows:
        st = r.get("status")
        val = "—" if st == "hidden" else fmt(r.get("value"), nd) + ("*" if st == "thin" else "")
        out.append({"name": r["name"], "value": val, "n": r.get("n"),
                    "qoq": fmt_pct(r.get("qoq_pct")) if st != "hidden" else "",
                    "yoy": fmt_pct(r.get("yoy_pct")) if st != "hidden" else "",
                    "qoq_sign": _sign(r.get("qoq_pct")), "yoy_sign": _sign(r.get("yoy_pct")),
                    "lfl": (fmt_pct(lmap[r["name"]]["mean_pct"]) + ("*" if lmap[r["name"]]["status"] == "thin" else ""))
                    if r["name"] in lmap and st != "hidden" else ""})
    return {"rows": out, "has_q": has_q, "has_y": has_y, "has_lfl": bool(lmap), "unit": block["unit"]}


def _sign(v):
    return "" if v is None or v == 0 else ("up" if v > 0 else "down")


def cite(text: str, order: dict, news: dict) -> str:
    """Escape, then turn [n03] into superscripts numbered per source article, in reading order."""
    t = html.escape(text)

    def sub(m):
        url = news.get(m.group(1), {}).get("url", m.group(1))
        if url not in order:
            order[url] = len(order) + 1
        return f'<sup class="cite">{order[url]}</sup>'
    t = re.sub(r"\[(n\d{2})\]", sub, t)
    return re.sub(r'(<sup class="cite">(\d+)</sup>)(<sup class="cite">\2</sup>)+', r"\1", t)


def line_chart(series: list[dict], w=700, h=250) -> str:
    """Single-series line, hand-built SVG for print: 2px line, hairline grid, end labels."""
    if not series:
        return ""
    xs = [s["quarter"] for s in series]
    ys = [s["value"] for s in series]
    lo, hi = min(ys + [100]), max(ys)
    step = 10
    lo, hi = step * (int(lo // step)), step * (int(hi // step) + 1)
    L, R, T, B = 40, 16, 22, 30
    X = lambda i: L + i * (w - L - R) / max(1, len(xs) - 1)          # noqa: E731
    Y = lambda v: T + (hi - v) * (h - T - B) / (hi - lo)              # noqa: E731
    g = [f'<svg viewBox="0 0 {w} {h}" class="chart" role="img" aria-label="Uy-joy narxlari indeksi">']
    for v in range(lo, hi + 1, step):
        g.append(f'<line x1="{L}" x2="{w - R}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="{C["grid"]}" stroke-width="1"/>')
        g.append(f'<text x="{L - 8}" y="{Y(v) + 4:.1f}" text-anchor="end" class="tick">{v}</text>')
    for i, q in enumerate(xs):
        p = pd.Period(q, "Q")
        if p.quarter in (1,) or i == 0 or i == len(xs) - 1:
            lab = f"{p.year}-Ch{p.quarter}"
            anchor = "start" if i == 0 else ("end" if i == len(xs) - 1 else "middle")
            g.append(f'<text x="{X(i):.1f}" y="{h - 12}" text-anchor="{anchor}" class="tick">{lab}</text>')
    pts = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(ys))
    g.append(f'<polyline points="{pts}" fill="none" stroke="{C["blue"]}" stroke-width="2" stroke-linejoin="round"/>')
    for i in (0, len(ys) - 1):
        g.append(f'<circle cx="{X(i):.1f}" cy="{Y(ys[i]):.1f}" r="4" fill="{C["blue"]}" stroke="{C["surface"]}" stroke-width="2"/>')
        anchor = "start" if i == 0 else "end"
        dx = 6 if i == 0 else -6
        g.append(f'<text x="{X(i) + dx:.1f}" y="{Y(ys[i]) - 10:.1f}" text-anchor="{anchor}" class="label">{ys[i]:.1f}</text>')
    g.append("</svg>")
    return "".join(g)


def bar_chart(rows: list[dict], w=640) -> str:
    """Horizontal bars, single hue, sorted; thin cells lighter and starred; hidden cells left out."""
    rows = sorted([r for r in rows if r.get("value") is not None], key=lambda r: -r["value"])
    if not rows:
        return ""
    bh, gap, L, R, T = 16, 6, 132, 48, 6
    h = T + len(rows) * (bh + gap) + 6
    vmax = max(r["value"] for r in rows)
    Wb = lambda v: (w - L - R) * v / vmax                          # noqa: E731
    g = [f'<svg viewBox="0 0 {w} {h}" class="chart" role="img" aria-label="Ijara rentabelligi">']
    g.append(f'<line x1="{L}" x2="{L}" y1="{T - 2}" y2="{h - 4}" stroke="{C["axis"]}" stroke-width="1"/>')
    for i, r in enumerate(rows):
        y = T + i * (bh + gap)
        thin = r.get("status") == "thin"
        fill = C["blue_light"] if thin else C["blue"]
        bw = Wb(r["value"])
        g.append(f'<path d="M{L},{y} h{bw - 4:.1f} a4,4 0 0 1 4,4 v{bh - 8} a4,4 0 0 1 -4,4 h-{bw - 4:.1f} z" fill="{fill}"/>')
        g.append(f'<text x="{L - 8}" y="{y + bh - 4}" text-anchor="end" class="cat">{html.escape(r["name"])}</text>')
        g.append(f'<text x="{L + bw + 6:.1f}" y="{y + bh - 4}" class="label">{r["value"]:.1f}%{"*" if thin else ""}</text>')
    g.append("</svg>")
    return "".join(g)


def render(run_dir: Path, scope: str) -> Path:
    facts = json.loads((run_dir / "facts.json").read_text(encoding="utf-8"))
    draft = json.loads((run_dir / "draft.json").read_text(encoding="utf-8"))
    news = {n["id"]: n for n in json.loads((run_dir / "news.json").read_text(encoding="utf-8"))}
    method = yaml.safe_load((CONFIG_DIR / "method.yaml").read_text(encoding="utf-8"))
    order: dict[str, int] = {}
    reading = ["asosiy_xulosalar", "birlamchi", "ikkilamchi", "ijara", "rentabellik", "indeks", "bozor_sharhi"]
    keys = [k for k in reading if k in draft] + [k for k in draft if k not in reading]
    text = {sec: {k: cite(v, order, news) for k, v in draft[sec]["slots"].items()} for sec in keys}
    rep = facts["report"]
    lfl_q = (facts.get("solishtirma") or {}).get("qoq", {})
    ctx = {
        "scope": scope, "period": rep["period"], "period_uz": period_uz(rep["period"]),
        "col": col_label(rep["period"]), "rep": rep, "text": text, "method": method,
        "partial": rep.get("partial_families", []),
        "t": {k: table(facts[k], 2 if k != "ijara" else 1, lfl_q.get(k)) for k in ("birlamchi", "ikkilamchi", "ijara")
              if k in facts},
        "brk": rep.get("series_break"),
        "brk_tash": bool(rep.get("series_break")) and any(f.startswith("tashkent") for f in rep["series_break"].get("families", [])),
        "lfl_summary": [{"label": lab, "avg": fmt_pct(facts[k].get("avg_qoq_pct")),
                         "som": fmt_pct(lfl_q[k][0]["mean_pct"]), "usd": fmt_pct(lfl_q[k][0]["mean_usd_pct"]),
                         "n": lfl_q[k][0]["n"]}
                        for k, lab in (("birlamchi", "Birlamchi bozor"), ("ikkilamchi", "Ikkilamchi bozor"),
                                       ("ijara", "Ijara")) if lfl_q.get(k) and lfl_q[k][0]["name"] == "Respublika"],
        "tt": {k: table(v, 2 if k != "ijara" else 1) for k, v in facts.get("toshkent_tumanlari", {}).items()},
        "index_svg": line_chart(facts.get("uy_joy_indeksi", {}).get("series", [])),
        "index": facts.get("uy_joy_indeksi", {}),
        "yield_svg": bar_chart(facts.get("ijara_rentabelligi", {}).get("rows", [])),
        "sources": [{"no": i, **next(n for n in news.values() if n["url"] == u)}
                    for u, i in sorted(order.items(), key=lambda x: x[1])],
        "partial_months": {f: rep["months_present"].get(f, []) for f in rep.get("partial_families", [])},
    }
    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html"]))
    out_html = run_dir / "report.html"
    out_html.write_text(env.get_template(f"{scope}.html").render(**ctx), encoding="utf-8")
    out_pdf = run_dir / "report.pdf"
    from playwright.sync_api import sync_playwright  # noqa: PLC0415
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        pg.goto(out_html.resolve().as_uri())
        pg.pdf(path=str(out_pdf), format="A4", print_background=True,
               margin={"top": "14mm", "bottom": "16mm", "left": "14mm", "right": "14mm"},
               display_header_footer=True, header_template="<span></span>",
               footer_template='<div style="font-size:8px;width:100%;text-align:center;color:#52514e;'
                               'font-family:Carlito,sans-serif"><span class="pageNumber"></span></div>')
        b.close()
    return out_pdf
