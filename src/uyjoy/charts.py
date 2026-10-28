"""Hand-built SVG charts and maps for the printed report.

Every chart takes plain numbers that come from facts.json (nothing is typed in by hand) and returns an
SVG string. One visual system throughout:

- each market keeps one colour (birlamchi blue, ikkilamchi amber, ijara teal);
- changes use a colour-blind-safe diverging ramp (orange = fall, blue = rise) with fixed steps, so the
  same colour means the same size of change on every map and heatmap;
- levels use a single-hue blue ramp;
- thin cells (10-29 listings) are hatched, hidden or missing cells are dotted grey;
- 1px hairline grid, direct labels instead of legends wherever possible.
"""
from __future__ import annotations

import html
import json
import math
from functools import lru_cache
from pathlib import Path

from .config import ROOT

GEO = ROOT / "assets" / "geo"

INK, INK2, INK3 = "#17202c", "#4d5868", "#8a93a0"
GRID, AXIS, PAPER = "#e3e6ea", "#c2c8d0", "#ffffff"
NODATA, NODATA_DOT = "#eef0f2", "#c9ced5"
MARKET = {"birlamchi": "#2463b4", "ikkilamchi": "#d68a1f", "ijara": "#1a8f80", "sotuv": "#5b6b7f"}
MARKET_LIGHT = {"birlamchi": "#b9cfea", "ikkilamchi": "#f1d3a6", "ijara": "#b3ddd6"}
ACCENT, ACCENT_DARK = "#2463b4", "#173f78"
# change ramp (%), 7 steps
DIV = ["#b4501f", "#e08a4f", "#f5c8a8", "#eef0f2", "#bcd3ec", "#6d9fd6", "#24589f"]
DIV_EDGES = [-5, -2, -0.5, 0.5, 2, 5]
SEQ = ["#e6eef8", "#c4d7ee", "#93b6e0", "#5f8fcd", "#3369b0", "#173f78"]

FONT = "Carlito, 'DejaVu Sans', sans-serif"


def esc(s) -> str:
    return html.escape(str(s))


def fnum(v, nd=1, sign=False) -> str:
    if v is None:
        return "—"
    s = f"{v:+.{nd}f}" if sign else f"{v:.{nd}f}"
    if abs(v) >= 1000 and nd == 0:
        s = f"{v:,.0f}".replace(",", " ")
        if sign and v > 0:
            s = "+" + s
    return s.replace("-", "−")


def div_color(v) -> str:
    if v is None:
        return NODATA
    for i, e in enumerate(DIV_EDGES):
        if v < e:
            return DIV[i]
    return DIV[-1]


def ink_on(fill: str) -> str:
    """Dark or light label colour for a fill."""
    h = fill.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return "#ffffff" if lum < 0.5 else INK


def seq_scale(values, n=len(SEQ)):
    """Quantile bins, so one very high value (Tashkent) does not wash out every other region."""
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return lambda v: NODATA, []
    lo, hi = vals[0], vals[-1]
    if hi == lo:
        hi = lo + 1
    k = min(n, len(vals))
    edges = []
    for i in range(1, k):
        e = vals[min(len(vals) - 1, round(i * len(vals) / k))]
        if not edges or e > edges[-1]:
            edges.append(e)
    cols = SEQ if len(edges) + 1 >= len(SEQ) else SEQ[len(SEQ) - len(edges) - 1:]

    def f(v):
        if v is None:
            return NODATA
        for i, e in enumerate(edges):
            if v < e:
                return cols[i]
        return cols[len(edges)]
    f.colors = cols
    return f, [lo, *edges, hi]


def _svg(w, h, body, label="") -> str:
    return (f'<svg viewBox="0 0 {w:.0f} {h:.0f}" class="chart" role="img" aria-label="{esc(label)}" '
            f'xmlns="http://www.w3.org/2000/svg" font-family="{FONT}">{_defs()}{body}</svg>')


def _defs() -> str:
    return ('<defs><pattern id="hatch" patternUnits="userSpaceOnUse" width="6" height="6" '
            'patternTransform="rotate(45)"><rect width="6" height="6" fill="none"/>'
            f'<rect width="1.6" height="6" fill="{INK}" fill-opacity=".28"/></pattern>'
            '<pattern id="nodots" patternUnits="userSpaceOnUse" width="6" height="6">'
            f'<rect width="6" height="6" fill="{NODATA}"/><circle cx="3" cy="3" r="1" fill="{NODATA_DOT}"/></pattern></defs>')


def _t(x, y, s, size=11, fill=INK, anchor="start", weight=400, extra="") -> str:
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{fill}" text-anchor="{anchor}" '
            f'font-weight="{weight}" {extra}>{esc(s)}</text>')


def nice_ticks(lo, hi, n=5):
    if hi <= lo:
        hi = lo + 1
    raw = (hi - lo) / n
    mag = 10 ** math.floor(math.log10(raw))
    step = min((s * mag for s in (1, 2, 2.5, 5, 10) if s * mag >= raw), default=10 * mag)
    a = math.floor(lo / step) * step
    b = math.ceil(hi / step) * step
    ticks, v = [], a
    while v <= b + step * 1e-6:
        ticks.append(round(v, 10))
        v += step
    return ticks


def qlabel(q: str, short=False) -> str:
    y, n = q[:4], q[-1]
    return f"{n}-ch {y[2:]}" if short else f"{y}-Ch{n}"


# ---------------------------------------------------------------- legends

def div_legend(x, y, title="Δ chorak, %", w=260, k=1.0) -> str:
    labels = ["−5", "−2", "−0,5", "+0,5", "+2", "+5"]
    sw = w / len(DIV)
    out = [_t(x, y - 6 * k, title, 10 * k, INK2)]
    for i, c in enumerate(DIV):
        out.append(f'<rect x="{x + i * sw:.1f}" y="{y}" width="{sw - 1:.1f}" height="{9 * k:.1f}" fill="{c}"/>')
    for i, lab in enumerate(labels):
        out.append(_t(x + (i + 1) * sw - 0.5, y + 21 * k, lab, 9 * k, INK2, "middle"))
    return "".join(out)


def seq_legend(x, y, edges, title, nd=1, w=260, k=1.0, colors=None) -> str:
    colors = colors or SEQ
    sw = w / len(colors)
    out = [_t(x, y - 6 * k, title, 10 * k, INK2)]
    for i, c in enumerate(colors):
        out.append(f'<rect x="{x + i * sw:.1f}" y="{y}" width="{sw - 1:.1f}" height="{9 * k:.1f}" fill="{c}"/>')
    inner = list(range(1, len(edges) - 1))
    if len(inner) > 3:
        inner = inner[1::2]
    for i in inner:
        out.append(_t(x + i * sw - 0.5, y + 21 * k, fnum(edges[i], nd), 8.5 * k, INK2, "middle"))
    out.append(_t(x, y + 21 * k, fnum(edges[0], nd), 8.5 * k, INK3, "start"))
    out.append(_t(x + w, y + 21 * k, fnum(edges[-1], nd), 8.5 * k, INK3, "end"))
    return "".join(out)


def status_legend(x, y, k=1.0) -> str:
    s = 12 * k
    return (f'<rect x="{x}" y="{y}" width="{s:.1f}" height="{9 * k:.1f}" fill="{NODATA}"/><rect x="{x}" y="{y}" width="{s:.1f}" '
            f'height="{9 * k:.1f}" fill="url(#hatch)"/>{_t(x + s + 4 * k, y + 8 * k, "eʼlonlar kam (10–29)", 9 * k, INK2)}'
            f'<rect x="{x}" y="{y + 15 * k:.1f}" width="{s:.1f}" height="{9 * k:.1f}" fill="url(#nodots)"/>'
            f'{_t(x + s + 4 * k, y + 23 * k, "maʼlumot yetarli emas", 9 * k, INK2)}')


# ---------------------------------------------------------------- maps

@lru_cache(maxsize=4)
def geo(name: str) -> dict:
    return json.loads((GEO / name).read_text(encoding="utf-8"))


REGION_LABEL_SHIFT = {"Qoraqalpogʻiston": (10, 30), "Navoiy": (-20, 15), "Jizzax": (14, -22), "Surxondaryo": (6, 0),
                      "Samarqand": (-30, 8), "Xorazm": (-4, 4)}
# eastern regions are too small for an inside label: they get a callout in a column to the right
CALLOUTS = ["Toshkent shahri", "Toshkent viloyati", "Namangan", "Andijon", "Fargʻona", "Sirdaryo"]
SHORT = {"Toshkent viloyati": "Toshkent vil.", "Toshkent shahri": "Toshkent sh.", "Qoraqalpogʻiston": "Qoraqalpogʻiston"}


def choropleth(values: dict, mode: str = "div", title: str = "", fmt_nd: int = 1, sign: bool = True,
               file: str = "uz_regions.json", label_names: bool = True, legend: str = "", **_) -> str:
    """values: name -> {"value": x, "status": "ok"|"thin"|"hidden"|"missing"}."""
    g = geo(file)
    _, _, w, h = g["viewBox"]
    country = file == "uz_regions.json"
    k = 2.9 if country else 1.95          # text scale: the map is drawn ~2.5x (country) / 1.5x smaller than its units
    extra_w = 190 if country else 0
    W = w + extra_w
    if mode == "div":
        col, edges, cols = div_color, None, DIV
    else:
        col, edges = seq_scale([v.get("value") for v in values.values() if v.get("status") in ("ok", "thin")])
        cols = getattr(col, "colors", SEQ)
    body = []
    names = [n for n in g["regions"] if n != "Toshkent shahri"] + (["Toshkent shahri"] if "Toshkent shahri" in g["regions"] else [])

    def cell(n):
        v = values.get(n, {})
        st = v.get("status", "missing")
        val = v.get("value") if st in ("ok", "thin") else None
        return val, st

    for n in names:
        if country and n == "Toshkent shahri":
            continue
        r = g["regions"][n]
        val, st = cell(n)
        if val is None:
            body.append(f'<path d="{r["d"]}" fill="url(#nodots)" stroke="#ffffff" stroke-width="1.4"/>')
        else:
            body.append(f'<path d="{r["d"]}" fill="{col(val)}" stroke="#ffffff" stroke-width="1.4"/>')
            if st == "thin":
                body.append(f'<path d="{r["d"]}" fill="url(#hatch)" stroke="none"/>')
    halo = 'stroke="#ffffff" stroke-width="{:.1f}" paint-order="stroke" stroke-linejoin="round"'.format(3.2 * k)

    def label(n, val, st):
        return (fnum(val, fmt_nd, sign) + ("*" if st == "thin" else "")) if val is not None else "—"

    if country:
        c = g["regions"]["Toshkent shahri"]
        val, st = cell("Toshkent shahri")
        body.append(f'<circle cx="{c["cx"]}" cy="{c["cy"]}" r="13" fill="{col(val) if val is not None else NODATA}" '
                    f'stroke="{INK}" stroke-width="1.6"/>')
        # callout column
        x_lab = w + 22
        y0, step = 150, 66
        for i, n in enumerate(CALLOUTS):
            r = g["regions"][n]
            val, st = cell(n)
            ly = y0 + i * step
            ax, ay = (r["cx"], r["cy"])
            if n == "Toshkent shahri":
                ax += 13
            body.append(f'<polyline points="{ax:.1f},{ay:.1f} {w - 4:.1f},{ly - 8:.1f} {x_lab - 6:.1f},{ly - 8:.1f}" fill="none" '
                        f'stroke="{INK3}" stroke-width="1.1"/>')
            body.append(f'<circle cx="{ax:.1f}" cy="{ay:.1f}" r="3.2" fill="{INK}"/>')
            body.append(_t(x_lab, ly - 12, SHORT.get(n, n), 8.6 * k, INK2))
            body.append(_t(x_lab, ly + 0.9 * 10 * k - 8, label(n, val, st), 10.5 * k, INK, "start", 700))
    for n in names:
        if country and n in CALLOUTS:
            continue
        r = g["regions"][n]
        val, st = cell(n)
        dx, dy = REGION_LABEL_SHIFT.get(n, (0, 0)) if country else (0, 0)
        cx, cy = r["cx"] + dx, r["cy"] + dy
        if label_names:
            body.append(_t(cx, cy - 2, SHORT.get(n, n), 8.2 * k, INK2, "middle", 400, halo))
            body.append(_t(cx, cy + 9.6 * k, label(n, val, st), 10.2 * k, INK, "middle", 700, halo))
        else:
            body.append(_t(cx, cy + 4 * k, label(n, val, st), 10.2 * k, INK, "middle", 700, halo))
    ly = h + 20 * k
    lw = min(W * 0.46, 120 * k)
    if mode == "div":
        body.append(div_legend(4, ly, legend or "Δ chorak, %", lw, k))
    else:
        body.append(seq_legend(4, ly, edges, legend, fmt_nd, lw, k, cols))
    body.append(status_legend(W - 112 * k, ly - 4 * k, k))
    return _svg(W, h + 40 * k, "".join(body), title)


# ---------------------------------------------------------------- small pieces

def sparkline(values, w=78, h=20, color=ACCENT, statuses=None) -> str:
    pts = [(i, v) for i, v in enumerate(values) if v is not None]
    if len(pts) < 2:
        return ""
    lo = min(v for _, v in pts)
    hi = max(v for _, v in pts)
    if hi == lo:
        hi = lo + 1
    n = len(values) - 1
    X = lambda i: 2 + i * (w - 6) / n           # noqa: E731
    Y = lambda v: h - 3 - (v - lo) * (h - 6) / (hi - lo)   # noqa: E731
    segs, cur = [], []
    for i, v in enumerate(values):
        if v is None:
            if len(cur) > 1:
                segs.append(cur)
            cur = []
        else:
            cur.append((X(i), Y(v)))
    if len(cur) > 1:
        segs.append(cur)
    body = "".join(f'<polyline points="{" ".join(f"{x:.1f},{y:.1f}" for x, y in s)}" fill="none" stroke="{color}" '
                   f'stroke-width="1.4" stroke-linejoin="round"/>' for s in segs)
    lx, lv = pts[-1]
    body += f'<circle cx="{X(lx):.1f}" cy="{Y(lv):.1f}" r="2" fill="{color}"/>'
    return f'<svg viewBox="0 0 {w} {h}" class="spark" xmlns="http://www.w3.org/2000/svg">{body}</svg>'


def hbars(rows, w=520, value_nd=1, unit="", color=ACCENT, sort=True, signed=False, ref=None, ref_label="",
          label_w=128, bar_h=15, gap=6, title="", x_min=None) -> str:
    """rows: [{"name", "value", "status"}]; signed bars use the diverging ramp ends."""
    rows = [r for r in rows if r.get("value") is not None and r.get("status") != "hidden"]
    if sort:
        rows = sorted(rows, key=lambda r: -r["value"])
    if not rows:
        return ""
    T = 8
    h = T + len(rows) * (bar_h + gap) + 14
    vmax = max(max(r["value"] for r in rows), ref or 0, 0)
    vmin = min(min(r["value"] for r in rows), 0) if x_min is None else x_min
    L, R = label_w, 52
    span = (vmax - vmin) or 1
    X = lambda v: L + (v - vmin) * (w - L - R) / span    # noqa: E731
    zero = 0 if vmin <= 0 else vmin
    X0 = X(zero)
    out = [f'<line x1="{X0:.1f}" x2="{X0:.1f}" y1="{T - 3}" y2="{h - 10}" stroke="{AXIS}"/>']
    for i, r in enumerate(rows):
        y = T + i * (bar_h + gap)
        v = r["value"]
        thin = r.get("status") == "thin"
        c = r.get("color") or ((DIV[-2] if v >= 0 else DIV[1]) if signed else color)
        x1, x2 = sorted((X0, X(v)))
        out.append(f'<rect x="{x1:.1f}" y="{y}" width="{max(x2 - x1, 1):.1f}" height="{bar_h}" rx="2" fill="{c}"/>')
        if thin:
            out.append(f'<rect x="{x1:.1f}" y="{y}" width="{max(x2 - x1, 1):.1f}" height="{bar_h}" fill="url(#hatch)"/>')
        out.append(_t(L - 8, y + bar_h - 3.5, r["name"], 11, INK, "end", 700 if r.get("bold") else 400))
        lab = fnum(v, value_nd, signed) + unit + ("*" if thin else "")
        out.append(_t(x2 + 5, y + bar_h - 3.5, lab, 11, INK, "start", 700))
    if ref is not None:
        xr = X(ref)
        out.append(f'<line x1="{xr:.1f}" x2="{xr:.1f}" y1="{T - 6}" y2="{h - 10}" stroke="{INK}" stroke-dasharray="3 3"/>')
        out.append(_t(xr + 4, h - 1, ref_label, 9.5, INK2))
    return _svg(w, h + 4, "".join(out), title)


def dumbbell(rows, w=520, nd=2, unit="", color=ACCENT, title="", label_w=96, prev_label="oldingi chorak",
             cur_label="joriy chorak") -> str:
    """rows: [{"name", "prev", "value", "qoq_pct"}] sorted by current value."""
    rows = [r for r in rows if r.get("value") is not None and r.get("prev") is not None]
    rows = sorted(rows, key=lambda r: -r["value"])
    if not rows:
        return ""
    T, rh = 26, 21
    h = T + len(rows) * rh + 22
    lo = min(min(r["prev"], r["value"]) for r in rows)
    hi = max(max(r["prev"], r["value"]) for r in rows)
    ticks = nice_ticks(lo, hi, 5)
    L, R = label_w, 86
    X = lambda v: L + (v - ticks[0]) * (w - L - R) / (ticks[-1] - ticks[0])  # noqa: E731
    out = []
    for t in ticks:
        out.append(f'<line x1="{X(t):.1f}" x2="{X(t):.1f}" y1="{T - 6}" y2="{h - 18}" stroke="{GRID}"/>')
        out.append(_t(X(t), h - 5, fnum(t, 0 if t == int(t) else 1, False), 9.5, INK2, "middle"))
    out.append(f'<circle cx="{L}" cy="9" r="4" fill="#ffffff" stroke="{color}" stroke-width="1.6"/>'
               + _t(L + 8, 12.5, prev_label, 10, INK2)
               + f'<circle cx="{L + 110}" cy="9" r="4.5" fill="{color}"/>' + _t(L + 118, 12.5, cur_label, 10, INK2))
    for i, r in enumerate(rows):
        y = T + i * rh + 6
        a, b = X(r["prev"]), X(r["value"])
        up = r["value"] >= r["prev"]
        out.append(f'<line x1="{L - 2}" x2="{w - R + 4}" y1="{y}" y2="{y}" stroke="{GRID}" stroke-width=".6"/>')
        out.append(f'<line x1="{a:.1f}" x2="{b:.1f}" y1="{y}" y2="{y}" stroke="{DIV[-2] if up else DIV[1]}" stroke-width="3"/>')
        out.append(f'<circle cx="{a:.1f}" cy="{y}" r="4" fill="#ffffff" stroke="{color}" stroke-width="1.6"/>')
        out.append(f'<circle cx="{b:.1f}" cy="{y}" r="4.5" fill="{color}"/>')
        out.append(_t(L - 8, y + 4, r["name"], 11, INK, "end"))
        q = r.get("qoq_pct")
        out.append(_t(w - R + 8, y + 4, fnum(r["value"], nd) + unit, 11, INK, "start", 700))
        if q is not None:
            out.append(_t(w - 2, y + 4, fnum(q, 1, True) + "%", 9.5, DIV[-1] if q > 0 else (DIV[0] if q < 0 else INK2), "end"))
    return _svg(w, h, "".join(out), title)


def heatmap(rows, cols, w=760, title="", label_w=118, cell_h=17, nd=1, show_values=True) -> str:
    """rows: [{"name", "values": [...], "status": [...]}]; diverging colours by value (% change)."""
    two = any("|" in c for c in cols)
    T = 30 if two else 22
    n = len(cols)
    cw = (w - label_w - 4) / n
    h = T + len(rows) * (cell_h + 2) + 4
    out = []
    for j, c in enumerate(cols):
        a, _, b = c.partition("|")
        out.append(_t(label_w + j * cw + cw / 2, 12, a, 9.5, INK2, "middle", 700 if two else 400))
        if b:
            out.append(_t(label_w + j * cw + cw / 2, 24, b, 9, INK3, "middle"))
    for i, r in enumerate(rows):
        y = T + i * (cell_h + 2)
        out.append(_t(label_w - 8, y + cell_h - 4.5, r["name"], 10.5, INK, "end", 700 if r.get("bold") else 400))
        for j, v in enumerate(r["values"]):
            st = (r.get("status") or ["ok"] * n)[j]
            x = label_w + j * cw
            if v is None or st in ("hidden", "missing"):
                out.append(f'<rect x="{x:.1f}" y="{y}" width="{cw - 2:.1f}" height="{cell_h}" fill="url(#nodots)"/>')
                continue
            fill = div_color(v)
            out.append(f'<rect x="{x:.1f}" y="{y}" width="{cw - 2:.1f}" height="{cell_h}" fill="{fill}"/>')
            if st == "thin":
                out.append(f'<rect x="{x:.1f}" y="{y}" width="{cw - 2:.1f}" height="{cell_h}" fill="url(#hatch)"/>')
            if show_values:
                out.append(_t(x + cw / 2 - 1, y + cell_h - 4.5, fnum(v, nd, True), 9.5, ink_on(fill), "middle"))
    return _svg(w, h, "".join(out), title)


def value_heatmap(rows, cols, w=520, title="", label_w=110, cell_h=19, nd=1, unit="") -> str:
    """Level heatmap (single hue): rows [{"name", "cells": [{"value","status"}]}]."""
    vals = [c["value"] for r in rows for c in r["cells"] if c.get("value") is not None]
    col, edges = seq_scale(vals)
    T = 22
    n = len(cols)
    cw = (w - label_w - 4) / n
    h = T + len(rows) * (cell_h + 2) + 48
    out = []
    for j, c in enumerate(cols):
        out.append(_t(label_w + j * cw + cw / 2, 14, c, 10, INK2, "middle", 700))
    for i, r in enumerate(rows):
        y = T + i * (cell_h + 2)
        out.append(_t(label_w - 8, y + cell_h - 5, r["name"], 10.5, INK, "end"))
        for j, c in enumerate(r["cells"]):
            x = label_w + j * cw
            v, st = c.get("value"), c.get("status")
            if v is None or st in ("hidden", "missing"):
                out.append(f'<rect x="{x:.1f}" y="{y}" width="{cw - 2:.1f}" height="{cell_h}" fill="url(#nodots)"/>')
                out.append(_t(x + cw / 2, y + cell_h - 5, "—", 10, INK2, "middle"))
                continue
            fill = col(v)
            out.append(f'<rect x="{x:.1f}" y="{y}" width="{cw - 2:.1f}" height="{cell_h}" fill="{fill}"/>')
            if st == "thin":
                out.append(f'<rect x="{x:.1f}" y="{y}" width="{cw - 2:.1f}" height="{cell_h}" fill="url(#hatch)"/>')
            out.append(_t(x + cw / 2 - 1, y + cell_h - 5, fnum(v, nd) + ("*" if st == "thin" else ""), 10.5,
                          ink_on(fill), "middle", 700))
    out.append(seq_legend(label_w, h - 22, edges, unit, nd, min(260, w - label_w - 10), 1.0, getattr(col, "colors", SEQ)))
    return _svg(w, h, "".join(out), title)


# ---------------------------------------------------------------- line charts

def lines(series, x_labels, w=760, h=260, title="", y_title="", nd=1, unit="", baseline=None, label_every=None,
          end_labels=True, y_min=None, y_max=None, legend=True, area=None, right_pad=None) -> str:
    """series: [{"name", "values", "color", "width", "dash", "bold"}]; x_labels: list of str."""
    allv = [v for s in series for v in s["values"] if v is not None]
    if not allv:
        return ""
    lo, hi = min(allv), max(allv)
    if baseline is not None:
        lo, hi = min(lo, baseline), max(hi, baseline)
    if y_min is not None:
        lo = y_min
    if y_max is not None:
        hi = y_max
    ticks = nice_ticks(lo, hi, 5)
    lw = max(len(s["name"]) for s in series) if end_labels else 0
    L, R = 40, right_pad if right_pad is not None else (min(150, 22 + lw * 6.2) if end_labels else 16)
    T = 30 if legend else 14
    B = 26
    n = len(x_labels)
    X = lambda i: L + i * (w - L - R) / max(1, n - 1)       # noqa: E731
    Y = lambda v: T + (ticks[-1] - v) * (h - T - B) / (ticks[-1] - ticks[0])  # noqa: E731
    out = []
    for t in ticks:
        out.append(f'<line x1="{L}" x2="{w - R}" y1="{Y(t):.1f}" y2="{Y(t):.1f}" stroke="{GRID}"/>')
        out.append(_t(L - 6, Y(t) + 3.5, fnum(t, 0 if float(t).is_integer() else 1), 10, INK2, "end"))
    if y_title:
        out.append(_t(L - 34, T - 12, y_title, 10, INK2))
    if baseline is not None:
        out.append(f'<line x1="{L}" x2="{w - R}" y1="{Y(baseline):.1f}" y2="{Y(baseline):.1f}" stroke="{INK3}" stroke-dasharray="3 3"/>')
    every = label_every or max(1, round(n / 7))
    for i, lab in enumerate(x_labels):
        if i == n - 1 or (i % every == 0 and n - 1 - i >= max(2, every * 0.75)):
            out.append(_t(X(i), h - 8, lab, 9.5, INK2, "end" if i == n - 1 else "middle"))
    if area:
        a, b = area["series"]
        pts_top = [(X(i), Y(v)) for i, v in enumerate(series[a]["values"]) if v is not None]
        pts_bot = [(X(i), Y(v)) for i, v in enumerate(series[b]["values"]) if v is not None][::-1]
        out.append(f'<polygon points="{" ".join(f"{x:.1f},{y:.1f}" for x, y in pts_top + pts_bot)}" '
                   f'fill="{area.get("color", "#dfe8f5")}" fill-opacity=".7"/>')
    lab_y = []
    for s in series:
        pts = [(X(i), Y(v), v) for i, v in enumerate(s["values"]) if v is not None]
        if len(pts) < 2:
            continue
        dash = f' stroke-dasharray="{s["dash"]}"' if s.get("dash") else ""
        out.append(f'<polyline points="{" ".join(f"{x:.1f},{y:.1f}" for x, y, _ in pts)}" fill="none" '
                   f'stroke="{s["color"]}" stroke-width="{s.get("width", 2)}" stroke-linejoin="round"{dash}/>')
        x, y, v = pts[-1]
        out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{3.5 if s.get("bold") else 2.6}" fill="{s["color"]}"/>')
        if end_labels:
            lab_y.append([y, s, v, x])
    # spread end labels so they do not overlap
    lab_y.sort(key=lambda t: t[0])
    for k in range(1, len(lab_y)):
        if lab_y[k][0] - lab_y[k - 1][0] < 12:
            lab_y[k][0] = lab_y[k - 1][0] + 12
    for y, s, v, x in lab_y:
        out.append(_t(x + 7, y + 3.5, f'{s["name"]} {fnum(v, nd)}{unit}', 10.5, s["color"], "start",
                      700 if s.get("bold") else 400))
    if legend and not end_labels:
        lx = L
        for s in series:
            out.append(f'<line x1="{lx}" x2="{lx + 18}" y1="10" y2="10" stroke="{s["color"]}" stroke-width="{s.get("width", 2)}"'
                       + (f' stroke-dasharray="{s["dash"]}"' if s.get("dash") else "") + "/>")
            out.append(_t(lx + 23, 13.5, s["name"], 10.5, INK2))
            lx += 34 + len(s["name"]) * 5.6
    return _svg(w, h, "".join(out), title)


def small_multiples(panels, x_labels, cols=5, w=760, ph=92, title="", nd=2, colors=None, names=None) -> str:
    """panels: [{"name", "series": [values_a, values_b]}]; each panel has its own y range."""
    colors = colors or [MARKET["birlamchi"], MARKET["ikkilamchi"]]
    rows_n = math.ceil(len(panels) / cols)
    gapx, gapy = 14, 16
    pw = (w - gapx * (cols - 1)) / cols
    top = 22
    h = top + rows_n * (ph + gapy)
    out = []
    if names:
        lx = 0
        for nm, c in zip(names, colors):
            out.append(f'<line x1="{lx}" x2="{lx + 16}" y1="9" y2="9" stroke="{c}" stroke-width="2"/>')
            out.append(_t(lx + 21, 12.5, nm, 10.5, INK2))
            lx += 30 + len(nm) * 5.8
    n = len(x_labels)
    for k, p in enumerate(panels):
        cx = (k % cols) * (pw + gapx)
        cy = top + (k // cols) * (ph + gapy)
        vals = [v for s in p["series"] for v in s if v is not None]
        out.append(_t(cx, cy + 10, p["name"], 10.5, INK, "start", 700))
        if not vals:
            out.append(_t(cx, cy + 40, "maʼlumot yetarli emas", 9.5, INK3))
            continue
        lo, hi = min(vals), max(vals)
        padv = (hi - lo) * 0.12 or 0.5
        lo, hi = lo - padv, hi + padv
        T, B = cy + 18, cy + ph - 12
        X = lambda i: cx + 2 + i * (pw - 30) / max(1, n - 1)   # noqa: E731
        Y = lambda v: B - (v - lo) * (B - T) / (hi - lo)         # noqa: E731
        out.append(f'<line x1="{cx}" x2="{cx + pw - 26}" y1="{B}" y2="{B}" stroke="{AXIS}" stroke-width=".8"/>')
        for si, s in enumerate(p["series"]):
            segs, cur = [], []
            for i, v in enumerate(s):
                if v is None:
                    if len(cur) > 1:
                        segs.append(cur)
                    cur = []
                else:
                    cur.append((X(i), Y(v)))
            if len(cur) > 1:
                segs.append(cur)
            for sg in segs:
                out.append(f'<polyline points="{" ".join(f"{x:.1f},{y:.1f}" for x, y in sg)}" fill="none" '
                           f'stroke="{colors[si]}" stroke-width="1.6" stroke-linejoin="round"/>')
            last = next(((i, v) for i, v in reversed(list(enumerate(s))) if v is not None), None)
            if last:
                out.append(f'<circle cx="{X(last[0]):.1f}" cy="{Y(last[1]):.1f}" r="2.2" fill="{colors[si]}"/>')
                out.append(_t(X(last[0]) + 4, Y(last[1]) + 3.5, fnum(last[1], nd), 9, colors[si], "start", 700))
        out.append(_t(cx, B + 10, x_labels[0], 8.5, INK3))
        out.append(_t(cx + pw - 28, B + 10, x_labels[-1], 8.5, INK3, "end"))
    return _svg(w, h, "".join(out), title)


def scatter_yield(points, w=520, h=330, title="", iso=(6, 8, 10), note="") -> str:
    """points: [{"name", "x": sale price mln soʻm/m², "y": rent ming soʻm/m²/month, "status"}]; iso-yield lines."""
    pts = [p for p in points if p.get("x") is not None and p.get("y") is not None]
    if not pts:
        return ""
    xt = nice_ticks(min(p["x"] for p in pts) * 0.96, max(p["x"] for p in pts) * 1.03, 6)
    yt = nice_ticks(min(p["y"] for p in pts) * 0.96, max(p["y"] for p in pts) * 1.03, 6)
    L, R, T, B = 44, 70, 14, 38
    X = lambda v: L + (v - xt[0]) * (w - L - R) / (xt[-1] - xt[0])   # noqa: E731
    Y = lambda v: T + (yt[-1] - v) * (h - T - B) / (yt[-1] - yt[0])  # noqa: E731
    out = []
    for t in xt:
        out.append(f'<line x1="{X(t):.1f}" x2="{X(t):.1f}" y1="{T}" y2="{h - B}" stroke="{GRID}"/>')
        out.append(_t(X(t), h - B + 14, fnum(t, 0), 10, INK2, "middle"))
    for t in yt:
        out.append(f'<line x1="{L}" x2="{w - R}" y1="{Y(t):.1f}" y2="{Y(t):.1f}" stroke="{GRID}"/>')
        out.append(_t(L - 6, Y(t) + 3.5, fnum(t, 0), 10, INK2, "end"))
    out.append(_t((L + w - R) / 2, h - 6, "Sotuv narxi, mln soʻm/m²", 10, INK2, "middle"))
    out.append(f'<text transform="translate(11 {(T + h - B) / 2:.1f}) rotate(-90)" font-size="10" fill="{INK2}" '
               f'text-anchor="middle">Ijara, ming soʻm/m², oyiga</text>')
    for yv in iso:
        # rent (ming) * 12 / (price mln * 1000) = yield% / 100  ->  rent = yield * price * 1000 / 1200
        k = yv * 1000 / 1200
        x1, x2 = xt[0], xt[-1]
        y1, y2 = k * x1, k * x2
        if y2 > yt[-1]:
            x2 = yt[-1] / k
            y2 = yt[-1]
        out.append(f'<line x1="{X(x1):.1f}" y1="{Y(y1):.1f}" x2="{X(x2):.1f}" y2="{Y(y2):.1f}" stroke="{INK3}" stroke-dasharray="4 4"/>')
        out.append(_t(X(x2) + 4, Y(y2) + 4, f"{yv}%", 10, INK2, "start", 700))
    placed = [(X(p["x"]) - 5, Y(p["y"]) - 5, X(p["x"]) + 5, Y(p["y"]) + 5) for p in pts]
    for p in pts:
        thin = p.get("status") == "thin"
        c = ACCENT_DARK if p.get("bold") else MARKET["ijara"]
        out.append(f'<circle cx="{X(p["x"]):.1f}" cy="{Y(p["y"]):.1f}" r="{5.5 if p.get("bold") else 4.5}" fill="{c}" '
                   f'fill-opacity="{0.45 if thin else 0.9}" stroke="#ffffff" stroke-width="1"/>')
    # label the crowded points first, so they get the closest free positions
    def crowd(p):
        return -sum(1 for q in pts if abs(X(q["x"]) - X(p["x"])) < 40 and abs(Y(q["y"]) - Y(p["y"])) < 20)
    for p in sorted(pts, key=crowd):
        px, py = X(p["x"]), Y(p["y"])
        tw = len(p["name"]) * 5.4 + 4
        best = None
        for dx, dy, anchor in ((7, 4, "start"), (-7, 4, "end"), (6, -7, "start"), (6, 15, "start"), (-6, -7, "end"),
                               (-6, 15, "end"), (12, 26, "start"), (-12, -18, "end"), (12, -18, "start"),
                               (-12, 26, "end"), (16, 38, "start"), (-16, -30, "end")):
            x1 = px + dx if anchor == "start" else px + dx - tw
            box = (x1, py + dy - 9, x1 + tw, py + dy + 2)
            if box[0] < L or box[2] > w - 4:
                continue
            if not any(box[0] < b[2] and b[0] < box[2] and box[1] < b[3] and b[1] < box[3] for b in placed):
                best = (dx, dy, anchor, box)
                break
        if best is None:
            best = (7, 4, "start", (px + 7, py - 5, px + 7 + tw, py + 6))
        dx, dy, anchor, box = best
        placed.append(box)
        if abs(dy) > 16:
            out.append(f'<line x1="{px:.1f}" y1="{py:.1f}" x2="{px + dx * 0.8:.1f}" y2="{py + dy - (4 if dy > 0 else -2):.1f}" '
                       f'stroke="{INK3}" stroke-width=".7"/>')
        out.append(_t(px + dx, py + dy, p["name"], 10, INK, anchor, 400,
                      'stroke="#ffffff" stroke-width="3" paint-order="stroke"'))
    return _svg(w, h, "".join(out), title)


def grouped_bars(groups, series_names, colors, w=520, h=240, title="", unit="%", nd=1) -> str:
    """groups: [{"name", "values": [..one per series..]}] vertical grouped bars with signed values."""
    allv = [v for g in groups for v in g["values"] if v is not None] + [0]
    ticks = nice_ticks(min(allv), max(allv), 5)
    L, R, T, B = 36, 8, 34, 30
    widths = [26 + len(nm) * 5.6 for nm in series_names]
    two_rows = sum(widths) + L > w
    if two_rows:
        T += 16
    X0 = L
    gw = (w - L - R) / len(groups)
    bw = min(34, (gw - 24) / len(series_names))
    Y = lambda v: T + (ticks[-1] - v) * (h - T - B) / (ticks[-1] - ticks[0])  # noqa: E731
    out = []
    for t in ticks:
        out.append(f'<line x1="{L}" x2="{w - R}" y1="{Y(t):.1f}" y2="{Y(t):.1f}" stroke="{GRID if t else INK3}"/>')
        out.append(_t(L - 6, Y(t) + 3.5, fnum(t, 0 if float(t).is_integer() else 1), 10, INK2, "end"))
    lx, ly = L, 4
    for nm, c, wd in zip(series_names, colors, widths):
        if two_rows and lx + wd > w:
            lx, ly = L, ly + 16
        out.append(f'<rect x="{lx}" y="{ly}" width="11" height="11" rx="2" fill="{c}"/>')
        out.append(_t(lx + 15, ly + 9.5, nm, 10.5, INK2))
        lx += wd
    for gi, g in enumerate(groups):
        gx = X0 + gi * gw + (gw - bw * len(series_names)) / 2
        for si, v in enumerate(g["values"]):
            if v is None:
                continue
            x = gx + si * bw
            y1, y2 = sorted((Y(0), Y(v)))
            out.append(f'<rect x="{x + 2:.1f}" y="{y1:.1f}" width="{bw - 4:.1f}" height="{max(y2 - y1, 1):.1f}" rx="2" fill="{colors[si]}"/>')
            out.append(_t(x + bw / 2, (y1 - 4) if v >= 0 else (y2 + 12), fnum(v, nd, True), 10, INK, "middle", 700))
        out.append(_t(X0 + gi * gw + gw / 2, h - 10, g["name"], 11, INK, "middle", 700))
    return _svg(w, h, "".join(out), title)


def vbars(labels, values, w=360, h=220, title="", nd=1, color=ACCENT, plan=None, line=None, line_label="",
          line_unit="%", line_color=None) -> str:
    """Vertical bars (e.g. per year); `plan` marks hatched bars; optional line on a right-hand % axis."""
    vals = [v for v in values if v is not None]
    if not vals:
        return ""
    ticks = nice_ticks(0, max(vals) * 1.08, 4)
    L, R, T, B = 40, 40 if line else 10, 24 if line else 12, 26
    n = len(labels)
    bw = (w - L - R) / n
    Y = lambda v: T + (ticks[-1] - v) * (h - T - B) / (ticks[-1] - ticks[0])  # noqa: E731
    out = []
    for t in ticks:
        out.append(f'<line x1="{L}" x2="{w - R}" y1="{Y(t):.1f}" y2="{Y(t):.1f}" stroke="{GRID}"/>')
        out.append(_t(L - 6, Y(t) + 3.5, fnum(t, 0), 10, INK2, "end"))
    for i, (lab, v) in enumerate(zip(labels, values)):
        x = L + i * bw
        if v is not None:
            out.append(f'<rect x="{x + bw * .18:.1f}" y="{Y(v):.1f}" width="{bw * .64:.1f}" height="{Y(0) - Y(v):.1f}" rx="2" '
                       f'fill="{color}" fill-opacity="{0.45 if plan and plan[i] else 1}"/>')
            if plan and plan[i]:
                out.append(f'<rect x="{x + bw * .18:.1f}" y="{Y(v):.1f}" width="{bw * .64:.1f}" height="{Y(0) - Y(v):.1f}" fill="url(#hatch)"/>')
            if line:
                out.append(_t(x + bw / 2, Y(v) + 13, fnum(v, nd), 9.5, "#ffffff", "middle", 700))
            else:
                out.append(_t(x + bw / 2, Y(v) - 4, fnum(v, nd), 9.5, INK, "middle", 700))
        out.append(_t(x + bw / 2, h - 9, lab + (" reja" if plan and plan[i] else ""), 9.5, INK2, "middle"))
    if line:
        lc = line_color or MARKET["ikkilamchi"]
        lv = [v for v in line if v is not None]
        lt = nice_ticks(0, max(lv) * 1.15, 4)
        Y2 = lambda v: T + (lt[-1] - v) * (h - T - B) / (lt[-1] - lt[0])  # noqa: E731
        for t in lt:
            out.append(_t(w - R + 6, Y2(t) + 3.5, fnum(t, 0) + line_unit, 9.5, lc))
        pts = [(L + i * bw + bw / 2, Y2(v), v) for i, v in enumerate(line) if v is not None]
        out.append(f'<polyline points="{" ".join(f"{x:.1f},{y:.1f}" for x, y, _ in pts)}" fill="none" stroke="{lc}" stroke-width="2"/>')
        for x, y, v in pts:
            out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="{lc}"/>')
            out.append(_t(x, y - 7, fnum(v, 0) + line_unit, 9.5, lc, "middle", 700,
                          'stroke="#ffffff" stroke-width="3" paint-order="stroke"'))
        out.append(_t(L, 12, "■ ", 10, color) + _t(L + 10, 12, title.split("|")[0] if "|" in title else "", 10, INK2))
        out.append(f'<line x1="{w - R - 150}" x2="{w - R - 134}" y1="8" y2="8" stroke="{lc}" stroke-width="2"/>'
                   + _t(w - R - 130, 11.5, line_label, 10, INK2))
    return _svg(w, h, "".join(out), title.split("|")[-1])


def stacked_vbars(labels, stacks, names, colors, w=360, h=220, title="", nd=0, total_nd=1, total_div=1000.0,
                  total_unit="") -> str:
    """stacks: list per label of values per component."""
    tots = [sum(v for v in s if v is not None) for s in stacks]
    ticks = nice_ticks(0, max(tots) * 1.1, 4)
    L, R, T, B = 46, 10, 26, 26
    n = len(labels)
    bw = (w - L - R) / n
    Y = lambda v: T + (ticks[-1] - v) * (h - T - B) / (ticks[-1] - ticks[0])  # noqa: E731
    out = []
    for t in ticks:
        out.append(f'<line x1="{L}" x2="{w - R}" y1="{Y(t):.1f}" y2="{Y(t):.1f}" stroke="{GRID}"/>')
        out.append(_t(L - 6, Y(t) + 3.5, fnum(t, 0), 10, INK2, "end"))
    lx = L
    for nm, c in zip(names, colors):
        out.append(f'<rect x="{lx}" y="4" width="11" height="11" rx="2" fill="{c}"/>' + _t(lx + 15, 13.5, nm, 10.5, INK2))
        lx += 26 + len(nm) * 5.6
    for i, (lab, s) in enumerate(zip(labels, stacks)):
        x = L + i * bw + bw * .22
        base = 0
        for v, c in zip(s, colors):
            if v is None:
                continue
            out.append(f'<rect x="{x:.1f}" y="{Y(base + v):.1f}" width="{bw * .56:.1f}" height="{Y(base) - Y(base + v):.1f}" fill="{c}"/>')
            out.append(_t(x + bw * .28, Y(base + v / 2) + 3.5, fnum(v, nd), 9.5, ink_on(c), "middle"))
            base += v
        out.append(_t(x + bw * .28, Y(base) - 5, fnum(base / total_div, total_nd) + total_unit, 10.5, INK, "middle", 700))
        out.append(_t(x + bw * .28, h - 9, lab, 10, INK2, "middle"))
    return _svg(w, h, "".join(out), title)


def kpi_spark(values, w=120, h=30, color=ACCENT) -> str:
    return sparkline(values, w, h, color)
