import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from uyjoy import validate, writer  # noqa: E402

FACTS = {
    "report": {"period": "2026Q3", "som_vs_usd_pct": 2.0},
    "birlamchi": {
        "rows": [
            {"id": "hudud.prim.Buxoro", "name": "Buxoro", "value": 8.45, "qoq_pct": -1.9, "yoy_pct": 13.3, "status": "ok"},
            {"id": "hudud.prim.Xorazm", "name": "Xorazm", "value": 7.39, "qoq_pct": 6.8, "yoy_pct": 10.8, "status": "ok"},
            {"id": "hudud.prim.Namangan", "name": "Namangan", "value": 6.77, "qoq_pct": -6.9, "yoy_pct": -14.4, "status": "thin"},
            {"id": "hudud.prim.Qoraqalpogʻiston", "name": "Qoraqalpogʻiston", "value": None, "status": "hidden"},
        ],
        "top_up": ["Xorazm"], "top_down": ["Buxoro"],
    },
}
NEWS = [{"id": "n01", "topic": "ipoteka", "claim_uz": "…", "date": "2026-07-27", "outlet": "spot.uz",
         "numbers": [{"value": 13.1, "unit": "trln so'm", "what": "ipoteka"}], "geography": "respublika"}]
SEC = {"key": "birlamchi", "title": "T", "facts": ["report", "birlamchi"], "news_topics": ["ipoteka"],
       "slots": {"hududlar": {"words": [5, 80], "about": ""}}, "must_mention": ["birlamchi.top_up", "birlamchi.top_down"]}


def codes(text):
    return {i["code"] for i in validate.check_section(SEC, {"hududlar": text}, FACTS, NEWS) if i["level"] == "error"}


def test_clean_text_passes():
    t = ("2026-yil 3-choragida narxlar Xorazmda oshdi (+6.8%), Buxoroda esa pasaydi (-1.9%). "
         "Buxoro bir yilda (+13.3%) qimmatlashgan. Ipoteka 13.1 trln. soʻmga yetdi [n01].")
    assert codes(t.replace("Buxoroda", "Buxoro viloyatida")) == set()


def test_invented_number_is_caught():
    assert "number" in codes("Xorazmda narxlar 12.0% ga oshdi, Buxoroda pasaydi.")


def test_wrong_region_attribution_is_caught():
    # Published Q2 2025 report gave Uchtepa's value to Shayxontohur; same mistake here.
    assert "attribution" in codes("Narxlar Xorazm (-1.9%) va Buxoroda oʻzgardi.")


def test_unsigned_value_attribution_is_caught():
    # Published Q2 2025 report: Namangan yield 12.0% in text vs 10.1% in its own chart.
    assert "attribution" in codes("Xorazm (8.45 mln. soʻm/m²) va Buxoro.")
    assert "attribution" not in codes("Xorazm (7.39 mln. soʻm/m²) va Buxoro.")


def test_news_number_needs_its_marker():
    assert "number" in codes("Xorazm va Buxoro. Ipoteka 13.1 trln. soʻmga yetdi.")


def test_direction_and_orthography_and_hidden():
    assert "direction" in codes("Xorazm va Buxoroda narxlar oshdi (-1.9%).")
    assert "apostrophe" in codes("Xorazm va Buxoro. O'zbekistonda.")
    assert "hidden" in codes("Xorazm, Buxoro, Qoraqalpogʻistonda 5.45 mln.")


def test_coverage():
    assert "coverage" in codes("Narxlar Xorazmda oshdi.")


def test_editor_lock_roundtrip():
    s = "Buxoro (-1.9%) va 42 575 fuqaro [n01]."
    locked, held = writer.lock_numbers(s)
    assert "1.9" not in locked and "[n01]" not in locked
    assert writer.unlock(locked, held) == s
