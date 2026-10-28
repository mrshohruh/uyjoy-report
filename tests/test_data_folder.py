import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from uyjoy import config, ingest  # noqa: E402


def _write(path, state, market, year=2026, month=9):
    pd.DataFrame({"state": [state], "type_of_market": pd.Series([market], dtype="string"),
                  "yil": [year], "oy": [month]}).to_parquet(path)


def test_default_data_folder_is_inside_the_project(monkeypatch):
    monkeypatch.delenv("UYJOY_DATA_DIR", raising=False)
    d = config.data_dir()
    assert d == config.ROOT / "data" / "parquet"
    monkeypatch.setenv("UYJOY_DATA_DIR", "/tmp/elsewhere")
    assert config.data_dir() == Path("/tmp/elsewhere")


def test_inventory_reads_names_and_skips_others(tmp_path):
    _write(tmp_path / "2026-09_13regions.parquet", "Buxoro Viloyati", "Новостройки")
    _write(tmp_path / "2026-09_1147tash.parquet", "Toshkent shahri", None)
    _write(tmp_path / "2026-09.parquet", "Buxoro Viloyati", None)          # unnamed: not read
    inv = ingest.inventory(tmp_path)
    assert sorted(inv.family) == ["regions_sale", "tashkent_rent"]
    assert set(inv.quarter) == {"2026Q3"}
    assert [f.name for f in ingest.unrecognised(tmp_path)] == ["2026-09.parquet"]


def test_verify_catches_wrong_names_and_import_fixes_them(tmp_path):
    _write(tmp_path / "2026-09_13regions.parquet", "Buxoro Viloyati", None)  # actually rent
    _write(tmp_path / "2026-08_13tash.parquet", "Toshkent shahri", "Новостройки", month=9)  # wrong month
    problems = ingest.verify(tmp_path)
    assert any("1147regions" in p for p in problems) and any("2026-09" in p for p in problems)
    src = tmp_path / "in"; src.mkdir(); _write(src / "2026-09.parquet", "Toshkent shahri", None)
    (_, fam, month, dest), = ingest.import_files([src / "2026-09.parquet"], tmp_path / "data")
    assert (fam, month, dest.name) == ("tashkent_rent", "2026-09", "2026-09_1147tash.parquet")
