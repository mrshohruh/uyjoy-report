# uyjoy-report — Uzbek housing report agent (method v1)

This repository is the agent that writes the quarterly Uzbek housing and rent market report, for the whole
country (`respublika`) or Tashkent (`toshkent`). It works in five steps:

1. Turn the monthly olx.uz parquet exports into a `facts.json` "facts pack".
2. Collect cited news for the quarter.
3. Write each section in Uzbek, using Claude.
4. Check every number and claim in the text against the facts pack and the news.
5. Render the report to HTML and PDF.

The facts pack is the only source of numbers the writing step may use.

## Setup

```bash
pip install -r requirements.txt
export PYTHONPATH=src
```

## Use

### 1. Put the data files in the project's data folder

All monthly files go into **`data/parquet/`** inside this project (the folder is set in `config/paths.yaml`;
`UYJOY_DATA_DIR` or `--data` override it). Use the same names the files have in the project:

| File name | Contents |
| --- | --- |
| `YYYY-MM_13regions.parquet` | Regions, sale |
| `YYYY-MM_1147regions.parquet` | Regions, rent |
| `YYYY-MM_13tash.parquet` | Tashkent city, sale |
| `YYYY-MM_1147tash.parquet` | Tashkent city, rent |

```bash
python -m uyjoy inventory     # which months are present, and any file whose name is not read
python -m uyjoy verify        # every name matches its content (type and month)
python -m uyjoy import ~/Downloads/2026-10.parquet   # copies a file named only YYYY-MM.parquet in, properly named
```

### 2. Build one report's data

```bash
python -m uyjoy build --period 2025Q4 --scope respublika
python -m uyjoy build --period 2026Q3 --scope toshkent --allow-partial   # draft from an incomplete quarter
```

### The whole report in one command

Windows (from the project folder, or double-click-free from anywhere with the full path):

```bat
run_report 2026Q3                 :: whole country
run_report 2026Q3 respublika --no-ai   :: rebuild data, checks and PDF, reusing the text already written
```

Linux / macOS: `./run_report.sh 2026Q3`. Without the launchers: `python -m uyjoy report --period 2026Q3 --scope respublika`
(with `PYTHONPATH=src`).

It runs five steps and stops at the first problem:

1. exchange rate for the quarter (fetched from cbu.uz into `config/usd_uzs_quarter_end.csv` if missing);
2. data from `data/parquet/` -> `facts.json`, `tables.xlsx`;
3. news (Claude with web search) -> `news.json`;
4. Uzbek text, section by section, with retries -> `draft.json`;
5. checks -> `check.json`; if there are no errors, the PDF -> `report.pdf`.

Everything lands in `runs/<period>_<scope>/`. Steps 3-4 need `ANTHROPIC_API_KEY` (Windows: `setx ANTHROPIC_API_KEY "..."`
once, then open a new window). `--no-ai` skips them and reuses the files already there; `--no-pdf` stops after the checks;
`--allow-partial` builds from an incomplete quarter.

One-time setup: `python -m pip install -r requirements.txt` and `python -m playwright install chromium` (for the PDF).
The Tashkent (`toshkent`) PDF layout is not built yet; that scope runs up to the checks.

Single steps are still available: `build`, `news` (or `news --from-file items.json`), `write`, `check`, `render`.

Two more steps help when a run already exists:

```bash
python -m uyjoy rebuild --period 2026Q3 --scope respublika            # facts.json again from the run's tables.xlsx
python -m uyjoy rebuild --period 2026Q3 --scope respublika --tables path/to/tables.xlsx
python -m uyjoy news --period 2026Q3 --scope respublika --add extra_items.json   # add hand-collected news, ids kept
```

`rebuild` needs no parquet files: it reads the medians, yields, index and like-for-like tables a run saved
and writes a facts pack with exactly that run's numbers (plus the blocks a newer version adds). Use it after a
code update to re-render an old quarter in the current layout.

How the text stays honest:

- The writer sees only the facts pack and dated, cited news items. It is asked for one section at a time, as JSON.
- `validate.py` checks every number in the Uzbek text. It must exist in the facts pack at the same precision,
  or carry a `[nXX]` marker for a news item that contains it. A figure in brackets after a place name must
  belong to that place. Verbs must agree with signs. Leaders and laggards must be mentioned, and thin or hidden
  regions must not be headlined. Spelling rules are checked too: oʻ/gʻ (U+02BB), no Cyrillic, and valid markers.
- Every number the writer lists in `numbers_used` must equal the value at the facts id it names. This catches a
  real figure attached to the wrong thing, which the existence check alone cannot see.
- Failed sections are re-asked with the error list (up to `writer.max_retries` in config/llm.yaml).
- The editor pass sees numbers and markers only as locked placeholders. If any placeholder changes, the
  edit is thrown away.
- Expert quotes are never generated.

The PDF font must contain ʻ (U+02BB) and ʼ (U+02BC). The template uses Carlito and falls back to DejaVu Sans;
Inter does not cover ʻ.

### Data build outputs

Each build writes `runs/<period>_<scope>/`:

- `facts.json`: every number the report may quote. Values are rounded as printed and each carries an `id`.
  It also includes ready-made rankings (top 3 up and down, direction flips, streaks, cheapest and most
  expensive), sample-size flags and the cleaning log.
- `tables.xlsx`: full quarterly series per region, district and room count, plus yield, the index, the file
  inventory and the cleaning log.

A build refuses an incomplete quarter unless you pass `--allow-partial`.

## Report layout (Respublika)

`templates/respublika.html` + `templates/report.css`, charts in `src/uyjoy/charts.py` (hand-built SVG, no
plotting library), all values from facts.json. Figures and tables are numbered in the order of
`templates/figures.yaml`; the writer gets the same numbers so the text can say «(7-rasm)».

| Page | Content |
| --- | --- |
| Cover | 6 KPI cards with sparklines (Tashkent primary / secondary / rent, UNI, policy rate, USD/UZS), lead finding, contents |
| 01 Asosiy xulosalar | 5 findings; median vs listing-weighted vs same-listings change (grouped bars); summary table |
| 02 Makroiqtisodiy fon | policy rate vs inflation (real-rate band), USD/UZS line, macro table |
| 03 Ipoteka, bitimlar, qurilish | deals and mortgage share, housing completions (plan hatched), mortgage volume by market |
| 04–05 Birlamchi / Ikkilamchi | country choropleth of Δ quarter with callouts for the small eastern regions; region table with 12-quarter sparklines and colour-coded Δ cells; Tashkent district map, dumbbell (previous → current), district table |
| 06 Taqqos | new-build premium bars; small multiples primary vs secondary for every region |
| 07 Ijara | rent-level map; region table; Tashkent district map; district × rooms heatmap |
| 08 Rentabellik | yield map; sale price vs rent scatter with iso-yield lines; yield trend Tashkent vs regions median |
| 09 UNI | index lines (national, Tashkent, top/bottom regions); regional index bars; 8-quarter Δ heatmap |
| 10 Bozor sharhi | three themed bands, conclusion, outlook and risks boxes |
| 11–12 Ilova, manbalar | all Tashkent district indicators, method, abbreviations, cited news, chart data sources |

Design rules: each market keeps one colour (primary blue, secondary amber, rent teal); changes use one
fixed diverging scale (orange = fall, blue = rise; −5/−2/−0.5/+0.5/+2/+5 %) on every map, table cell and
heatmap; levels use a quantile blue scale; cells with 10–29 listings are hatched, fewer than 10 dotted grey.

New facts blocks (`src/uyjoy/history.py`): `tarix` / `tarix_tumanlar` (12 / 8 quarters of values and changes),
`respublika` (listing-weighted change and the composition gap against same-listings), `premium` /
`premium_tumanlar`, `rentabellik_tarix`, `rentabellik_tumanlar`, `indeks_hududlar`, `xonalar_toshkent`, and
`makro` from `config/macro/` (policy rate, inflation, deals, mortgages, construction — every value with a
source; see `config/macro/README.md`; add a row each quarter).

Maps: `assets/geo/uz_regions.json` (regions) and `assets/geo/tashkent_districts.json` (11 districts; built by
`tools/build_geo_tashkent.py` from geoBoundaries, Yangihayot inside Sergeli as in the data).

## Method v1 (config/method.yaml)

| Step | Rule |
| --- | --- |
| Scope | Buildings of 4+ floors, 1–5 rooms, 20–140 m² |
| Price caps | Regions sale ≤ $135k, rent ≤ $800; Tashkent sale ≤ $330k, rent ≤ $2,300 |
| Duplicates | Within a quarter: latest row per listing id, then drop reposts (same place, rooms, area, floor, height, price, market) |
| Outliers | Drop price per m² outside 0.4×–2.5× the cell median |
| Geography | Whole region for the 13 regions; Tashkent by district plus a city total |
| Statistic | Median USD/m² over the quarter × CBU rate on the quarter's last day |
| Thin cells | n ≥ 30 published; 10–29 marked `thin` (shown with *, never headlined); < 10 `hidden` |
| Changes | Quarterly and annual changes from this pipeline's own series, in so'm (and in USD for the currency check) |
| Yield | Median rent × 12 / median sale price (both markets) |
| Index | Resale, room-mix-adjusted chain (1/2/3/4+ rooms), USD terms, population-weighted; base 2023Q1 = 100 (provisional base = first quarter on file until 2023 data is loaded) |

## Series breaks and like-for-like changes

When the source exports start being cleaned differently, add the first affected month to `series_breaks` in
`config/method.yaml`. The first one is July 2026: from then the colleague's exports use other rules (rent loses
most cheap listings, area limits change). Any quarterly or yearly change that spans a break:

- is flagged in `facts.json` (`report.series_break`) and marked † in the PDF tables;
- comes with the like-for-like check (`solishtirma`, computed for every report): the mean price change of the same listing ids seen in both
  quarters, in so'm at quarter-end rates and in USD. Asking prices change rarely, so this is a lower bound on the
  market move, not a replacement for it. Only the quarterly version is given to the writer; the yearly one is
  biased towards listings that never sold;
- must be named in every affected section (`note_break: true` in `prompts/sections.yaml`), or the check fails.

The proper fix for a cleaning break is to re-clean the affected months from the uncleaned exports with the earlier
rules. `tools/` has one script per file type; each holds both rule sets, inferred from the colleague's files:

| Script | Type | New rules (Jul 2026 on) | Earlier rules |
| --- | --- | --- | --- |
| `clean_13regions.py` | regional sale | exact | approximated (national price-per-m² floor) |
| `clean_1147_v2.py` (`clean_1147.py` for old-format raw) | regional rent | exact | exact |
| `clean_13tash.py` | Tashkent sale | exact | approximated (citywide floors + district cuts) |
| `clean_1147tash.py` | Tashkent rent | exact | approximated (area 30-150, price <= 1600 + district cuts) |

July-September 2026 in `data/raw/` are the earlier-rule versions; the colleague's new-rule files are kept in
`data/colleague_newrules/`. No break is declared now. From July 2026 the website itself carries fewer listings in
several regions and far fewer cheap rentals; that is a real change in the listings market, so it is explained in
the text (using the like-for-like check, which is now part of every report) rather than flagged as a data break.

## Config to keep up to date

- `config/usd_uzs_quarter_end.csv`: add the CBU rate effective on each quarter's last day. A build fails with a
  clear message if one is missing. The 2026Q3 value is derived and should be replaced with the cbu.uz figure.
- `config/population.csv`: index weights (stat.uz, 1 April 2026).
- `config/geo.yaml`: canonical Uzbek names (with ʻ U+02BB) and report order.

## Tests

```bash
python -m pytest -q tests
```
