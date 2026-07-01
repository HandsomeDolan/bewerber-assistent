"""Extrahiert Design-Tokens (Theme) aus einem hochgeladenen CV (PDF/Word).

Kein Vision: Style-Fakten werden strukturell geerntet (pdfplumber fuer PDF,
python-docx fuer Word) und per Text-LLM auf das Theme-Schema gemappt.
"""
import json
from collections import Counter
from pathlib import Path

import pdfplumber
from docx import Document

from bewerber.shared.llm import LLMClient
from bewerber.shared.theme import Theme, SectionKey

SUPPORTED_EXT = {".pdf", ".docx"}
_SECTION_HINTS = {  # grobe Zuordnung Ueberschrift -> SectionKey
    "profil": "profil", "profile": "profil", "summary": "profil",
    "skill": "skills", "kenntnis": "skills",
    "erfahrung": "werdegang", "werdegang": "werdegang", "experience": "werdegang", "beruf": "werdegang",
    "projekt": "projekte", "project": "projekte",
    "bildung": "bildung", "ausbildung": "bildung", "education": "bildung",
    "sprach": "sprachen", "language": "sprachen",
    "zertifik": "zertifikate", "certif": "zertifikate", "weiterbildung": "zertifikate",
}


def _rgb_to_hex(c) -> str | None:
    try:
        if isinstance(c, (tuple, list)) and len(c) == 3:
            r, g, b = (int(round(float(x) * 255)) if float(x) <= 1 else int(x) for x in c)
            return f"#{r:02x}{g:02x}{b:02x}"
    except Exception:  # noqa: BLE001
        return None
    return None


def _classify_section(text: str) -> str | None:
    low = text.lower()
    for hint, key in _SECTION_HINTS.items():
        if hint in low:
            return key
    return None


def harvest_style_facts(path: Path) -> dict:
    """Erntet rohe Style-Fakten aus PDF/Word: Fonts, Farben, Heading-Groessen, Sektionen."""
    ext = path.suffix.lower()
    fonts: Counter = Counter()
    colors: Counter = Counter()
    sizes: list[float] = []
    sections: list[str] = []

    if ext == ".pdf":
        with pdfplumber.open(str(path)) as pdf:
            for page in pdf.pages[:4]:
                for ch in page.chars:
                    fn = ch.get("fontname") or ""
                    if fn:
                        fonts[fn.split("+")[-1]] += 1
                    hx = _rgb_to_hex(ch.get("non_stroking_color"))
                    if hx:
                        colors[hx] += 1
                    if ch.get("size"):
                        sizes.append(round(float(ch["size"]), 1))
                # Zeilen als Section-Kandidaten (kurze Zeilen mit Section-Hint)
                for line in (page.extract_text() or "").splitlines():
                    s = line.strip()
                    if 0 < len(s) <= 40 and _classify_section(s):
                        sec = _classify_section(s)
                        if sec and sec not in sections:
                            sections.append(sec)
    elif ext == ".docx":
        doc = Document(str(path))
        for para in doc.paragraphs:
            txt = para.text.strip()
            for run in para.runs:
                if run.font and run.font.name:
                    fonts[run.font.name] += 1
                col = getattr(run.font, "color", None)
                rgb = getattr(col, "rgb", None) if col else None
                if rgb:
                    colors[f"#{str(rgb).lower()}"] += 1
            if txt and (para.style.name or "").lower().startswith("heading"):
                sec = _classify_section(txt)
                if sec and sec not in sections:
                    sections.append(sec)
    else:
        raise ValueError(f"nicht unterstuetzt: {ext}")

    big = sorted(set(sizes), reverse=True)[:3]
    return {
        "fonts": [f for f, _ in fonts.most_common(3)],
        "colors": [c for c, _ in colors.most_common(5)],
        "heading_sizes": big,
        "sections": sections,
    }


_SYS = """Du bist ein Design-Analyst. Aus den geernteten Style-Fakten eines
Lebenslaufs leitest du Design-Tokens ab. Antworte NUR im vorgegebenen Schema.
- font_family: eine der Whitelist-Familien, die den erkannten Fonts am naechsten ist.
- accent_color/heading_color: die auffaelligste Nicht-Schwarz-Farbe (Hex) oder Default.
- text_color: die dominante Textfarbe (meist dunkel).
- section_order: die Reihenfolge der erkannten Sektionen; fehlende ergaenzt das System.
- header_style/section_title_style/density: aus dem Gesamteindruck schaetzen."""


def extract_theme(path: Path, name: str, llm: LLMClient) -> Theme:
    facts = harvest_style_facts(path)
    user = (
        f"Name des Themes: {name}\n"
        f"Geerntete Style-Fakten (JSON):\n{json.dumps(facts, ensure_ascii=False)}\n\n"
        f"Erlaubte Sektions-Keys: {[s.value for s in SectionKey]}\n"
        "Leite die Design-Tokens ab."
    )
    theme = llm.structured(system=_SYS, user=user, schema=Theme)
    # id/name deterministisch setzen (LLM-Werte ueberschreiben)
    theme.name = name
    return theme
