"""Exercise writer.run end to end with a stand-in model (no API key needed)."""
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from uyjoy import writer  # noqa: E402

FIX = Path(__file__).resolve().parents[1] / "runs" / "2026Q3_respublika"


class FakeLLM:
    """Writer role: first answer has a planted error, retry returns the clean draft.
    Editor role: returns the locked text unchanged."""

    def __init__(self, draft):
        self.draft, self.calls = draft, []

    def call(self, role, system, messages, tools=None, max_tokens=None):
        user = messages[-1]["content"]
        self.calls.append(role)
        if role == "editor":
            return user, [], {}
        key = next(s["key"] for s in writer.sections("respublika") if f"BOʻLIM: {s['title']}" in user)
        slots = dict(self.draft[key]["slots"])
        if key == "birlamchi" and "TEKSHIRUV XATOLARI" not in user:
            slots["hududlar"] = slots["hududlar"].replace("Xorazm (+15.0%)", "Xorazm (+5.0%)")
        return "```json\n" + json.dumps({"slots": slots, "numbers_used": []}, ensure_ascii=False) + "\n```", [], {}


def test_writer_retries_then_passes(tmp_path):
    if not (FIX / "draft.json").exists():
        return
    run = tmp_path / "run"
    run.mkdir()
    for f in ("facts.json", "news.json"):
        shutil.copy(FIX / f, run / f)
    draft = json.loads((FIX / "draft.json").read_text(encoding="utf-8"))
    llm = FakeLLM(draft)
    out = writer.run(run, "respublika", llm, retries=2)
    assert out["birlamchi"]["attempt"] == 2                      # planted error caught, re-asked
    assert all(not [i for i in s["issues"] if i["level"] == "error"] for s in out.values())
    assert out["birlamchi"]["slots"] == draft["birlamchi"]["slots"]   # editor pass kept numbers
    assert llm.calls.count("writer") == len(out) + 1
