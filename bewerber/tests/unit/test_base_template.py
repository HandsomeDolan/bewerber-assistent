import jinja2
from pathlib import Path
from bewerber.shared.theme import Theme

TEMPLATES = Path(__file__).resolve().parents[2] / "templates"
LBL = {"profil":"PROFIL","skills":"SKILLS","werdegang":"WERDEGANG","projekte":"PROJEKTE",
       "bildung":"BILDUNG","sprachen":"SPRACHEN","zertifikate":"ZERTIFIKATE",
       "sk_prozess":"P","sk_projekt":"P","sk_komm":"K","sk_auto":"A","sk_vertrieb":"V",
       "heute":"heute","ergebnis":"Ergebnis","zhd":"z.Hd.","betreff_prefix":"Bewerbung als",
       "gruss_fallback":"MfG","anlagen_titel":"Anlagen"}

class O:
    def __init__(self, **k): self.__dict__.update(k)

def _env():
    return jinja2.Environment(loader=jinja2.FileSystemLoader(str(TEMPLATES)),
                              autoescape=jinja2.select_autoescape(["html","xml"]))

def _profile():
    return O(person=O(name="Max Test", adresse="Leipzig", phone="0", email="a@b.de"),
             berufsprofil="x", ausbildung=[], sprachen=[], zertifikate=[])

def _cust():
    return O(berufsprofil_zugespitzt="P", skills_kategorisiert=O(prozessmanagement=["a"],
             projektmanagement=[], kommunikation_training=[], automatisierung_ki=["n8n"], vertrieb=[]),
             berufserfahrung=[])

def test_base_applies_theme_tokens():
    th = Theme(id="t", name="T", accent_color="#abcdef", section_order=["skills","profil"]).tokens()
    html = _env().get_template("sets/base/lebenslauf.html.j2").render(
        profile=_profile(), customized=_cust(), zielposition_titel="X", lbl=LBL, theme=th)
    assert "set: base" in html
    assert "#abcdef" in html                        # Akzentfarbe wirkt
    assert html.index("SKILLS") < html.index("PROFIL")   # Reihenfolge wirkt

def test_base_renders_without_theme_defaults():
    html = _env().get_template("sets/base/lebenslauf.html.j2").render(
        profile=_profile(), customized=_cust(), zielposition_titel="X", lbl=LBL)  # kein theme
    assert "set: base" in html and "#1f6feb" in html  # Default-Akzent

def test_base_anschreiben_renders():
    html = _env().get_template("sets/base/anschreiben.html.j2").render(
        profile=_profile(), anschreiben=O(anrede="Hallo", einleitung="i", hauptteil="h",
        schluss="s", gruss="G"), firma="ACME", rolle="Dev", datum="01.01.2026",
        kontakt_name=None, ort="Leipzig", anlagen=["Lebenslauf"], lbl=LBL,
        theme=Theme(id="t", name="T", accent_color="#abcdef").tokens())
    assert "set: base" in html and "ACME" in html
