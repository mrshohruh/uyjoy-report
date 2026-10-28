"""Find the monthly parquet files in the project's data folder, and load them.

All files live in one folder inside the project (config/paths.yaml, default data/parquet),
named YYYY-MM_<type>.parquet, the same names the colleague's files carry:

  YYYY-MM_13regions.parquet    regions, sale
  YYYY-MM_1147regions.parquet  regions, rent
  YYYY-MM_13tash.parquet       Tashkent city, sale
  YYYY-MM_1147tash.parquet     Tashkent city, rent

The type is read from the name. `verify` checks every name against the file's content
(Tashkent files have state == "Toshkent shahri" on every row; rent files have no
type_of_market). `import_files` copies a file named only YYYY-MM.parquet into the folder
under its proper name, using the same content check.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from .config import Config

FAMILIES = ("regions_sale", "regions_rent", "tashkent_sale", "tashkent_rent")
CODES = {"13regions": "regions_sale", "1147regions": "regions_rent",
         "13tash": "tashkent_sale", "1147tash": "tashkent_rent"}
FAMILY_CODE = {v: k for k, v in CODES.items()}
NAME_RE = re.compile(r"^(\d{4})-(\d{2})_(13regions|1147regions|13tash|1147tash)\.parquet$")

# Only these columns go further. Free text (title, description) can hold phone
# numbers and names, so it is dropped here and never reaches a model.
KEEP = [
    "id", "url", "sana", "yil", "oy", "created_time", "top_ad",
    "state", "location_uz", "district", "type_of_market",
    "price", "currency", "total_area", "price_sqrm",
    "number_of_rooms", "floor", "total_floors",
]


def detect_family(path: Path) -> str:
    t = pq.read_table(path, columns=["state", "type_of_market"]).to_pandas()
    if t.empty:
        raise ValueError(f"{path} has no rows")
    states = set(t["state"].dropna().unique())
    tashkent = states == {"Toshkent shahri"}
    if not tashkent and "Toshkent shahri" in states:
        raise ValueError(f"{path} mixes Tashkent city with regions; cannot classify")
    rent = t["type_of_market"].isna().all()
    return f"{'tashkent' if tashkent else 'regions'}_{'rent' if rent else 'sale'}"


def detect_month(path: Path) -> str:
    t = pq.read_table(path, columns=["yil", "oy"]).to_pandas().drop_duplicates()
    if len(t) != 1:
        raise ValueError(f"{path} spans several months: {t.to_dict('records')}")
    return f"{int(t.yil.iloc[0]):04d}-{int(t.oy.iloc[0]):02d}"


def import_files(paths: list[Path], data_dir: Path) -> list[tuple[Path, str, str, Path]]:
    """Copy each file into data_dir as YYYY-MM_<type>.parquet (type and month read from the content)."""
    done = []
    data_dir.mkdir(parents=True, exist_ok=True)
    for p in paths:
        fam, month = detect_family(p), detect_month(p)
        dest = data_dir / f"{month}_{FAMILY_CODE[fam]}.parquet"
        if p.resolve() != dest.resolve():
            shutil.copyfile(p, dest)
        done.append((p, fam, month, dest))
    return done


def unrecognised(data_dir: Path) -> list[Path]:
    """Parquet files in the folder whose name does not follow YYYY-MM_<type>.parquet (they are not read)."""
    return sorted(f for f in data_dir.glob("*.parquet") if not NAME_RE.match(f.name))


def verify(data_dir: Path) -> list[str]:
    """Check every file's name against its content. Returns a list of problems (empty = all good)."""
    problems = [f"{f.name}: name not in the form YYYY-MM_<13regions|1147regions|13tash|1147tash>.parquet"
                for f in unrecognised(data_dir)]
    for r in inventory(data_dir).itertuples():
        try:
            fam, month = detect_family(r.path), detect_month(r.path)
        except ValueError as e:
            problems.append(f"{r.path.name}: {e}")
            continue
        if fam != r.family:
            problems.append(f"{r.path.name}: content is {FAMILY_CODE[fam]} ({fam}), not {FAMILY_CODE[r.family]}")
        if month != r.month:
            problems.append(f"{r.path.name}: rows are from {month}, not {r.month}")
    return problems


def inventory(data_dir: Path) -> pd.DataFrame:
    rows = []
    for f in sorted(Path(data_dir).glob("*.parquet")):
        m = NAME_RE.match(f.name)
        if m:
            rows.append({"family": CODES[m[3]], "month": f"{m[1]}-{m[2]}", "path": f})
    inv = pd.DataFrame(rows, columns=["family", "month", "path"])
    if not inv.empty:
        p = pd.PeriodIndex(inv["month"], freq="M")
        inv["quarter"] = p.asfreq("Q").astype(str)
    return inv


def load_family(data_dir: Path, family: str, cfg: Config, quarters: list[str] | None = None) -> pd.DataFrame:
    inv = inventory(data_dir)
    inv = inv[inv.family == family]
    if quarters is not None:
        inv = inv[inv.quarter.isin(quarters)]
    if inv.empty:
        return pd.DataFrame()
    frames = []
    for _, r in inv.iterrows():
        cols = [c for c in KEEP if c in pq.read_schema(r.path).names]
        d = pd.read_parquet(r.path, columns=cols)
        d["month"] = r.month
        d["quarter"] = r.quarter
        frames.append(d)
    df = pd.concat(frames, ignore_index=True)
    return standardise(df, family, cfg)


def standardise(df: pd.DataFrame, family: str, cfg: Config) -> pd.DataFrame:
    g = cfg.geo
    df = df.copy()
    df["family"] = family
    df["region"] = df["state"].map(g["state_to_region"])
    unknown = df.loc[df.region.isna(), "state"].unique()
    if len(unknown):
        raise ValueError(f"Unknown state values, add them to config/geo.yaml: {list(unknown)}")
    if family.startswith("tashkent"):
        df["district"] = df["district"].map(g["district_ru_to_uz"])
        if df["district"].isna().any():
            raise ValueError("Tashkent rows with an unknown or empty district; update config/geo.yaml")
    else:
        df["district"] = None
    if family.endswith("rent"):
        df["market"] = "rent"
    else:
        df["market"] = df["type_of_market"].map(g["market_ru"])
        if df["market"].isna().any():
            raise ValueError(f"Unknown type_of_market values: {df.type_of_market[df.market.isna()].unique()}")
    if (df["currency"] != "UYE").any():
        raise ValueError(f"Non-USD prices found: {df.currency.unique()}; conversion rule needed")
    # geo = the finest unit a table is built on: district in Tashkent, region elsewhere
    df["geo"] = df["district"].fillna(df["region"])
    df["rooms"] = df["number_of_rooms"].clip(upper=4).astype(int).astype(str).replace({"4": "4+"})
    return df
