from pathlib import Path
from bewerber.tailoring.render import render_lebenslauf, render_anschreiben
from bewerber.tailoring.customize import (
    CustomizedResume,
    CustomBerufserfahrung,
    ProjekterfahrungBlock,
    SkillKategorien,
)
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
            CustomBerufserfahrung(
                position="PM", firma="Acme", von="2020-01", bis="2024-08",
                werdegang_bullets=["High-level a1", "High-level a2"],
                projekterfahrung=[
                    ProjekterfahrungBlock(
                        titel="Workflow-Automatisierung mit n8n",
                        aufgaben=["b1", "b2"],
                        ergebnisse=["1,5 h/Tag → 10 min/Tag"],
                    ),
                ],
            ),
        ],
        skills_kategorisiert=SkillKategorien(
            projektmanagement=["Projektplanung", "Stakeholder-Management"],
            automatisierung_ki=["n8n", "Python"],
        ),
    )


def test_render_lebenslauf_returns_pdf_bytes(tmp_path):
    pdf = render_lebenslauf(_profile(), _customized())
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 1000  # has actual content


def test_render_lebenslauf_includes_thematic_blocks_and_categorized_skills():
    """Thematic blocks + categorized skills + werdegang bullets appear in the rendered PDF."""
    import pdfplumber
    import io
    pdf_bytes = render_lebenslauf(_profile(), _customized(), zielposition_titel="Test-Zielposition")
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        text = "\n".join((p.extract_text() or "") for p in pdf.pages)
    assert "Steve Eigenwillig" in text
    assert "Test-Zielposition" in text  # passed-through subtitle
    assert "Zugeschnitten." in text
    assert "High-level a1" in text  # werdegang bullet
    # Categorized skills section
    assert "Projektmanagement:" in text
    assert "Automatisierung" in text and "KI:" in text
    assert "n8n" in text
    # Detaillierte Projekterfahrung
    assert "DETAILLIERTE PROJEKTERFAHRUNG" in text
    assert "Workflow-Automatisierung mit n8n" in text
    assert "1,5 h/Tag" in text  # ergebnis line


def test_render_lebenslauf_without_zielposition_falls_back_to_default():
    """When no zielposition_titel passed, template uses default fallback."""
    import pdfplumber
    import io
    pdf_bytes = render_lebenslauf(_profile(), _customized())
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        text = "\n".join((p.extract_text() or "") for p in pdf.pages)
    assert "Projekt- und Prozessmanager" in text


def test_lebenslauf_has_keep_with_next_rule_for_section_dividers():
    """Regression: ohne `.section-divider + *` Regel landet die Ueberschrift
    'DETAILLIERTE PROJEKTERFAHRUNG' allein am Seitenende, wenn der erste
    Projektblock nicht mehr in den Restplatz passt."""
    from bewerber.tailoring.render import _lebenslauf_html
    html = _lebenslauf_html(_profile(), _customized())
    # Beide Halbsaetze der Keep-with-next-Regel muessen vorhanden sein
    assert ".section-divider +" in html, "Sibling-Selector fehlt im Template-CSS"
    assert "page-break-before: avoid" in html, "page-break-before-Property fehlt"


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
