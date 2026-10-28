"""Run every data stage for one period and scope, and write the outputs."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from . import clean as clean_mod
from . import facts as facts_mod
from . import breaks, ingest, metrics
from .config import Config


def _quarters_needed(period: str) -> list[str]:
    p = pd.Period(period, "Q")
    return [str(p - k) for k in range(0, 9)]  # current, previous, year ago, and streak history


def compute(raw_dir: Path, period: str, cfg: Config, with_index: bool = True) -> dict:
    inv = ingest.inventory(raw_dir)
    if inv.empty:
        raise FileNotFoundError(
            f"No data files in {raw_dir}. Put the monthly files there, named YYYY-MM_13regions.parquet, "
            f"YYYY-MM_1147regions.parquet, YYYY-MM_13tash.parquet and YYYY-MM_1147tash.parquet "
            f"(see data/parquet/README.md), or change config/paths.yaml.")
    wanted = None if with_index else _quarters_needed(period)
    frames, logs = [], []
    for fam in ingest.FAMILIES:
        d = ingest.load_family(raw_dir, fam, cfg, wanted)
        if d.empty:
            continue
        d, log = clean_mod.clean(d, cfg)
        frames.append(d)
        logs.append(log)
    df = pd.concat(frames, ignore_index=True)
    log = pd.concat(logs, ignore_index=True)

    tables = {"clean_rows": len(df)}
    tables["regions"] = metrics.medians(df, cfg, "region")
    tsh = df[df.family.str.startswith("tashkent")]
    tables["districts"] = metrics.medians(tsh, cfg, "district") if not tsh.empty else pd.DataFrame()
    tables["rooms"] = metrics.medians(tsh, cfg, "district", extra=("rooms",)) if not tsh.empty else pd.DataFrame()
    tables["yield_hudud"] = metrics.rental_yield(tables["regions"])
    tables["yield_tuman"] = metrics.rental_yield(tables["districts"])
    q = pd.Period(period, "Q")
    tables["lfl_qoq"] = breaks.like_for_like(df, cfg, str(q - 1), period)
    tables["lfl_yoy"] = breaks.like_for_like(df, cfg, str(q - 4), period)
    if with_index:
        reg = metrics.mix_adjusted_index(df, cfg, "region", until=period)
        tables["index_regional"] = reg
        tables["index"] = metrics.national_index(reg, cfg)
    return {"tables": tables, "inventory": inv, "clean_log": log}


def run(raw_dir: Path, out_dir: Path, period: str, scope: str, cfg: Config,
        allow_partial: bool = False, with_index: bool = True) -> Path:
    res = compute(raw_dir, period, cfg, with_index)
    inv = res["inventory"]
    have = inv[inv.quarter == period]
    needed = ["regions_sale", "regions_rent"] if scope == "respublika" else ["tashkent_sale", "tashkent_rent"]
    problems = []
    for fam in needed:
        months = sorted(have[have.family == fam].month)
        if len(months) < 3:
            problems.append(f"{fam}: {len(months)}/3 months ({', '.join(months) or 'none'})")
    if problems and not allow_partial:
        raise RuntimeError("Incomplete quarter, report not built: " + "; ".join(problems)
                           + ". Add the missing files or pass --allow-partial for a draft.")

    facts = facts_mod.build(period, scope, cfg, res["tables"], inv, res["clean_log"])
    facts["report"]["incomplete"] = problems

    run_dir = out_dir / f"{period}_{scope}"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "facts.json").write_text(json.dumps(facts, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    export_tables(res, run_dir / "tables.xlsx")
    return run_dir


TABLE_SHEETS = ("regions", "districts", "rooms", "yield_hudud", "yield_tuman", "index_regional", "index",
                "lfl_qoq", "lfl_yoy")


def load_tables(path: Path) -> dict:
    """Read a run's tables.xlsx back into the same structure `compute` returns.

    This lets a report be rebuilt (new facts, new layout) from a finished run without the parquet files,
    with exactly the numbers that run produced.
    """
    xl = pd.read_excel(path, sheet_name=None, dtype={"rooms": str, "quarter": str, "from": str, "to": str})
    tables = {}
    for name in TABLE_SHEETS:
        df = xl.get(name[:31], pd.DataFrame())
        tables[name] = df
    if not tables["index"].empty and "missing" in tables["index"]:
        tables["index"]["missing"] = tables["index"]["missing"].map(
            lambda v: [] if v is None or (isinstance(v, float) and pd.isna(v)) else
            (json.loads(v.replace("'", '"')) if isinstance(v, str) else list(v)))
    inv = xl.get("files", pd.DataFrame(columns=["family", "month", "quarter"]))
    log = xl.get("cleaning_log", pd.DataFrame(columns=["family", "quarter", "rows", "rule"]))
    return {"tables": tables, "inventory": inv, "clean_log": log}


def rebuild(tables_xlsx: Path, out_dir: Path, period: str, scope: str, cfg: Config) -> Path:
    """facts.json for `period` from a saved tables.xlsx (see load_tables); tables.xlsx itself is left as it is."""
    res = load_tables(tables_xlsx)
    facts = facts_mod.build(period, scope, cfg, res["tables"], res["inventory"], res["clean_log"])
    facts["report"]["incomplete"] = []
    run_dir = out_dir / f"{period}_{scope}"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "facts.json").write_text(json.dumps(facts, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    if tables_xlsx.resolve() != (run_dir / "tables.xlsx").resolve():
        import shutil  # noqa: PLC0415
        shutil.copyfile(tables_xlsx, run_dir / "tables.xlsx")
    return run_dir


def export_tables(res: dict, path: Path) -> None:
    t = res["tables"]
    with pd.ExcelWriter(path) as xw:
        for name in ("regions", "districts", "rooms", "yield_hudud", "yield_tuman", "index_regional", "index",
                     "lfl_qoq", "lfl_yoy"):
            df = t.get(name)
            if isinstance(df, pd.DataFrame) and not df.empty:
                df.to_excel(xw, sheet_name=name[:31], index=False)
        res["inventory"].drop(columns="path").to_excel(xw, sheet_name="files", index=False)
        if not res["clean_log"].empty:
            res["clean_log"].to_excel(xw, sheet_name="cleaning_log", index=False)
