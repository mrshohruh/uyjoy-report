"""Command line: `python -m uyjoy <command>`.

  Data: every file lives in the project's data folder (config/paths.yaml, default data/parquet),
  named YYYY-MM_13regions / _1147regions / _13tash / _1147tash .parquet.

  import FILE...                 copy files named only YYYY-MM.parquet into the data folder, properly named
  inventory                      list which months are present for each file type
  verify                         check every file's name against its content
  build --period 2025Q4 --scope respublika|toshkent [--allow-partial] [--no-index]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import config, ingest, pipeline

ROOT = config.ROOT


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="uyjoy")
    ap.add_argument("--data", "--raw", dest="raw", type=Path, default=config.data_dir(),
                    help="data folder (default: config/paths.yaml, normally data/parquet)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_imp = sub.add_parser("import")
    p_imp.add_argument("files", nargs="+", type=Path)
    sub.add_parser("inventory")
    sub.add_parser("verify")
    p_r = sub.add_parser("rates", help="fetch missing CBU quarter-end rates for every quarter on file")
    p_r.add_argument("--overwrite", action="store_true")
    p_b = sub.add_parser("build")
    p_b.add_argument("--period", required=True, help="e.g. 2025Q4")
    p_b.add_argument("--scope", required=True, choices=["respublika", "toshkent"])
    p_b.add_argument("--out", type=Path, default=ROOT / "runs")
    p_b.add_argument("--allow-partial", action="store_true")
    p_b.add_argument("--no-index", action="store_true")
    for name in ("news", "write", "check", "render", "report"):
        p = sub.add_parser(name)
        p.add_argument("--period", required=True)
        p.add_argument("--scope", required=True, choices=["respublika", "toshkent"])
        p.add_argument("--out", type=Path, default=ROOT / "runs")
        if name == "news":
            p.add_argument("--from-file", type=Path, help="load hand-collected items instead of searching")
        if name == "report":
            p.add_argument("--allow-partial", action="store_true")
            p.add_argument("--no-ai", action="store_true",
                           help="reuse news.json and draft.json already in the run folder (no API calls)")
            p.add_argument("--no-pdf", action="store_true", help="stop after the checks")
            p.add_argument("--keep-news", action="store_true",
                           help="reuse news.json from the last run (no new web searches); still writes the text")
            p.add_argument("--fix-errors", action="store_true",
                           help="reuse news.json and draft.json; rewrite only the sections that fail a check")
    a = ap.parse_args(argv)
    if a.cmd in ("news", "write", "check", "render", "report"):
        return _report_cmds(a)

    if a.cmd == "import":
        for src, fam, month, dest in ingest.import_files(a.files, a.raw):
            print(f"{src.name:40s} -> {fam:14s} {month}  ({dest.name})")
        return 0
    if a.cmd == "verify":
        problems = ingest.verify(a.raw)
        n = len(ingest.inventory(a.raw))
        for pr in problems:
            print("problem:", pr)
        print(f"{n} files in {a.raw}: " + ("all names match their content" if not problems else f"{len(problems)} problem(s)"))
        return 1 if problems else 0
    if a.cmd == "inventory":
        inv = ingest.inventory(a.raw)
        print(f"data folder: {a.raw}")
        for f in ingest.unrecognised(a.raw):
            print(f"  not read (name not YYYY-MM_<type>.parquet): {f.name}")
        if inv.empty:
            print("no files")
            return 0
        print(inv.groupby(["family", "quarter"]).month.apply(lambda m: ",".join(x[-2:] for x in sorted(m)))
              .unstack(0).fillna("").to_string())
        return 0
    if a.cmd == "rates":
        from . import rates
        inv = ingest.inventory(a.raw)
        new = rates.update_csv(config.CONFIG_DIR / "usd_uzs_quarter_end.csv",
                               sorted(inv.quarter.unique()), overwrite=a.overwrite)
        print(new.to_string(index=False) if not new.empty else "all quarters already have a rate")
        return 0
    if a.cmd == "build":
        cfg = config.load()
        d = pipeline.run(a.raw, a.out, a.period.upper(), a.scope, cfg, a.allow_partial, not a.no_index)
        print(f"wrote {d}")
        return 0
    return 1


def _check(run_dir: Path, scope: str) -> int:
    """Run every text check on draft.json; print and save them. Returns the number of errors."""
    import json  # noqa: PLC0415

    from . import validate, writer  # noqa: PLC0415
    facts = json.loads((run_dir / "facts.json").read_text(encoding="utf-8"))
    items = json.loads((run_dir / "news.json").read_text(encoding="utf-8"))
    draft = json.loads((run_dir / "draft.json").read_text(encoding="utf-8"))
    rows = []
    for sec in writer.sections(scope):
        if sec["key"] not in draft:
            rows.append({"section": sec["key"], "level": "error", "code": "missing", "slot": "*",
                         "message": "boʻlim yozilmagan"})
            continue
        for i in validate.check_section(sec, draft[sec["key"]]["slots"], facts, items,
                                        draft[sec["key"]].get("numbers_used")):
            rows.append({"section": sec["key"], **i})
    n_err = sum(r["level"] == "error" for r in rows)
    (run_dir / "check.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    for r in rows:
        print(f"{r['level']:7s} {r['section']}/{r['slot']} [{r['code']}] {r['message']}")
    print(f"{n_err} errors, {len(rows) - n_err} warnings")
    return n_err


def _report(a, run_dir: Path, period: str) -> int:
    """The whole report in one command: rate -> data -> news -> text -> checks -> PDF."""
    import json  # noqa: PLC0415
    import os  # noqa: PLC0415

    from . import news, validate, writer  # noqa: PLC0415
    from .llm import run_cost  # noqa: PLC0415
    uses_ai = not a.no_ai
    if uses_ai and not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set, so the news and Uzbek text steps cannot run.\n"
              "Set it first (Windows cmd: set ANTHROPIC_API_KEY=...), or add --no-ai to rebuild the data,\n"
              "checks and PDF using the news.json and draft.json already in " + str(run_dir))
        return 2
    if (a.fix_errors or a.keep_news) and not (run_dir / "news.json").exists():
        print(f"--fix-errors/--keep-news need news.json from an earlier run in {run_dir}")
        return 2
    if a.fix_errors and not (run_dir / "draft.json").exists():
        print(f"--fix-errors needs draft.json from an earlier run in {run_dir}")
        return 2
    log = run_dir / "log.jsonl"
    log_start = len(log.read_text(encoding="utf-8").splitlines()) if log.exists() else 0

    def cost_line():
        if uses_ai:
            c = run_cost(log, log_start)
            print(f"cost of this run: about ${c['usd']:.2f} ({c['calls']} calls, {c['input_tokens']:,} input and "
                  f"{c['output_tokens']:,} output tokens, {c['searches']} web searches)")

    cfg = config.load()
    print(f"[1/5] exchange rate for {period}")
    if period not in cfg.rates.index:
        try:
            from . import rates  # noqa: PLC0415
            rates.update_csv(config.CONFIG_DIR / "usd_uzs_quarter_end.csv", [period])
            cfg = config.load()
            print(f"      fetched from cbu.uz: {cfg.rate(period)}")
        except Exception as e:  # noqa: BLE001
            print(f"      could not fetch it ({e}); add it to config/usd_uzs_quarter_end.csv")
            return 2
    else:
        print(f"      {cfg.rate(period)} (config/usd_uzs_quarter_end.csv)")
    print(f"[2/5] data from {a.raw}")
    pipeline.run(a.raw, a.out, period, a.scope, cfg, a.allow_partial)
    if a.no_ai:
        missing = [f for f in ("news.json", "draft.json") if not (run_dir / f).exists()]
        if missing:
            print(f"--no-ai needs {', '.join(missing)} in {run_dir}")
            return 2
        print("[3/5] news: reusing news.json\n[4/5] text: reusing draft.json")
    else:
        from .llm import LLM  # noqa: PLC0415
        m = LLM(log)
        if a.keep_news or a.fix_errors:
            items = news.load(run_dir / "news.json", period)       # re-filtered with the current rules
            (run_dir / "news.json").write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"[3/5] news: reusing news.json ({len(items)} items)")
        else:
            print("[3/5] news (web search)")
            items = news.collect(period, a.scope, m, run_dir / "news.json")
            print(f"      {len(items)} items")
        if a.fix_errors:
            facts = json.loads((run_dir / "facts.json").read_text(encoding="utf-8"))
            draft = json.loads((run_dir / "draft.json").read_text(encoding="utf-8"))
            bad = {sec["key"] for sec in writer.sections(a.scope)
                   if sec["key"] not in draft or any(
                       i["level"] == "error" for i in validate.check_section(
                           sec, draft[sec["key"]].get("slots", {}), facts, items, draft[sec["key"]].get("numbers_used")))}
            print(f"[4/5] Uzbek text: rewriting only {', '.join(sorted(bad)) or 'nothing (no errors)'}")
            if bad:
                writer.run(run_dir, a.scope, m, only=bad)
        else:
            print("[4/5] Uzbek text, section by section")
            writer.run(run_dir, a.scope, m)
    print("[5/5] checks")
    n_err = _check(run_dir, a.scope)
    if n_err:
        print(f"PDF not made: {n_err} error(s) above (also in {run_dir / 'check.json'}).\n"
              f"To rewrite only the failing sections (cheap): run_report {period} {a.scope} --fix-errors")
        cost_line()
        return 1
    cost_line()
    if a.no_pdf:
        return 0
    from . import render  # noqa: PLC0415
    pdf = render.render(run_dir, a.scope)
    print(f"done: {pdf}")
    return 0


def _report_cmds(a) -> int:
    import json  # noqa: PLC0415

    from . import news, writer  # noqa: PLC0415
    run_dir = a.out / f"{a.period.upper()}_{a.scope}"
    period = a.period.upper()

    def llm():
        from .llm import LLM  # noqa: PLC0415
        return LLM(run_dir / "log.jsonl")

    if a.cmd == "report":
        return _report(a, run_dir, period)
    if a.cmd == "news":
        if a.from_file:
            items = news.load(a.from_file, period)
            (run_dir / "news.json").write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            items = news.collect(period, a.scope, llm(), run_dir / "news.json")
        print(f"{len(items)} news items -> {run_dir / 'news.json'}")
        return 0
    if a.cmd == "write":
        writer.run(run_dir, a.scope, llm())
        a.cmd = "check"
    if a.cmd == "check":
        return 1 if _check(run_dir, a.scope) else 0
    if a.cmd == "render":
        from . import render  # noqa: PLC0415
        print(render.render(run_dir, a.scope))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
