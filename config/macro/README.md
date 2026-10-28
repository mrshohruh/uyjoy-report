# Macro context for the report

`quarterly.csv` — one row per quarter, values at the quarter's end:

- `base_rate_pct`: Central Bank policy rate in force on the quarter's last day.
- `inflation_yoy_pct`: annual CPI inflation for the quarter's last month (Statistics Agency / CBU), 1 decimal.
- `*_source`: the page the value was taken from. Every value must have one; the report lists them.

`annual.csv` — yearly series shown on the mortgage page. Source for all of them is the
company's 2025 Q4 review (data from the Central Bank and the Center for Economic Research and Reforms
for deals and mortgages, the National Committee for Urbanization for completed housing, the Central
Bank for mortgage volumes). `housing_plan = 1` marks a planned (not completed) year.

Add a row each quarter before running the report. A missing quarter only shortens the charts.
