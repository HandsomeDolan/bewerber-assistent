from typing import Optional
from pydantic import BaseModel, EmailStr, Field, ConfigDict


class Person(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    adresse: Optional[str] = None
    linkedin: Optional[str] = None
    xing: Optional[str] = None
    github: Optional[str] = None


class Arbeitspraeferenzen(BaseModel):
    model_config = ConfigDict(extra="forbid")
    remote: Optional[str] = None  # "ja" | "teilweise" | "nein"
    reisebereitschaft: Optional[str] = None
    gehaltserwartung_brutto_jahr: Optional[str] = None
    notice_period: Optional[str] = None


class Ausbildung(BaseModel):
    model_config = ConfigDict(extra="forbid")
    art: str
    institution: str
    abschluss: Optional[str] = None
    jahr: Optional[str] = None
    nachweis_pdf: Optional[str] = None


class Berufserfahrung(BaseModel):
    model_config = ConfigDict(extra="forbid")
    position: str
    firma: str
    von: str  # YYYY-MM
    bis: Optional[str] = None  # YYYY-MM or None for current
    standort: Optional[str] = None
    aufgaben: list[str] = Field(default_factory=list)
    erfolge: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    nachweis_pdf: Optional[str] = None


class Project(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    titel: str
    quelle: Optional[str] = None
    kurzbeschreibung: Optional[str] = None
    rolle: Optional[str] = None
    skills_fachlich: list[str] = Field(default_factory=list)
    skills_methodisch: list[str] = Field(default_factory=list)
    erfolge: list[str] = Field(default_factory=list)
    sichtbar_in_lebenslauf: bool = True


class Zertifikat(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    aussteller: Optional[str] = None
    jahr: Optional[str] = None


class Sprache(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sprache: str
    niveau: str  # z.B. "Muttersprache", "C1", "B2"


class MasterProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    person: Person
    berufsprofil: str
    zielposition: list[str] = Field(default_factory=list)
    arbeitspraeferenzen: Optional[Arbeitspraeferenzen] = None
    ausbildung: list[Ausbildung] = Field(default_factory=list)
    berufserfahrung: list[Berufserfahrung] = Field(default_factory=list)
    projekte: list[Project] = Field(default_factory=list)
    zertifikate: list[Zertifikat] = Field(default_factory=list)
    sprachen: list[Sprache] = Field(default_factory=list)
    interessen: list[str] = Field(default_factory=list)
