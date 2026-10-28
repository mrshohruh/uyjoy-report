# Uy-joy bozori monitori (dashboard)

Put this folder inside `uyjoy-report` as `uyjoy-report/dashboard`. It uses the agent's own code
(`src/uyjoy`) and config, so every figure follows method v1.

    cd uyjoy-report/dashboard
    python compute_periods.py                # reads data/parquet, writes dashboard_data.json
    python build_dash.py                     # writes out/uyjoy-monitor-sayt-uchun.html (for the website)
    python check_dash.py out/uyjoy-monitor-sayt-uchun.html   # optional: compares every shown number with the data

- Months, quarters and years use the same cleaning as the quarterly report; de-duplication and outlier
  trimming happen within the chosen period. Quarters reproduce the agent's facts exactly.
- So'm values use the CBU rate on the period's last day (`usd_uzs_month_end.csv`; quarter-ends equal the
  agent's `config/usd_uzs_quarter_end.csv`). Add a row for each new month.
- The latest year is year-to-date and is compared with the same months of the previous year.
- Change `LAST` at the top of `compute_periods.py` when a new month arrives.
