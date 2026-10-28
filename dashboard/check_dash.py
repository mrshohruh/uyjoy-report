"""Open the dashboard, step through every period, market and view, and compare what it shows
with dashboard_data.json (which itself is checked against the agent's facts for 2026-Q3)."""
import asyncio, json, pathlib, sys
from playwright.async_api import async_playwright

ROOT = pathlib.Path(__file__).parent
D = json.loads((ROOT / "dashboard_data.json").read_text(encoding="utf-8"))
MK = ["primary", "secondary", "rent"]
DEC = {"primary": 2, "secondary": 2, "rent": 1}


def pct(v):
    return "—" if v is None else ("+" if v > 0 else "") + f"{v:.1f}%".replace("-0.0%", "0.0%")


def expect_row(kind, p, m, name):
    P = D["data"][kind][p]
    r = P["regions"][m][name]
    s = P["same"][m].get(name)
    y = P["yield"].get(name)
    star = r and r["s"] == "thin"
    price = "—" if not r or r["v"] is None else f"{r['v']:.{DEC[m]}f}" + ("*" if star else "")
    dq = "—" if not r or r["dq"] is None else pct(r["dq"])
    row = [name, price, dq]
    if kind != "Y":
        row.append("—" if not r or r["dy"] is None else pct(r["dy"]))
    row.append(pct(r["dq_usd"]) if r else "—")
    row.append("—" if not s or s["uzs"] is None else pct(s["uzs"]) + ("*" if s["s"] == "thin" else ""))
    row.append("—" if not r else f"{r['n']:,}".replace(",", " "))
    row.append("—" if not y or y["v"] is None else f"{y['v']:.1f}%" + ("*" if y["s"] == "thin" else ""))
    return row


async def main(page_path):
    bad, checked = [], 0
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        pg = await b.new_page(viewport={"width": 1280, "height": 900})
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        await pg.goto("file://" + str(page_path))
        await pg.wait_for_function("window.__REPORT_READY === true")
        await pg.click("#mapTableBtn")
        for kind in ("M", "Q", "Y"):
            for p in D["periods"][kind]:
                for m in MK:
                    await pg.evaluate(f"""() => {{ const d = window.__DASH; d.state.kind = "{kind}"; d.state.market = "{m}";
                                          d.state.metric = "dq"; d.selectPeriod("{p}"); }}""")
                    rows = await pg.eval_on_selector_all("#mapTable tbody tr", "rs => rs.map(r => [...r.children].map(c => c.textContent.trim()))")
                    for r in rows:
                        want = expect_row(kind, p, m, r[0])
                        checked += len(want) - 1
                        if r != want:
                            bad.append(f"{kind} {p} {m}: page {r} vs data {want}")
                    # district tiles: price view
                    tiles = await pg.eval_on_selector_all("#tiles .tile", "ts => ts.map(t => [t.querySelector('.tn').firstChild.textContent.trim(), t.querySelector('.tv').textContent.trim()])")
                    for name, v in tiles:
                        d = D["data"][kind][p]["districts"][m][name]
                        key = {"price": "v"}.get(await pg.evaluate("window.__DASH.state.dmetric"), "v")
                        want = "—" if not d or d[key] is None else f"{d[key]:.{DEC[m]}f}" + ("*" if d["s"] == "thin" else "")
                        checked += 1
                        if v != want:
                            bad.append(f"{kind} {p} {m} district {name}: page {v} vs data {want}")
        await b.close()
    print(f"checked {checked} values across {sum(len(v) for v in D['periods'].values())} periods; mismatches {len(bad)}; page errors {len(errs)}")
    for x in bad[:20]:
        print("  ", x)
    for e in errs[:5]:
        print("  error:", e)
    return not bad and not errs


sys.exit(0 if asyncio.run(main(pathlib.Path(sys.argv[1]).resolve())) else 1)
