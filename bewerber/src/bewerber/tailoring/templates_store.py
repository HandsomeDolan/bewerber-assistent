"""Registry + Abstraktion fuer Design-Sets (CV + Anschreiben).

Phase 1: nur eingebaute Sets (Dateisystem). Spaeter erweitern um User-Uploads
(A2) und geteilte Sets/Supabase (A5) - Renderer/Handler bleiben unveraendert.
"""
from dataclasses import dataclass
from typing import Optional

from pydantic import BaseModel, ConfigDict

DEFAULT_SET = "classic"
_DOCS = ("lebenslauf", "anschreiben")


class TemplateSetMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    description: str = ""
    builtin: bool = True


@dataclass
class TemplateChoice:
    """Vom UI gewaehlte Auswahl. cv_set/anschreiben_set ueberschreiben set_id."""
    set_id: str = DEFAULT_SET
    cv_set: Optional[str] = None
    anschreiben_set: Optional[str] = None

    def cv(self) -> str:
        return self.cv_set or self.set_id

    def anschreiben(self) -> str:
        return self.anschreiben_set or self.set_id


_BUILTIN = [
    TemplateSetMeta(id="classic", name="Classic",
                    description="Klassisch, zentriert, monochrom (Standard)."),
    TemplateSetMeta(id="modern", name="Modern",
                    description="Einspaltig, linksbündig, dezente Akzentfarbe."),
]


class TemplateStore:
    """Interface. Spaetere Backends (User/Supabase) implementieren dieselben Methoden."""
    def list_sets(self) -> list[TemplateSetMeta]:
        raise NotImplementedError

    def has_set(self, set_id: str) -> bool:
        raise NotImplementedError

    def template_path(self, set_id: str, doc: str) -> str:
        raise NotImplementedError


class BuiltinTemplateStore(TemplateStore):
    def list_sets(self) -> list[TemplateSetMeta]:
        return list(_BUILTIN)

    def has_set(self, set_id: str) -> bool:
        return any(s.id == set_id for s in _BUILTIN)

    def template_path(self, set_id: str, doc: str) -> str:
        if doc not in _DOCS:
            raise ValueError(f"unbekanntes Dokument {doc!r}")
        sid = set_id if self.has_set(set_id) else DEFAULT_SET
        return f"sets/{sid}/{doc}.html.j2"
