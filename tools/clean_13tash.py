"""Clean raw Tashkent sale (category 13, Tashkent city) exports with the pre-July-2026 rules.

Earlier rules (approximated from the colleague's cleaned files; no raw file from that period to confirm):
  1. total_area 30..155 m² and price_sqrm >= 0.52 x the month's citywide median
  2. per district, one after another: drop total_area, then price, then price_sqrm outside
     Q1 - 1.5*IQR .. Q3 + 1.5*IQR
  3. one row per listing id (earliest date); description lowercased, everything but a-z, а-я,
     0-9 and space removed (HTML <br> first), then "  " deleted; rows sorted by date
New rules (from July 2026, reproduced exactly on 2026-07): step 2 only, without step 1.
"""
# Output names follow YYYY-MM_<type>.parquet, so the output folder can be the project's data/parquet/.
import re, sys, json
from pathlib import Path
import pandas as pd
import pyarrow as pa, pyarrow.parquet as pq

NON, BR = re.compile(r"[^a-zа-я0-9 ]"), re.compile(r"<br\s*/?>")


def norm(t):
    return t if t is None or t is pd.NA else NON.sub("", BR.sub("", t).lower()).replace("  ", "")


def iqr_keep(d, var, k=1.5):
    g = d.groupby("district")[var]
    q1, q3 = g.transform(lambda s: s.quantile(.25)), g.transform(lambda s: s.quantile(.75))
    i = q3 - q1
    return d[(d[var] >= q1 - k * i) & (d[var] <= q3 + k * i)]


def clean_old(df):
    steps = {"raw": len(df)}
    med = df.price_sqrm.median()
    df = df[df.total_area.between(30, 155) & (df.price_sqrm >= 0.52 * med)]
    steps["floors_out"] = steps["raw"] - len(df)
    n = len(df)
    for v in ("total_area", "price", "price_sqrm"):
        df = iqr_keep(df, v)
    steps["district_outliers_out"] = n - len(df)
    n = len(df)
    df = (df.assign(_d=pd.to_datetime(df.sana), _o=range(len(df)))
            .sort_values(["_d", "last_refresh_time", "_o"], kind="stable").drop_duplicates("id")
            .drop(columns=["_d", "_o"]).reset_index(drop=True))
    steps["dup_out"] = n - len(df)
    df["description"] = df["description"].map(norm).astype("string")
    steps["kept"] = len(df)
    return df, steps


if __name__ == "__main__":
    out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True); log = {}
    for f in sys.argv[2:]:
        month = re.search(r"(20\d\d-\d\d)\.parquet$", f).group(1)
        raw = pd.read_parquet(f)
        assert (raw.yil.astype(int).astype(str) + "-" + raw.oy.astype(int).astype(str).str.zfill(2) == month).all()
        assert (raw.state == "Toshkent shahri").all()
        df, steps = clean_old(raw)
        schema = pq.read_schema(f)
        pq.write_table(pa.Table.from_pandas(df[schema.names], preserve_index=False).cast(schema), out / f"{month}_13tash.parquet")
        log[month] = steps; print(month, steps)
    (out / "cleaning_log.json").write_text(json.dumps(log, indent=1))
