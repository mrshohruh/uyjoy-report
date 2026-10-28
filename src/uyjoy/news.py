"""News module: find, filter and structure cited news for one reporting period.

One model call per topic, with the server-side web search tool. The model must
return items only for URLs the search actually returned in this call; anything
else is dropped. Items outside the date window are dropped. News explains the
numbers; it never replaces them.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import yaml

from .config import CONFIG_DIR

MONTHS_UZ = ["yanvar", "fevral", "mart", "aprel", "may", "iyun", "iyul", "avgust",
             "sentabr", "oktabr", "noyabr", "dekabr"]
TOPICS = ("stavka", "ipoteka", "narx", "ijara", "qurilish", "tartibga_solish", "valyuta")

SYSTEM = """Siz O'zbekiston uy-joy va ijara bozori bo'yicha tahliliy hisobot uchun yangiliklarni yig'uvchi \
tadqiqotchisiz. Faqat web_search vositasi shu so'rovda qaytargan sahifalardan foydalaning.

Qoidalar:
- Faqat {start} dan {end} gacha e'lon qilingan materiallar.
- Avval rasmiy manbalar ({official}), keyin nashrlar ({news}).
- Har bir element bitta aniq faktni bildirsin: kim, nima, qachon, raqam bo'lsa raqami bilan.
- claim_uz: o'zbek (lotin) tilida, 1 gap, o'z so'zlaringiz bilan (iqtibos emas), 30 so'zdan oshmasin.
- Taxmin, reklama, e'lon va sharhlarni fakt sifatida bermang; ekspert fikri bo'lsa "X fikricha" deb yozing.
- Raqamlarni manbadagidek, birligi bilan bering; manbada yo'q raqamni qo'shmang.
- Tegishli hech narsa topilmasa, bo'sh ro'yxat qaytaring.

Javob faqat JSON ro'yxat (```json bloki ichida), har bir element:
{{"topic": "{topic}", "geography": "respublika|toshkent|<viloyat nomi>", "date": "YYYY-MM-DD",
  "outlet": "kun.uz", "url": "...", "title": "...", "claim_uz": "...",
  "numbers": [{{"value": 14.0, "unit": "%", "what": "asosiy stavka"}}],
  "official": true, "relevance": 1-5}}"""


def window(period: str, after_days: int) -> tuple[date, date]:
    p = pd.Period(period, "Q")
    return p.start_time.date(), p.end_time.date() + timedelta(days=after_days)


def _queries(topic: dict, period: str) -> list[str]:
    p = pd.Period(period, "Q")
    fmt = {"year": p.year, "quarter_uz": f"{p.quarter}-chorak",
           "month_name_uz": MONTHS_UZ[p.end_time.month - 1]}
    return [q.format(**fmt) for lang in ("uz", "ru") for q in topic["queries"].get(lang, [])]


NEWS_SCHEMA = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "geography": {"type": "string"}, "date": {"type": "string"}, "outlet": {"type": "string"},
            "url": {"type": "string"}, "title": {"type": "string"}, "claim_uz": {"type": "string"},
            "numbers": {"type": "array", "items": {
                "type": "object",
                "properties": {"value": {"type": "number"}, "unit": {"type": "string"}, "what": {"type": "string"}},
                "required": ["value", "unit", "what"], "additionalProperties": False}},
            "relevance": {"type": "integer"},
        },
        "required": ["geography", "date", "outlet", "url", "title", "claim_uz", "numbers", "relevance"],
        "additionalProperties": False}}},
    "required": ["items"],
    "additionalProperties": False,
}

FORMAT_SYSTEM = """Quyidagi tadqiqot matnidan "{topic}" mavzusidagi yangilik elementlarini ajrating.
Faqat matnda yozilgan va pastdagi URL roʻyxatidagi sahifalarga tegishli faktlar; yangi fakt yoki raqam qoʻshmang.
Davr: {start} dan {end} gacha. Sana YYYY-MM-DD. claim_uz: oʻzbek (lotin) tilida bitta gap. relevance: 1-5.
Hech narsa topilmasa, "items" boʻsh roʻyxat boʻlsin."""


def _norm_url(u: str) -> str:
    """Compare URLs loosely: no scheme, no www, no trailing slash, no query or fragment."""
    u = str(u or "").strip().lower().split("#")[0].split("?")[0]
    u = u.split("://", 1)[-1].removeprefix("www.")
    return u.rstrip("/")


def _items_from(text: str) -> list[dict]:
    from .llm import parse_json  # noqa: PLC0415
    try:
        got = parse_json(text)
    except (ValueError, json.JSONDecodeError):
        return []
    if isinstance(got, dict):
        got = got.get("items", [])
    return [x for x in got if isinstance(x, dict)] if isinstance(got, list) else []


def collect(period: str, scope: str, llm, out_path: Path) -> list[dict]:
    """Search each topic, structure the findings, filter them. Writes news.json and news_dropped.json."""
    from .llm import search_results  # noqa: PLC0415
    cfg = yaml.safe_load((CONFIG_DIR / "news_queries.yaml").read_text(encoding="utf-8"))
    start, end = window(period, cfg["after_days"])
    items, summary = [], []
    for key, topic in cfg["topics"].items():
        if scope not in topic["scope"]:
            continue
        system = SYSTEM.format(start=start, end=end, official=", ".join(cfg["official_domains"]),
                               news=", ".join(cfg["news_domains"]), topic=key)
        user = (f"Mavzu: {topic['label']}. Qamrov: {scope}. Davr: {period}.\n"
                f"Quyidagi so'rovlardan boshlang, kerak bo'lsa aniqlashtiring:\n- "
                + "\n- ".join(_queries(topic, period))
                + f"\nEng muhim {cfg['max_items_per_topic']} tagacha element qaytaring.")
        tool = dict(llm.cfg["web_search"], name="web_search")
        text, blocks, _ = llm.call("news", system, [{"role": "user", "content": user}], tools=[tool])
        seen = search_results(blocks)
        got = _items_from(text)
        if not got and seen and text.strip():
            # The search answer was not usable JSON: turn it into JSON with a second, tool-free call.
            urls = "\n".join(f"- {u} ({v.get('title') or ''})" for u, v in seen.items())
            ftext, _, _ = llm.call(
                "news", FORMAT_SYSTEM.format(topic=topic["label"], start=start, end=end),
                [{"role": "user", "content": f"MATN:\n{text}\n\nURL ROʻYXATI:\n{urls}"}],
                output_schema=NEWS_SCHEMA)
            got = _items_from(ftext)
        seen_n = {_norm_url(u) for u in seen}
        for it in got:
            it["topic"] = key
            it["_returned_by_search"] = _norm_url(it.get("url")) in seen_n
        items += got
        summary.append((key, len(seen), len(got)))
    dropped: list[dict] = []
    kept = clean_items(items, start, end, cfg, dropped)
    out_path.write_text(json.dumps(kept, ensure_ascii=False, indent=2), encoding="utf-8")
    out_path.with_name("news_dropped.json").write_text(json.dumps(dropped, ensure_ascii=False, indent=2),
                                                       encoding="utf-8")
    for key, n_seen, n_got in summary:
        n_kept = sum(1 for k in kept if k["topic"] == key)
        print(f"      {key:16s} {n_seen:2d} pages found, {n_got:2d} items, {n_kept:2d} kept")
    if dropped:
        print(f"      {len(dropped)} item(s) dropped, reasons in {out_path.with_name('news_dropped.json').name}")
    return kept


def _parse_date(v) -> date | None:
    v = str(v or "").strip()
    for f in (lambda x: date.fromisoformat(x[:10]),
              lambda x: date(int(x[6:10]), int(x[3:5]), int(x[0:2]))):   # 16.09.2026
        try:
            return f(v)
        except (ValueError, IndexError):
            continue
    return None


def _clean_numbers(nums) -> list[dict]:
    """Keep numbers whose value is numeric (as a float); a non-numeric value such as a rating ("BB")
    is kept as text in `what`, with no value, so it cannot be matched or break the checks."""
    from .validate import news_value  # noqa: PLC0415
    out = []
    for n in nums if isinstance(nums, list) else []:
        if not isinstance(n, dict):
            continue
        v = news_value(n.get("value"))
        if v is None:
            if n.get("value") not in (None, ""):
                out.append({"value": None, "unit": str(n.get("unit") or ""),
                            "what": f"{n.get('what') or ''} {n.get('value')}".strip()})
            continue
        out.append({"value": v, "unit": str(n.get("unit") or ""), "what": str(n.get("what") or "")})
    return out


def clean_items(items: list[dict], start: date, end: date, cfg: dict, dropped: list | None = None) -> list[dict]:
    """Keep items with a URL the search returned, a date in the window and a claim; fill optional fields;
    drop exact repeats; number them. Every dropped item is appended to `dropped` with its reason."""
    kept, seen = [], set()   # one article can carry several facts; drop exact repeats only

    def drop(it, why):
        if dropped is not None:
            dropped.append({"reason": why, **{k: v for k, v in it.items() if not k.startswith("_")}})

    for it in items:
        if it.get("topic") not in TOPICS:
            drop(it, "unknown topic"); continue
        if not it.get("url") or not str(it.get("claim_uz", "")).strip():
            drop(it, "no url or no claim"); continue
        if it.get("_returned_by_search") is False:
            drop(it, "url not among the pages the search returned"); continue
        d = _parse_date(it.get("date"))
        if d is None:
            drop(it, f"unreadable date {it.get('date')!r}"); continue
        if not (start <= d <= end):
            drop(it, f"date {d} outside {start}..{end}"); continue
        key = (_norm_url(it["url"]), it["claim_uz"].strip().lower())
        if key in seen:
            drop(it, "repeat"); continue
        seen.add(key)
        dom = _norm_url(it["url"]).split("/")[0]
        it.update(date=d.isoformat(),
                  official=any(dom == o or dom.endswith("." + o) for o in cfg["official_domains"]),
                  outlet=it.get("outlet") or dom, title=it.get("title") or "",
                  geography=it.get("geography") or "respublika",
                  numbers=_clean_numbers(it.get("numbers")))
        try:
            it["relevance"] = int(it.get("relevance") or 3)
        except (TypeError, ValueError):
            it["relevance"] = 3
        it.pop("_returned_by_search", None)
        kept.append(it)
    kept.sort(key=lambda x: (not x["official"], -x["relevance"], x["date"]))
    for i, it in enumerate(kept, 1):
        it["id"] = f"n{i:02d}"
    return kept


def load(path: Path, period: str) -> list[dict]:
    """Load a news.json written by `collect` or by hand, re-applying the same filters."""
    cfg = yaml.safe_load((CONFIG_DIR / "news_queries.yaml").read_text(encoding="utf-8"))
    start, end = window(period, cfg["after_days"])
    return clean_items(json.loads(path.read_text(encoding="utf-8")), start, end, cfg)
