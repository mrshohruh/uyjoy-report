"""Fetch the CBU USD/UZS rate in effect on each quarter's last day from cbu.uz.

The archive endpoint returns the rate in force on the requested date; its `Date`
field is the day that rate was set (e.g. the last working day before a holiday).
"""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

import pandas as pd

URL = "https://cbu.uz/uz/arkhiv-kursov-valyut/json/USD/{date}/"


def fetch_rate(date: str) -> tuple[float, str]:
    with urllib.request.urlopen(URL.format(date=date), timeout=30) as r:
        data = json.loads(r.read().decode("utf-8"))
    row = data[0] if isinstance(data, list) else data
    return float(row["Rate"]), row["Date"]


def update_csv(csv_path: Path, quarters: list[str], overwrite: bool = False) -> pd.DataFrame:
    cur = pd.read_csv(csv_path, dtype={"period": str})
    have = set(cur.period)
    new = []
    for q in quarters:
        if q in have and not overwrite:
            continue
        end = pd.Period(q, "Q").end_time.strftime("%Y-%m-%d")
        rate, set_on = fetch_rate(end)
        new.append({"period": q, "rate": rate,
                    "source": f"cbu.uz archive: rate in force on {end} (set {set_on})"})
    if new:
        cur = cur[~cur.period.isin([r["period"] for r in new])]
        cur = pd.concat([cur, pd.DataFrame(new)], ignore_index=True)
        cur = cur.sort_values("period", key=lambda s: s.map(lambda x: pd.Period(x, "Q")))
        cur.to_csv(csv_path, index=False)
    return pd.DataFrame(new)
