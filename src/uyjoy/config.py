"""Load method, geography, exchange-rate and population settings from config/."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"


@dataclass(frozen=True)
class Config:
    method: dict
    geo: dict
    rates: pd.Series        # index: "2025Q4", value: UZS per USD
    population: pd.Series   # index: canonical region name, value: thousands

    def rate(self, period: str) -> float:
        if period not in self.rates.index:
            raise KeyError(
                f"No USD/UZS rate for {period}. Add the CBU rate effective on the quarter's "
                f"last day to config/usd_uzs_quarter_end.csv (or run `uyjoy rates fetch`)."
            )
        return float(self.rates[period])


def load(config_dir: Path = CONFIG_DIR) -> Config:
    method = yaml.safe_load((config_dir / "method.yaml").read_text(encoding="utf-8"))
    geo = yaml.safe_load((config_dir / "geo.yaml").read_text(encoding="utf-8"))
    rates = pd.read_csv(config_dir / "usd_uzs_quarter_end.csv", dtype={"period": str}).set_index("period")["rate"]
    pop = pd.read_csv(config_dir / "population.csv").set_index("geo")["population_thousands"]
    return Config(method=method, geo=geo, rates=rates, population=pop)


def data_dir(config_dir: Path = CONFIG_DIR) -> Path:
    """The project's parquet folder: UYJOY_DATA_DIR, else config/paths.yaml, else data/parquet."""
    env = os.environ.get("UYJOY_DATA_DIR")
    if env:
        return Path(env).expanduser().resolve()
    f = config_dir / "paths.yaml"
    rel = (yaml.safe_load(f.read_text(encoding="utf-8")) or {}).get("data_dir", "data/parquet") if f.exists() \
        else "data/parquet"
    path = Path(rel).expanduser()
    return path if path.is_absolute() else (ROOT / path)
