"""Build assets/geo/tashkent_districts.json (SVG paths of Tashkent city's districts) from geoBoundaries.

    python tools/build_geo_tashkent.py [path/to/geoBoundaries-UZB-ADM2_simplified.geojson]

Without a path the file is downloaded from the geoBoundaries GitHub release (gbOpen, CC BY 4.0).
The boundaries are the 11 districts before Yangihayot was split off, which matches the data
(Yangihayot listings are counted in Sergeli).
"""
from __future__ import annotations

import json
import math
import sys
import urllib.request
from pathlib import Path

URL = ("https://media.githubusercontent.com/media/wmgeolab/geoBoundaries/main/releaseData/gbOpen/UZB/ADM2/"
       "geoBoundaries-UZB-ADM2_simplified.geojson")
NAMES = {"Bektemir": "Bektemir", "Chilanzar": "Chilonzor", "Mirabad": "Mirobod", "Mirzo Ulugbek": "Mirzo Ulugʻbek",
         "Almazar": "Olmazor", "Sergeli": "Sergeli", "Shaykhantokhur": "Shayxontohur", "Uchtepa": "Uchtepa",
         "Yakkasaray": "Yakkasaroy", "Yashnobod": "Yashnobod", "Yunusabad": "Yunusobod"}
OUT = Path(__file__).resolve().parents[1] / "assets" / "geo" / "tashkent_districts.json"
W = 600.0


def rings(geom):
    if geom["type"] == "Polygon":
        return geom["coordinates"]
    return [r for poly in geom["coordinates"] for r in poly]


def main(src: str | None) -> None:
    if src:
        data = json.loads(Path(src).read_text(encoding="utf-8"))
    else:
        with urllib.request.urlopen(URL) as r:
            data = json.loads(r.read().decode("utf-8"))
    feats = {NAMES[f["properties"]["shapeName"]]: f["geometry"] for f in data["features"]
             if f["properties"]["shapeName"] in NAMES}
    missing = set(NAMES.values()) - set(feats)
    if missing:
        raise SystemExit(f"not found: {sorted(missing)}")
    pts = [p for g in feats.values() for ring in rings(g) for p in ring]
    lon0, lon1 = min(p[0] for p in pts), max(p[0] for p in pts)
    lat0, lat1 = min(p[1] for p in pts), max(p[1] for p in pts)
    k = math.cos(math.radians((lat0 + lat1) / 2))
    scale = W / ((lon1 - lon0) * k)
    H = (lat1 - lat0) * scale

    def xy(p):
        return (p[0] - lon0) * k * scale, (lat1 - p[1]) * scale
    out = {"viewBox": [0, 0, round(W, 1), round(H, 1)], "attribution": "Chegaralar: geoBoundaries (gbOpen, CC BY 4.0)",
           "regions": {}}
    for name, g in feats.items():
        parts, xs, ys, area, cx, cy = [], [], [], 0.0, 0.0, 0.0
        for ring in rings(g):
            q = [xy(p) for p in ring]
            parts.append("M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in q) + "Z")
            xs += [x for x, _ in q]
            ys += [y for _, y in q]
            for (x1, y1), (x2, y2) in zip(q, q[1:] + q[:1]):
                c = x1 * y2 - x2 * y1
                area += c
                cx += (x1 + x2) * c
                cy += (y1 + y2) * c
        out["regions"][name] = {"d": "".join(parts), "cx": round(cx / (3 * area), 1), "cy": round(cy / (3 * area), 1),
                                "bbox": [round(min(xs), 1), round(min(ys), 1), round(max(xs), 1), round(max(ys), 1)]}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {OUT} ({len(out['regions'])} districts)")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
