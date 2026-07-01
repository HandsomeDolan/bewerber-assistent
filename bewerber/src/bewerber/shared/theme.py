"""Design-Tokens (Theme) fuer das parametrisierte Basis-Layout. Reine Daten,
streng validiert (Farbe=Hex, Font=Whitelist, Stiloptionen=Enums) -> keine
CSS/HTML-Injection ueber Token-Werte moeglich."""
import re
from enum import Enum
from typing import Literal
from pydantic import BaseModel, ConfigDict, field_validator, model_validator

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


class SectionKey(str, Enum):
    profil = "profil"
    skills = "skills"
    werdegang = "werdegang"
    projekte = "projekte"
    bildung = "bildung"
    sprachen = "sprachen"
    zertifikate = "zertifikate"


# key -> (CSS font-stack). Kuratiert auf WeasyPrint-sichere / gaengige Familien.
FONT_WHITELIST: dict[str, str] = {
    "calibri": '"Calibri","Carlito","Helvetica Neue","Arial",sans-serif',
    "helvetica": '"Helvetica Neue","Arial","Liberation Sans",sans-serif',
    "georgia": 'Georgia,"Times New Roman",serif',
    "garamond": '"EB Garamond","Garamond",Georgia,serif',
    "lato": '"Lato","Helvetica Neue","Arial",sans-serif',
}
_DEFAULT_FONT = "calibri"

# grobe Zuordnung roher Fontnamen -> Whitelist-Key
_FONT_HINTS = {
    "calibri": "calibri", "carlito": "calibri", "arial": "helvetica",
    "helvetica": "helvetica", "liberation": "helvetica",
    "georgia": "georgia", "times": "georgia", "serif": "georgia",
    "garamond": "garamond", "lato": "lato",
}


def map_font(raw: str) -> str:
    low = (raw or "").lower()
    # Split on whitespace/dash/underscore and check exact word matches
    words = set(re.split(r"[\s\-_]+", low))
    for hint, key in _FONT_HINTS.items():
        if hint in words:
            return key
    return _DEFAULT_FONT


_COLOR_DEFAULTS = {
    "accent_color": "#1f6feb",
    "text_color": "#20242b",
    "heading_color": "#1f6feb",
}

_ENUM_DEFAULTS = {
    "header_style": "left_accent_bar",
    "section_title_style": "uppercase_bar",
    "density": "normal",
}


class Theme(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    font_family: str = _DEFAULT_FONT
    accent_color: str = "#1f6feb"
    text_color: str = "#20242b"
    heading_color: str = "#1f6feb"
    header_style: Literal["centered", "left", "left_accent_bar"] = "left_accent_bar"
    section_title_style: Literal["uppercase_underline", "uppercase_bar", "plain_bold"] = "uppercase_bar"
    section_order: list[str] = [s.value for s in SectionKey]
    density: Literal["compact", "normal", "spacious"] = "normal"

    @field_validator("font_family", mode="before")
    @classmethod
    def _font(cls, v):
        v = str(v or "")
        return v if v in FONT_WHITELIST else map_font(v)

    @field_validator("accent_color", "text_color", "heading_color", mode="before")
    @classmethod
    def _hex(cls, v, info):
        v = str(v or "")
        return v if _HEX.match(v) else _COLOR_DEFAULTS[info.field_name]

    @field_validator("header_style", "section_title_style", "density", mode="before")
    @classmethod
    def _enum_fallback(cls, v, info):
        # ungueltige Enum-Werte -> Feld-Default (kein ValidationError)
        allowed = {
            "header_style": {"centered", "left", "left_accent_bar"},
            "section_title_style": {"uppercase_underline", "uppercase_bar", "plain_bold"},
            "density": {"compact", "normal", "spacious"},
        }[info.field_name]
        return v if v in allowed else _ENUM_DEFAULTS[info.field_name]

    @model_validator(mode="after")
    def _normalize_order(self):
        valid = [s.value for s in SectionKey]
        seen, out = set(), []
        for k in self.section_order:
            if k in valid and k not in seen:
                seen.add(k); out.append(k)
        for k in valid:  # fehlende ans Ende
            if k not in seen:
                out.append(k)
        self.section_order = out
        return self

    def tokens(self) -> dict:
        """Render-fertiges Token-Dict fuer das Basis-Layout."""
        return {
            "font_stack": FONT_WHITELIST.get(self.font_family, FONT_WHITELIST[_DEFAULT_FONT]),
            "accent_color": self.accent_color,
            "text_color": self.text_color,
            "heading_color": self.heading_color,
            "header_style": self.header_style,
            "section_title_style": self.section_title_style,
            "section_order": self.section_order,
            "density": self.density,
        }


# Defaults, wenn das Basis-Layout ohne Theme gerendert wird.
DEFAULT_THEME_TOKENS: dict = Theme(id="_default", name="Default").tokens()
