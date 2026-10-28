"""Assemble the dashboard page: styles, computed data and map shapes go into one HTML file."""
import json, pathlib, sys
ROOT = pathlib.Path(__file__).parent
pending = sys.argv[1] if len(sys.argv) > 1 else "null"   # e.g. '["2026-07","2026-08","2026-09"]'
tpl = (ROOT / "template.html").read_text(encoding="utf-8")
data = json.dumps(json.loads((ROOT / "dashboard_data.json").read_text(encoding="utf-8")), ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
geo = json.dumps(json.loads((ROOT / "geo_uz.json").read_text(encoding="utf-8")), ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
page = (tpl.replace("/*__BASE_CSS__*/", (ROOT / "base.css").read_text(encoding="utf-8"))
           .replace("/*__DATA__*/", data).replace("/*__GEO__*/", geo).replace("/*__PENDING__*/null", pending))
(ROOT / "out").mkdir(exist_ok=True)
(ROOT / "out" / "uyjoy-monitor.html").write_text(page, encoding="utf-8")
site = '<!doctype html>\n<html lang="uz"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n' + page + "\n</html>"
(ROOT / "out" / "uyjoy-monitor-sayt-uchun.html").write_text(site, encoding="utf-8")
print("built", len(page), "bytes")
