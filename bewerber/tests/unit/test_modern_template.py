import jinja2
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parents[2] / "templates"

LBL_DE = {"profil": "PROFIL", "skills": "SKILLS", "werdegang": "WERDEGANG",
          "projekte": "DETAILLIERTE PROJEKTERFAHRUNG", "bildung": "BILDUNG",
          "sprachen": "SPRACHEN", "zertifikate": "WEITERBILDUNGEN & ZERTIFIKATE",
          "sk_prozess": "Prozessmanagement", "sk_projekt": "Projektmanagement",
          "sk_komm": "Kommunikation & Training", "sk_auto": "Automatisierung & KI",
          "sk_vertrieb": "Vertrieb", "heute": "heute", "ergebnis": "Ergebnis",
          "zhd": "z. Hd.", "betreff_prefix": "Bewerbung als",
          "gruss_fallback": "Mit freundlichen Grüßen", "anlagen_titel": "Anlagen"}
LBL_EN = dict(LBL_DE, profil="PROFILE", werdegang="EXPERIENCE", bildung="EDUCATION",
              sprachen="LANGUAGES", betreff_prefix="Application for", anlagen_titel="Enclosures")


class O:
    def __init__(self, **k): self.__dict__.update(k)


def _env():
    return jinja2.Environment(loader=jinja2.FileSystemLoader(str(TEMPLATES)),
                              autoescape=jinja2.select_autoescape(["html", "xml"]))


def _profile():
    return O(person=O(name="Max Test", adresse="Leipzig", phone="0", email="a@b.de"),
             berufsprofil="x", ausbildung=[], sprachen=[], zertifikate=[])


def _customized():
    return O(berufsprofil_zugespitzt="Profiltext",
             skills_kategorisiert=O(prozessmanagement=["a"], projektmanagement=[],
                                    kommunikation_training=[], automatisierung_ki=["n8n"], vertrieb=[]),
             berufserfahrung=[])


def test_modern_lebenslauf_renders_de_and_en():
    tpl = _env().get_template("sets/modern/lebenslauf.html.j2")
    de = tpl.render(profile=_profile(), customized=_customized(), zielposition_titel="X", lbl=LBL_DE)
    assert "set: modern" in de and "PROFIL" in de and "Max Test" in de
    en = tpl.render(profile=_profile(), customized=_customized(), zielposition_titel="X", lbl=LBL_EN)
    assert "PROFILE" in en and "EXPERIENCE" in en


def test_modern_anschreiben_has_marker():
    tpl = _env().get_template("sets/modern/anschreiben.html.j2")
    out = tpl.render(profile=_profile(), anschreiben=O(anrede="Hallo", einleitung="i",
                     hauptteil="h", schluss="s", gruss="Gruß"),
                     firma="ACME", rolle="Dev", datum="01.01.2026", kontakt_name=None,
                     ort="Leipzig", anlagen=["Lebenslauf"], lbl=LBL_DE)
    assert "set: modern" in out and "ACME" in out


def test_classic_still_present():
    # Sicherstellen, dass der Move geklappt hat
    assert (TEMPLATES / "sets/classic/lebenslauf.html.j2").is_file()
    assert (TEMPLATES / "sets/classic/anschreiben.html.j2").is_file()
