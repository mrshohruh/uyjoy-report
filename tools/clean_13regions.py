"""Clean raw regional sale (category 13) exports.

Two rule sets, both inferred from the colleague's cleaned files:

  new  (from July 2026; reproduced exactly, row for row, on 2026-07..09):
       per region (state), one after another: drop total_area outside Q1-1.5*IQR..Q3+1.5*IQR,
       then price, then price_sqrm; then keep price <= 135000 and total_area <= 150.
  old  (up to June 2026; approximated, no raw file from that period to confirm):
       one national floor and ceiling on price_sqrm per month (0.574x and 2.9x the month's
       median), total_area 21..210 m², price <= 260000, one row per id (earliest date),
       description normalised like the 2025 files.
"""
# Output names follow YYYY-MM_<type>.parquet, so the output folder can be the project's data/parquet/.
import re, sys, json
from pathlib import Path
import pandas as pd
import pyarrow as pa, pyarrow.parquet as pq

NON = re.compile(r"[^a-zа-я0-9 ]")


def iqr_keep(d, var, k=1.5):
    g = d.groupby("state")[var]
    q1, q3 = g.transform(lambda s: s.quantile(.25)), g.transform(lambda s: s.quantile(.75))
    i = q3 - q1
    return d[(d[var] >= q1 - k * i) & (d[var] <= q3 + k * i)]


def clean_new(df):
    for v in ("total_area", "price", "price_sqrm"):
        df = iqr_keep(df, v)
    return df[(df.price <= 135000) & (df.total_area <= 150)]


def clean_old(df):
    med = df.price_sqrm.median()
    df = df[df.price_sqrm.between(0.574 * med, 2.9 * med) & df.total_area.between(21, 210) & (df.price <= 260000)]
    df = (df.assign(_d=pd.to_datetime(df.sana)).sort_values(["_d", "last_refresh_time"], kind="stable")
            .drop_duplicates("id").drop(columns="_d"))
    df = df.copy()
    df["description"] = df["description"].map(
        lambda t: t if t is None or t is pd.NA else NON.sub("", re.sub(r"<br\s*/?>", "", t).lower()).replace("  ", "")
    ).astype("string")
    return df


if __name__ == "__main__":
    rules, out = sys.argv[1], Path(sys.argv[2]); log = {}
    out.mkdir(parents=True, exist_ok=True)
    for f in sys.argv[3:]:
        month = re.search(r"(20\d\d-\d\d)\.parquet$", f).group(1)
        raw = pd.read_parquet(f)
        df = (clean_new if rules == "new" else clean_old)(raw)
        df = df.assign(_d=pd.to_datetime(df.sana)).sort_values("_d", kind="stable").drop(columns="_d").reset_index(drop=True)
        tbl = pa.Table.from_pandas(df, preserve_index=False).cast(pq.read_schema(f))
        pq.write_table(tbl, out / f"{month}_13regions.parquet")
        log[month] = {"raw": len(raw), "kept": len(df)}
        print(rules, month, log[month])
    (out / "cleaning_log.json").write_text(json.dumps(log, indent=1))
