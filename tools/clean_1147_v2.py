"""Clean raw regional rent (category 1147) exports with the pre-July-2026 rules.

Earlier rules (found exactly on 2025 files): price 100..1500 USD, one row per listing id per
month (earliest date), description lowercased with everything but a-z, а-я, 0-9 and space removed,
then "  " deleted. Earlier raw exports were already limited to area 25..200 m² and 4+ floors; the
new exports are not, so those limits are applied here too. Output uses the earlier files' column
order and types (pass one earlier cleaned file as --schema).

New rules (from July 2026, for reference; reproduced exactly): per region, drop outliers beyond
1.5 x IQR on total_area, then price, then price_sqrm; then price <= 800.
"""
# Output names follow YYYY-MM_<type>.parquet, so the output folder can be the project's data/parquet/.
import re, sys, json
from pathlib import Path
import pandas as pd
import pyarrow as pa, pyarrow.parquet as pq

NON = re.compile(r"[^a-zа-я0-9 ]")
BR = re.compile(r"<br\s*/?>")


def norm(t):
    if t is None or t is pd.NA:
        return t
    return NON.sub("", BR.sub("", t).lower()).replace("  ", "")


def clean_old(df):
    steps = {"raw": len(df)}
    df = df[df.total_area.between(25, 200) & (df.total_floors >= 4)]
    steps["area/floors_out"] = steps["raw"] - len(df)
    n = len(df); df = df[df.price.between(100, 1500)]; steps["price_out"] = n - len(df)
    n = len(df)
    df = (df.assign(_d=pd.to_datetime(df.sana), _o=range(len(df)))
            .sort_values(["_d", "last_refresh_time", "_o"], kind="stable").drop_duplicates("id")
            .drop(columns=["_d", "_o"]).reset_index(drop=True))
    steps["dup_out"] = n - len(df)
    df["description"] = df["description"].map(norm).astype("string")
    steps["kept"] = len(df)
    return df, steps


if __name__ == "__main__":
    schema = pq.read_schema(sys.argv[1]); out = Path(sys.argv[2]); out.mkdir(parents=True, exist_ok=True); log = {}
    for f in sys.argv[3:]:
        month = re.search(r"(20\d\d-\d\d)\.parquet$", f).group(1)
        raw = pd.read_parquet(f)
        assert (raw.yil.astype(int).astype(str) + "-" + raw.oy.astype(int).astype(str).str.zfill(2) == month).all()
        df, steps = clean_old(raw)
        tbl = pa.Table.from_pandas(df[schema.names], preserve_index=False).cast(schema)
        pq.write_table(tbl, out / f"{month}_1147regions.parquet")
        log[month] = steps; print(month, steps)
    (out / "cleaning_log.json").write_text(json.dumps(log, indent=1))
