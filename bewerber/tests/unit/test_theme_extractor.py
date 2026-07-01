from pathlib import Path
from bewerber.shared.theme import Theme
from bewerber.tailoring.theme_extractor import harvest_style_facts, extract_theme


def _make_pdf(tmp_path) -> Path:
    # Minimales PDF via pdfplumber-kompatibler Erzeugung (reportlab falls da, sonst skip)
    import pytest
    rl = pytest.importorskip("reportlab.pdfgen.canvas")
    p = tmp_path / "cv.pdf"
    c = rl.Canvas(str(p))
    c.setFont("Helvetica-Bold", 18); c.drawString(72, 750, "PROFIL")
    c.setFont("Helvetica", 11); c.drawString(72, 730, "Lorem ipsum dolor")
    c.setFont("Helvetica-Bold", 18); c.drawString(72, 700, "BERUFSERFAHRUNG")
    c.save()
    return p


def test_harvest_pdf_returns_facts(tmp_path):
    p = _make_pdf(tmp_path)
    facts = harvest_style_facts(p)
    assert isinstance(facts, dict)
    assert facts.get("fonts")            # mind. eine Fontangabe
    assert "sections" in facts           # erkannte Überschriften (evtl. leer, aber Key da)


def test_extract_theme_uses_llm(mocker, tmp_path):
    p = _make_pdf(tmp_path)
    fake = Theme(id="x", name="Mein CV", accent_color="#123456", font_family="helvetica")
    llm = mocker.Mock()
    llm.structured.return_value = fake
    t = extract_theme(p, name="Mein CV", llm=llm)
    assert t.name == "Mein CV" and t.accent_color == "#123456"
    # LLM wurde mit den geernteten Fakten im user-Prompt aufgerufen
    _, kwargs = llm.structured.call_args
    assert "PROFIL" in kwargs["user"] or "fonts" in kwargs["user"].lower()
