from pathlib import Path
from bewerber.tailoring.render import render_lebenslauf, render_anschreiben
from bewerber.tailoring.customize import CustomizedResume, CustomBerufserfahrung
from bewerber.tailoring.anschreiben import AnschreibenContent
from bewerber.shared.profile_schema import (
    MasterProfile, Person, Berufserfahrung, Project, Ausbildung, Sprache, Zertifikat,
)


def _profile() -> MasterProfile:
    return MasterProfile(
        person=Person(name="Steve Eigenwillig", email="s@x.de", phone="+49 123",
                      adresse="Leipzig"),
        berufsprofil="Erfahrener Manager.",
        zielposition=["KI Manager"],
        ausbildung=[Ausbildung(art="Techniker", institution="RHS Chemnitz", jahr="2015")],
        berufserfahrung=[
            Berufserfahrung(position="PM", firma="Acme", von="2020-01", bis="2024-08",
                            aufgaben=["a1"], erfolge=["e1"], skills=["Python"]),
        ],
        projekte=[
            Project(id="1-x", titel="X", kurzbeschreibung="Beschreibung X",
                    rolle="Lead", skills_fachlich=["Python", "n8n"]),
        ],
        zertifikate=[Zertifikat(name="REFA", aussteller="REFA")],
        sprachen=[Sprache(sprache="Deutsch", niveau="C2")],
    )


def _customized() -> CustomizedResume:
    return CustomizedResume(
        berufsprofil_zugespitzt="Zugeschnitten.",
        berufserfahrung=[
            CustomBerufserfahrung(position="PM", firma="Acme", von="2020-01", bis="2024-08",
                                   aufgaben=["a1 (tailored)"], erfolge=["e1"], skills=["Python"]),
        ],
        projekte_hervorheben=["1-x"],
        skills_reihenfolge=["Python", "n8n", "Leadership"],
    )


def test_render_lebenslauf_returns_pdf_bytes(tmp_path):
    pdf = render_lebenslauf(_profile(), _customized())
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 1000  # has actual content


def test_render_lebenslauf_includes_highlighted_projects():
    """Projects in projekte_hervorheben must appear in PDF (we check via text extraction)."""
    import pdfplumber
    import io
    pdf_bytes = render_lebenslauf(_profile(), _customized())
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        text = "\n".join((p.extract_text() or "") for p in pdf.pages)
    assert "Steve Eigenwillig" in text
    assert "Zugeschnitten." in text
    assert "Acme" in text
    assert "X" in text  # project title
    assert "Python" in text


def test_render_anschreiben_returns_pdf_bytes():
    anschreiben = AnschreibenContent(
        anrede="Sehr geehrte Damen und Herren,",
        einleitung="Mit großem Interesse...",
        hauptteil="Meine Erfahrung als Projektmanager bei Acme...",
        schluss="Über die Einladung würde ich mich freuen.",
        gruss="Mit freundlichen Grüßen\nSteve Eigenwillig",
    )
    pdf = render_anschreiben(
        _profile(),
        anschreiben,
        firma="BMW Group",
        rolle="KI Manager",
        datum="12.06.2026",
        kontakt_name=None,
    )
    assert pdf.startswith(b"%PDF")

    import pdfplumber
    import io
    with pdfplumber.open(io.BytesIO(pdf)) as p:
        text = "\n".join((page.extract_text() or "") for page in p.pages)
    assert "Sehr geehrte Damen und Herren" in text
    assert "Bewerbung als KI Manager" in text
    assert "BMW Group" in text
