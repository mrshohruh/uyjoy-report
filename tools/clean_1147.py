"""Clean raw olx rent (category 1147) regional monthly files the way the 2025 cleaned files were made.

Rules (inferred from the colleague's cleaned 2025 files and checked on 35,739 matched listings):
  1. price 100..1500 (USD, inclusive)
  2. one row per listing id per month: the earliest date in the month
  3. description: lowercase, keep only a-z, а-я, 0-9 and space, then delete "  " (double spaces)
  4. sort by date, same 40 columns and dtypes
Raw files already satisfy the other limits (area 25-200 m², 4+ floors, currency UYE).
"""
# Output names follow YYYY-MM_<type>.parquet, so the output folder can be the project's data/parquet/.
import re, sys, json
from pathlib import Path
import pandas as pd
import pyarrow as pa, pyarrow.parquet as pq

P_MIN, P_MAX = 100, 1500
NON = re.compile(r"[^a-zа-я0-9 ]")

def norm_desc(t):
    if t is None or t is pd.NA: return t
    return NON.sub("", t.lower()).replace("  ", "")

def clean(df):
    steps = {"raw": len(df)}
    df = df[df.price.between(P_MIN, P_MAX)]
    steps["price_out"] = steps["raw"] - len(df)
    n = len(df)
    df = (df.assign(_d=pd.to_datetime(df.sana), _o=range(len(df)))
            .sort_values(["_d", "last_refresh_time", "_o"], kind="stable")
            .drop_duplicates("id", keep="first"))
    steps["dup_out"] = n - len(df)
    df = df.drop(columns=["_d", "_o"]).reset_index(drop=True)
    df["description"] = df["description"].map(norm_desc).astype("string")
    steps["kept"] = len(df)
    return df, steps

if __name__ == "__main__":
    out = Path(sys.argv[1]); log = {}
    for f in sys.argv[2:]:
        month = re.search(r"(20\d\d-\d\d)\.parquet$", f).group(1)
        raw = pd.read_parquet(f)
        assert (raw.yil.astype(str) + "-" + raw.oy.astype(int).astype(str).str.zfill(2) == month).all()
        df, steps = clean(raw)
        schema = pq.read_schema(f)       # write with the raw file's own schema (same as the cleaned files)
        tbl = pa.Table.from_pandas(df, preserve_index=False).cast(schema)
        pq.write_table(tbl, out / f"{month}_1147regions.parquet")
        log[month] = steps
        print(month, steps)
    (out / "cleaning_log.json").write_text(json.dumps(log, indent=1))
