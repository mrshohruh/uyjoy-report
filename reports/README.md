# Published report runs

`2026Q3_respublika/` — the 2026-Q3 Respublika report in the new layout: `report.pdf`, `report.html`, the
checked text (`draft.json`), the news it cites (`news.json`) and the check results (`check.json`, empty = no
issues). The numbers come from the run's `tables.xlsx` via `uyjoy rebuild`, identical to the earlier draft's
facts.json. To rebuild: copy `draft.json` and `news.json` into `runs/2026Q3_respublika/` next to that run's
`tables.xlsx`, then `python -m uyjoy rebuild ...` and `python -m uyjoy render ...`.
