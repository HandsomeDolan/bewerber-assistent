import re


UMLAUT_MAP = str.maketrans({
    "ä": "ae", "ö": "oe", "ü": "ue",
    "Ä": "Ae", "Ö": "Oe", "Ü": "Ue",
    "ß": "ss",
})


def slug_part(text: str) -> str:
    """Filesystem-safe slug preserving case. Empty input → empty string.

    Umlauts are transliterated (ä→ae). Non-alphanumeric becomes `-`. Multiple
    dashes collapse. Leading/trailing dashes stripped.
    """
    if not text:
        return ""
    transliterated = text.translate(UMLAUT_MAP)
    with_dashes = re.sub(r"[^A-Za-z0-9]+", "-", transliterated)
    collapsed = re.sub(r"-+", "-", with_dashes)
    return collapsed.strip("-")


def bewerbungsordner_name(date_str: str, firma: str, rolle: str) -> str:
    """Build folder name: `YYYY-MM-DD_Firma-Slug_Rolle-Slug`. Rolle optional."""
    firma_s = slug_part(firma)
    rolle_s = slug_part(rolle)
    parts = [date_str, firma_s]
    if rolle_s:
        parts.append(rolle_s)
    return "_".join(parts)
