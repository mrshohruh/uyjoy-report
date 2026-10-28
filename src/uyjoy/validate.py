"""Checks on the Uzbek text against the facts pack and the news items.

Errors block a section (the writer is asked again with the error list);
warnings go to the analyst's review sheet.
"""
from __future__ import annotations

import re

import yaml

from .config import CONFIG_DIR

GEO = yaml.safe_load((CONFIG_DIR / "geo.yaml").read_text(encoding="utf-8"))
NAMES = sorted(GEO["region_order"] + GEO["district_order"], key=len, reverse=True)
UP = re.compile(r"\b(oshdi|oshgan|oʻsdi|oʻsgan|qimmatlashdi|qimmatlashgan|koʻtarildi|ortdi|ortgan)\b")
DOWN = re.compile(r"\b(pasaydi|pasaygan|kamaydi|kamaygan|arzonlashdi|arzonlashgan|tushdi|tushgan|qisqardi)\b")
LEAD = re.compile(r"(eng yuqori|eng koʻp|yetakchi|eng tez|eng sezilarli)")
NUM = re.compile(r"\d{1,3}(?:[  ]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?")
MARK = re.compile(r"\[(n\d{2})\]")
SENT = re.compile(r"(?<=[.!?])\s+(?=[A-ZʻOʼ\"«(0-9])")


def news_value(v) -> float | None:
    """A news item's number as float, or None if it is not a number (e.g. a rating such as "BB").
    Accepts 6.2, "6,2", "6.2%", "1 200", "−3.5"."""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    t = str(v).strip().replace("\u2212", "-").replace("\u00a0", "").replace(" ", "").rstrip("%")
    t = t.replace(",", ".") if t.count(",") == 1 and "." not in t else t.replace(",", "")
    try:
        return float(t)
    except ValueError:
        return None


def _news_nums(items) -> list[float]:
    return [x for x in (news_value(n.get("value")) for n in items if isinstance(n, dict)) if x is not None]


def _num(s: str) -> float:
    return float(s.replace(" ", "").replace(" ", "").replace(",", "."))


def tokens(text: str):
    """Yield (value with sign, raw, start, end, followed_by) for every number in the text."""
    for m in NUM.finditer(text):
        raw, i = m.group(0), m.start()
        prev = text[i - 1] if i else ""
        prev2 = text[i - 2] if i > 1 else " "
        sign = 1
        if prev in "-−" and (prev2 in " (\n" or i == 1):
            sign = -1
        yield sign * _num(raw), raw, i, m.end(), text[m.end():m.end() + 8]


def _leaves(obj, path=""):
    if isinstance(obj, bool) or obj is None:
        return
    if isinstance(obj, (int, float)):
        yield path, float(obj)
    elif isinstance(obj, dict):
        base = obj.get("id", path) if isinstance(obj.get("id"), str) else path
        for k, v in obj.items():
            yield from _leaves(v, f"{base}.{k}" if base else k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _leaves(v, f"{path}[{i}]")


def _decimals(raw: str) -> int:
    m = re.search(r"[.,](\d+)$", raw)
    return len(m.group(1)) if m else 0


def _rows(slice_: dict) -> dict[str, list[dict]]:
    """name -> table rows (any block with `rows`) found in the slice."""
    out: dict[str, list[dict]] = {}

    def walk(o):
        if isinstance(o, dict):
            if isinstance(o.get("rows"), list):
                for r in o["rows"]:
                    if isinstance(r, dict) and "name" in r:
                        out.setdefault(r["name"], []).append(r)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(slice_)
    return out


def _status_names(slice_: dict, status: str) -> set[str]:
    return {n for n, rs in _rows(slice_).items() if all(r.get("status") == status for r in rs)}


def check_text(slot: str, text: str, slice_: dict, news: list[dict], words: tuple[int, int] | None) -> list[dict]:
    issues = []
    text = text.replace("**", "")   # bold lead-ins are markup, not text

    def err(code, msg, level="error"):
        issues.append({"level": level, "code": code, "slot": slot, "message": msg})

    facts_vals = list(_leaves(slice_))
    news_by_id = {n["id"]: n for n in news}
    rows = _rows(slice_)
    hidden, thin = _status_names(slice_, "hidden"), _status_names(slice_, "thin")

    # Orthography
    for m in re.finditer(r"[OoGg]['’‘`]", text):
        err("apostrophe", f"'{text[max(0, m.start()-6):m.end()+4]}': oʻ/gʻ uchun U+02BB (ʻ) ishlating")
    if re.search(r"[А-Яа-яЁё]", text):
        err("cyrillic", "matnda kirill harflari bor")
    for mk in MARK.findall(text):
        if mk not in news_by_id:
            err("marker", f"[{mk}] yangiliklar roʻyxatida yoʻq")
    if words:
        n = len(text.split())
        if n > words[1] * 1.3:
            err("length", f"{n} soʻz, chegarasi {words[1]}")
        elif n < words[0] * 0.7 or n > words[1]:
            err("length", f"{n} soʻz, kutilgan {words[0]}–{words[1]}", "warning")

    for sent in SENT.split(text):
        marks = MARK.findall(sent)
        cited = [news_by_id[m] for m in marks if m in news_by_id]
        for val, raw, s, e, after in tokens(sent):
            d = _decimals(raw)
            if re.match(r"\s*-?\s*(yil|yildan|yilgacha|yilda)", after) and 2000 <= abs(val) <= 2035:
                continue
            if re.match(r"-?\s*(chora[kg]|xona)", after) and 1 <= abs(val) <= 5 and d == 0:
                continue
            if re.match(r"-(rasm|jadval)", after) and d == 0 and 1 <= abs(val) <= 40:
                continue    # a pointer to a figure or table ("3-rasm"), not a figure from the data
            if sent[e:e + 1] == "]" and sent[max(0, s - 2):s] == "[n":
                continue
            if abs(val) == 100 and "indeks" in sent.lower():
                continue
            # same precision only: "7.4" must not match a stored 7.43
            in_facts = [p for p, v in facts_vals if round(abs(v), d) == abs(val)
                        and round(v, d) == round(v, 6) and (val >= 0 or v < 0)]
            in_news = [n["id"] for n in cited for x in _news_nums(n.get("numbers") or [])
                       if round(abs(x), d) == abs(val)]
            if not in_facts and not in_news:
                where = "yangilik belgisisiz" if any(round(abs(x), d) == abs(val)
                                                     for n in news for x in _news_nums(n.get("numbers") or [])) \
                    else "hech qayerda"
                err("number", f"'{raw}' raqami maʼlumotlarda yoʻq ({where}): «{sent[:90]}…»")

        # A figure in brackets right after a place name must belong to that place:
        # signed % -> its change; unsigned % or level -> its value (or a change).
        for m in re.finditer(r"\(([+\-−]?)(\d+(?:[.,]\d+)?)\s*(%|mln|ming)", sent):
            sign, raw, unit = m.groups()
            val = _num(raw) * (-1 if sign in ("-", "−") else 1)
            before = sent[:m.start()]
            name = max(((before.rfind(nm), nm) for nm in NAMES if nm in before), default=(-1, None))[1]
            if not name or name not in rows or before.rfind(name) < len(before) - 30:
                continue
            keys = ("qoq_pct", "yoy_pct") if sign else ("value", "qoq_pct", "yoy_pct")
            cands = [r.get(k) for r in rows[name] for k in keys if r.get(k) is not None]
            if not sign:
                cands = [abs(c) for c in cands]
            d = _decimals(raw)
            if not any(round(c, d) == round(val, d) for c in cands):
                err("attribution", f"{name} uchun ({sign}{raw}{unit}) maʼlumotlarga mos emas; "
                                   f"mavjud: {cands or 'qiymat yoʻq'}")

        signed = [v for v, raw, s, e, a in tokens(sent) if sent[max(0, s - 1):s] in "+-−" and "%" in sent[e:e + 2]]
        up, down = bool(UP.search(sent)), bool(DOWN.search(sent))
        if signed and up != down:
            if up and all(v < 0 for v in signed):
                err("direction", f"oʻsish feʼli, lekin barcha oʻzgarishlar manfiy: «{sent[:90]}…»")
            if down and all(v > 0 for v in signed):
                err("direction", f"pasayish feʼli, lekin barcha oʻzgarishlar musbat: «{sent[:90]}…»")

        for nm in hidden:
            if nm in sent and NUM.search(sent):
                err("hidden", f"{nm}: eʼlonlar soni juda kam, raqam bilan tilga olinmasin")
        for nm in thin:
            if nm in sent and LEAD.search(sent):
                err("thin", f"{nm}: eʼlonlar soni kam, yetakchi sifatida koʻrsatilmasin", "warning")
    return issues


def check_section(sec: dict, slots: dict, facts: dict, news: list[dict],
                  numbers_used: list[dict] | None = None) -> list[dict]:
    from .writer import facts_slice, must_mention  # noqa: PLC0415
    sl = facts_slice(facts, sec)
    issues = []
    for k, spec in sec["slots"].items():
        if not slots.get(k):
            issues.append({"level": "error", "code": "missing", "slot": k, "message": "slot boʻsh"})
            continue
        issues += check_text(k, slots[k], sl, news, tuple(spec["words"]))
    joined = " ".join(slots.values())
    issues += check_numbers_used(numbers_used or [], facts, news)
    brk = (facts.get("report") or {}).get("series_break")
    kw = (brk or {}).get("keyword_uz", "qayta ishlan")
    if brk and sec.get("note_break") and kw not in joined:
        issues.append({"level": "error", "code": "series_break", "slot": "*",
                       "message": f"{brk['month']} dagi maʼlumotlar oʻzgarishi aytilmagan (kalit ibora: «{kw}»)"})
    by_id = {n["id"]: n for n in news}
    for mk in sorted(set(MARK.findall(joined))):
        if mk in by_id and by_id[mk]["topic"] not in sec["news_topics"]:
            issues.append({"level": "warning", "code": "marker_topic", "slot": "*",
                           "message": f"[{mk}] mavzusi ({by_id[mk]['topic']}) bu boʻlimga tegishli emas: manbani tekshiring"})
    for nm in must_mention(facts, sec):
        if nm not in joined:
            issues.append({"level": "error", "code": "coverage", "slot": "*", "message": f"{nm} tilga olinmagan"})
    return issues


def check_numbers_used(items: list[dict], facts: dict, news: list[dict]) -> list[dict]:
    """The writer lists every number with the facts id it took it from; the value at that id must match.

    This catches a real figure attached to the wrong thing (e.g. another region's like-for-like change),
    which the existence check alone cannot see.
    """
    issues = []
    by_path = dict(_leaves(facts))
    news_ids = {n["id"] for n in news}

    def resolve(ref: str):
        """Value at an id path ("indeks.value") or a plain key path ("uy_joy_indeksi.value",
        "uy_joy_indeksi.highest_regions.Xorazm.value"); None if absent, "skip" if not a number."""
        if ref in by_path:
            return by_path[ref]
        obj = facts
        for part in ref.split("."):
            if isinstance(obj, dict) and part in obj:
                obj = obj[part]
            elif isinstance(obj, dict) and isinstance(obj.get("rows"), list):
                obj = next((r for r in obj["rows"] if isinstance(r, dict) and r.get("name") == part), None)
            elif isinstance(obj, list):
                obj = next((r for r in obj if isinstance(r, dict) and r.get("name") == part), None)
            else:
                return None
            if obj is None:
                return None
        if isinstance(obj, bool) or not isinstance(obj, (int, float)):
            return "skip" if isinstance(obj, str) else None
        return float(obj)
    for it in items:
        text, ref = str(it.get("text", "")), str(it.get("id", ""))
        m = NUM.search(text)
        if not m or ref in news_ids:
            continue
        raw = m.group(0)
        val = _num(raw) * (-1 if re.search(r"[-−]\s*$", text[:m.start()]) else 1)
        target = resolve(ref)
        if target == "skip":
            continue
        if target is None:
            issues.append({"level": "warning", "code": "numbers_used", "slot": "*",
                           "message": f"'{text}': id {ref} maʼlumotlarda topilmadi"})
            continue
        d = _decimals(raw)
        if round(abs(target), d) != abs(val):
            issues.append({"level": "error", "code": "numbers_used", "slot": "*",
                           "message": f"'{text}' {ref} qiymatiga ({target}) mos emas"})
    return issues
