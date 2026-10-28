"""Writing layer: one Claude call per section, checked, retried with the check
failures, then an editor pass that cannot touch numbers or source markers."""
from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from . import validate
from .config import ROOT
from .llm import parse_json

PROMPTS = ROOT / "prompts"


def get_path(obj, path: str):
    for part in path.split("."):
        if obj is None:
            return None
        obj = obj.get(part) if isinstance(obj, dict) else None
    return obj


def sections(scope: str) -> list[dict]:
    return yaml.safe_load((PROMPTS / "sections.yaml").read_text(encoding="utf-8"))[scope]


def facts_slice(facts: dict, sec: dict) -> dict:
    out = {}
    for p in sec["facts"]:
        v = get_path(facts, p)
        if v is not None:
            out[p] = v
    return out


def news_slice(news: list[dict], sec: dict) -> list[dict]:
    keep = ("id", "date", "outlet", "claim_uz", "numbers", "geography")
    return [{k: n[k] for k in keep} for n in news if n["topic"] in sec["news_topics"]]


def must_mention(facts: dict, sec: dict) -> list[str]:
    names = []
    for p in sec.get("must_mention", []):
        v = get_path(facts, p) or []
        names += [x if isinstance(x, str) else x.get("name") for x in v]
    return list(dict.fromkeys(names))


def examples(sec: dict) -> str:
    ex = yaml.safe_load((ROOT / "examples" / "narrative_uz.yaml").read_text(encoding="utf-8"))
    keys = [k for k in ex if k == sec["key"] or k.startswith(sec["key"] + ".")]
    return "\n\n".join(ex[k] for k in keys)


def system_prompt() -> str:
    return ((PROMPTS / "system_writer.md").read_text(encoding="utf-8") + "\n\n"
            + (PROMPTS / "style_guide_uz.md").read_text(encoding="utf-8"))


def figures_for(sec: dict) -> list[str]:
    """Numbered figures and tables of the section, so the text can point to them ("3-rasm", "2-jadval")."""
    f = ROOT / "templates" / "figures.yaml"
    if not f.exists():
        return []
    out = []
    for scope in yaml.safe_load(f.read_text(encoding="utf-8")).values():
        for kind, word in (("figures", "rasm"), ("tables", "jadval")):
            for i, x in enumerate(scope.get(kind, []), 1):
                if x["section"] == sec["key"]:
                    out.append(f"{i}-{word}: {x['title']}")
    return out


def user_prompt(sec: dict, facts: dict, news: list[dict], prior: dict | None, feedback: list[dict] | None) -> str:
    figs = figures_for(sec)
    parts = [
        f"BOʻLIM: {sec['title']}",
        "SLOTS:\n" + "\n".join(f"- {k}: {v['words'][0]}–{v['words'][1]} soʻz. {v['about']}" for k, v in sec["slots"].items()),
        "MUST_MENTION: " + (", ".join(must_mention(facts, sec)) or "—"),
        "FACTS:\n```json\n" + json.dumps(facts_slice(facts, sec), ensure_ascii=False, indent=1) + "\n```",
        "NEWS:\n```json\n" + json.dumps(news_slice(news, sec), ensure_ascii=False, indent=1) + "\n```",
        "NAMUNA:\n" + (examples(sec) or "—"),
        "RASMLAR VA JADVALLAR (matnda ishora qiling, masalan «(3-rasm)»; raqamlarini takrorlab sanamang):\n"
        + ("\n".join(figs) or "—"),
    ]
    if prior:
        parts.append("OLDINGI BOʻLIMLAR MATNI (xulosalar shulardan olinadi, yangi raqam qoʻshilmaydi):\n"
                     + json.dumps(prior, ensure_ascii=False, indent=1))
    if feedback:
        parts.append("TEKSHIRUV XATOLARI — tuzating va butun javobni qayta bering:\n"
                     + "\n".join(f"- [{f['slot']}] {f['message']}" for f in feedback if f["level"] == "error"))
    return "\n\n".join(parts)


LOCK = re.compile(r"\[n\d{2}\]|[+\-−]?\d[\d  ]*(?:[.,]\d+)?%?")


def lock_numbers(text: str) -> tuple[str, list[str]]:
    held = []

    def sub(m):
        held.append(m.group(0))
        return f"⟦{len(held)}⟧"
    return LOCK.sub(sub, text), held


def unlock(text: str, held: list[str]) -> str:
    for i, h in enumerate(held, 1):
        if text.count(f"⟦{i}⟧") != 1:
            raise ValueError(f"editor changed placeholder {i}")
        text = text.replace(f"⟦{i}⟧", h)
    if re.search(r"⟦\d+⟧", text):
        raise ValueError("editor invented a placeholder")
    return text


EDITOR_SYSTEM = (
    "Siz oʻzbek tilidagi tahliliy matn muharririsiz. Faqat grammatika, imlo (oʻ/gʻ U+02BB bilan, tutuq U+02BC), "
    "uslub va ravonlikni tuzating. ⟦1⟧ kabi belgilarni aynan saqlang: oʻchirmang, koʻchirmang, qoʻshmang. "
    "Maʼnoni, faktlarni va hudud nomlarini oʻzgartirmang. Javob faqat tuzatilgan matn."
)


def edit(llm, text: str) -> str:
    locked, held = lock_numbers(text)
    out, _, _ = llm.call("editor", EDITOR_SYSTEM, [{"role": "user", "content": locked}])
    try:
        return unlock(out.strip(), held)
    except ValueError:
        return text   # keep the unedited text rather than risk a changed number


def section_schema(sec: dict) -> dict:
    """JSON schema for one section's answer: every slot as a string, plus numbers_used and notes."""
    return {
        "type": "object",
        "properties": {
            "slots": {"type": "object",
                      "properties": {k: {"type": "string"} for k in sec["slots"]},
                      "required": list(sec["slots"]), "additionalProperties": False},
            "numbers_used": {"type": "array", "items": {
                "type": "object", "properties": {"text": {"type": "string"}, "id": {"type": "string"}},
                "required": ["text", "id"], "additionalProperties": False}},
            "notes": {"type": "string"},
        },
        "required": ["slots", "numbers_used"],
        "additionalProperties": False,
    }


def _read_answer(text: str) -> dict:
    try:
        out = json.loads(text)
    except json.JSONDecodeError:
        out = parse_json(text)
    if not isinstance(out, dict) or not isinstance(out.get("slots"), dict):
        raise ValueError("javobda 'slots' obyekti yoʻq")
    return out


def write_section(llm, sec: dict, facts: dict, news: list[dict], prior: dict | None, retries: int,
                  raw_dir: Path | None = None) -> dict:
    """Ask for one section (structured JSON), check it, re-ask with the errors; then the number-locked edit.

    Never raises on a bad answer: if no attempt gives a usable answer, the section comes back empty with an
    error issue, so the run finishes, the checks report it and the PDF is not made. Raw answers are kept in
    raw_dir for diagnosis.
    """
    feedback, out, last_err = None, None, ""
    for attempt in range(retries + 1):
        text, _, usage = llm.call("writer", system_prompt(),
                                  [{"role": "user", "content": user_prompt(sec, facts, news, prior, feedback)}],
                                  output_schema=section_schema(sec))
        if raw_dir is not None:
            raw_dir.mkdir(parents=True, exist_ok=True)
            (raw_dir / f"{sec['key']}_{attempt + 1}.txt").write_text(text, encoding="utf-8")
        try:
            cand = _read_answer(text)
        except (ValueError, json.JSONDecodeError) as e:
            cut = usage.get("stop_reason") == "max_tokens" if isinstance(usage, dict) else False
            last_err = ("javob max_tokens chegarasida kesilgan" if cut else f"javobni oʻqib boʻlmadi: {e}")
            feedback = [{"level": "error", "slot": "*", "message": last_err + "; butun javobni qayta bering"}]
            continue
        out = cand
        issues = validate.check_section(sec, out.get("slots", {}), facts, news, out.get("numbers_used"))
        out["attempt"] = attempt + 1
        out["issues"] = issues
        if not any(i["level"] == "error" for i in issues):
            break
        feedback = issues
    if out is None:
        return {"slots": {}, "numbers_used": [], "attempt": retries + 1, "failed": True,
                "issues": [{"level": "error", "code": "writer", "slot": "*",
                            "message": f"{retries + 1} urinishda ham yaroqli javob olinmadi ({last_err})"}]}
    sl = facts_slice(facts, sec)

    def n_err(slot, text):
        words = tuple(sec["slots"][slot]["words"]) if slot in sec["slots"] else None
        return sum(i["level"] == "error" for i in validate.check_text(slot, text, sl, news, words))

    edited = {}
    for k, v in out.get("slots", {}).items():
        e = edit(llm, v)
        edited[k] = e if n_err(k, e) <= n_err(k, v) else v     # the editor may not break a passing text
    out["slots"] = edited
    out["issues"] = validate.check_section(sec, out["slots"], facts, news, out.get("numbers_used"))
    return out


def run(run_dir: Path, scope: str, llm, retries: int = 2, only: set | None = None) -> dict:
    """Write every section, or with `only` rewrite just those sections and keep the rest of draft.json."""
    facts = json.loads((run_dir / "facts.json").read_text(encoding="utf-8"))
    news = json.loads((run_dir / "news.json").read_text(encoding="utf-8")) if (run_dir / "news.json").exists() else []
    draft, prior = {}, {}
    if only is not None and (run_dir / "draft.json").exists():
        draft = json.loads((run_dir / "draft.json").read_text(encoding="utf-8"))
    for sec in sections(scope):
        if only is not None and sec["key"] not in only and sec["key"] in draft:
            prior[sec["key"]] = draft[sec["key"]]["slots"]
            continue
        res = write_section(llm, sec, facts, news, prior if sec.get("after_sections") else None, retries,
                            raw_dir=run_dir / "raw")
        bad = [i for i in res.get("issues", []) if i["level"] == "error"]
        print(f"      {sec['key']}: attempt {res.get('attempt')}, "
              + ("ok" if not bad else f"{len(bad)} error(s) left"))
        draft[sec["key"]] = res
        prior[sec["key"]] = res["slots"]
    (run_dir / "draft.json").write_text(json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8")
    return draft
