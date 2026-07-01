"""Feste Demo-Daten fuer die Theme-Vorschau (keine echten Profildaten)."""
from bewerber.shared.profile_schema import MasterProfile, Person, Ausbildung, Sprache, Zertifikat
from bewerber.tailoring.customize import CustomizedResume, CustomBerufserfahrung, ProjekterfahrungBlock, SkillKategorien
from bewerber.tailoring.render_html import _lebenslauf_html

SAMPLE_PROFILE = MasterProfile(
    person=Person(name="Alex Beispiel", email="alex@example.com", phone="+49 000",
                  adresse="Musterstr. 1, Leipzig, Germany"),
    berufsprofil="Beispiel-Berufsprofil fuer die Layout-Vorschau.",
    ausbildung=[Ausbildung(art="Studium", institution="Universitaet Beispiel", abschluss="B.Sc. Musterwissenschaft")],
    sprachen=[Sprache(sprache="Deutsch", niveau="C2"), Sprache(sprache="Englisch", niveau="B2")],
    zertifikate=[Zertifikat(name="Beispiel-Zertifikat")],
)
SAMPLE_CUSTOMIZED = CustomizedResume(
    berufsprofil_zugespitzt="Zugespitztes Beispiel-Profil fuer die Vorschau dieses Layouts.",
    berufserfahrung=[
        CustomBerufserfahrung(position="Beispiel-Rolle", firma="Muster GmbH", von="2022-01", bis=None,
            standort="Leipzig", werdegang_bullets=["Beispielaufgabe eins", "Beispielaufgabe zwei"],
            projekterfahrung=[ProjekterfahrungBlock(titel="Beispielprojekt",
                aufgaben=["Beispieltaetigkeit"], ergebnisse=["Beispielergebnis mit Zahl 20%"])]),
    ],
    skills_kategorisiert=SkillKategorien(prozessmanagement=["Prozessoptimierung"], projektmanagement=["Projektleitung"],
        kommunikation_training=["Praesentation"], automatisierung_ki=["Python"], vertrieb=[]),
)


def preview_html(theme_tokens: dict | None) -> str:
    """Rendert das Basis-Layout mit Beispieldaten + Theme-Tokens als HTML."""
    return _lebenslauf_html(
        SAMPLE_PROFILE, SAMPLE_CUSTOMIZED, zielposition_titel="Beispiel-Rolle",
        sprache="de", template="sets/base/lebenslauf.html.j2", theme=theme_tokens,
    )
