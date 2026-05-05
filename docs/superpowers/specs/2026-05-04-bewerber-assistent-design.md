# Bewerber-Assistent — Design Spec

**Datum:** 2026-05-04
**Autor:** Steve Eigenwillig (Brainstorming mit Claude)
**Status:** Approved Design, ready for implementation planning

## Kontext & Problem

Steve hat:
- 17 Projektordner (`/Users/steve/Documents/[1-17]*`) mit heterogenem Inhalt: Code, READMEs, Docs, Spreadsheets.
- `Bewerbungsunterlagen/` mit Zeugnissen (Techniker, REFA, Ausbilder, Magna-Arbeitszeugnis) und ~25 bereits geschriebenen Bewerbungen (DOCX/PDF) als Referenz für Stil & Inhalt.
- OpenAI API-Zugang, präferiert `gpt-5.1-mini`.

**Ziel:** Ein Tool, das (a) Skills aus den Projektordnern strukturiert extrahiert, (b) Jobs auf 5 deutschen Boards findet und scort, (c) tailored Lebenslauf + Anschreiben pro Job in Deutsch erzeugt, (d) den Bewerbungsstand in einem statischen HTML-Dashboard sichtbar und durchsuchbar macht — speziell für Interview-Vorbereitung mit schnellem Zugriff auf Job-Posting + eigene Bewerbung + Notizen.

**Kein Auto-Apply.** Bewerbung erfolgt manuell. Tool unterstützt Discovery, Tailoring, Tracking.

## Nicht-Ziele (YAGNI)

- Auto-Apply, Form-Filling, CAPTCHA-Solving.
- Mehrsprachigkeit (nur Deutsch).
- Multi-User, Auth, Cloud-Sync, Mobile-App.
- Live-Web-UI (statisches HTML reicht).
- Workday/Direkt-ATS-Adapter wie ApplyPilot sie hat.

## Tech-Entscheidungen

| Bereich           | Wahl                                                                 |
|-------------------|----------------------------------------------------------------------|
| Sprache           | Python 3.11+                                                          |
| LLM               | OpenAI `gpt-5.1-mini` (Structured Outputs für Scoring/Tailoring)      |
| CLI-Framework     | Click                                                                 |
| Job-Scraping      | `python-jobspy` für LinkedIn DE + Indeed.de, eigene Scraper für Xing/StepStone/Arbeitsagentur |
| Browser-Automation| Selenium (Xing, StepStone-Fallback) + Playwright (Posting-PDF-Snapshot) |
| HTML-Parsing      | BeautifulSoup, readability-lxml                                      |
| PDF-Generierung   | WeasyPrint (Lebenslauf, Anschreiben aus HTML/Markdown)               |
| Templating        | Jinja2                                                                |
| Datenmodell       | Pydantic, YAML (master_profile, searches), JSON (state)               |
| Persistenz        | Flat Files: master_profile.yaml, state.json, _profile.md pro Projekt  |

**Verhältnis zu ApplyPilot/AIHawk:** beide bleiben in `scope/` als Referenz. Es wird kein Code importiert — die Tools sind für andere Use Cases (englisch, Auto-Apply) gebaut. `python-jobspy` (das ApplyPilot intern nutzt) wird direkt verwendet.

## Architektur

Vier Subsysteme mit klaren Schnittstellen:

```
PROFIL-AUFBAU      →   master_profile.yaml   ←   DISCOVERY + TAILORING
                                                       ↓
                                                  state.json
                                                       ↓
                                                  DASHBOARD (HTML)
```

### Subsystem 1: Profil-Aufbau

**Verantwortung:** Aus Bewerbungsunterlagen + 17 Projektordnern eine kanonische `master_profile.yaml` erzeugen und konsistent halten.

**Komponenten:**

- `bewerber profile init`
  - Liest `Bewerbungsunterlagen/*.pdf` (Zeugnisse, Lebensläufe).
  - Extrahiert via PDF-Text + LLM strukturiert: `person`, `ausbildung`, `berufserfahrung`, `zertifikate`, `sprachen`.
  - Schreibt erste Version `master_profile.yaml`. Idempotent: Re-Run frägt vor Überschreiben.
  - Fragt interaktiv: welche 2-3 deiner bisherigen Anschreiben (`Bewerbungsunterlagen/Bewerbungen/*.docx`) sollen als Stil-Few-Shots dienen → speichert als Plain-Text in `anschreiben_examples/`.

- `bewerber projects scan`
  - Iteriert über `/Users/steve/Documents/[0-9]*` Ordner.
  - Pro Ordner: Liest `README.md`, `claude.md`, `*.md`, Dateinamen, `package.json`/`requirements.txt`, Code-Header. Sampling falls > 30k Tokens.
  - LLM erzeugt `_profile.md` mit Front-Matter (`id`, `titel`, `sichtbar_in_lebenslauf`) und Sektionen: Kurzbeschreibung, Meine Rolle, Fachliche Skills, Methodische Skills, Erfolge, Notizen.
  - **Idempotent:** Bestehende `_profile.md` bleiben unangetastet, außer mit `--force`.

- `bewerber profile sync`
  - Liest alle `_profile.md` über `id`-Front-Matter → merged in Sektion `projekte:` von `master_profile.yaml`.
  - Verlustfrei: andere Sektionen (von `init` oder manuell editiert) bleiben unverändert.

**Schnittstelle nach außen:** `master_profile.yaml` mit pydantic-Schema validiert (siehe `shared/profile_schema.py`).

### Subsystem 2: Discovery

**Verantwortung:** Jobs auf 5 Boards finden, anreichern, scoren, in `state.json` persistieren.

**Komponenten:**

- `bewerber discover [--search NAME]`
  - Liest `searches.yaml` (mehrere benannte Suchen mit Keywords + Boards).
  - Stage 1 — **Scrape**: parallel pro Board.
    - LinkedIn DE, Indeed.de: `python-jobspy`.
    - Xing: Selenium gegen public Suche.
    - StepStone: requests + BeautifulSoup, JSON-LD-Parser; Selenium-Fallback bei Cloudflare-Block.
    - Arbeitsagentur: offizielle JSON-API (`jobsuche.api.bund.de`, API-Key-Setup in `.env`).
    - Fehler isoliert pro Board → `state.scrape_errors[board]`. Andere Boards laufen weiter.
  - Stage 2 — **Enrich**: Volltext-Beschreibung holen wenn fehlt (HTML fetch + readability-lxml).
  - Stage 3 — **Score**: LLM-Pass pro Job mit Master-Profil + Beschreibung. Output strukturiert via OpenAI Structured Outputs:
    ```json
    { "fit_score": 8, "begruendung": "...", "matched_skills": [...],
      "missing_skills": [...], "red_flags": [...],
      "verbessern_in_anschreiben": [...] }
    ```
  - Stage 4 — **Persist**: upsert in `state.jobs[<job_id>]`. Existierende Status bleiben erhalten. Score wird neu berechnet wenn Description-Hash sich geändert hat.
  - Anschließend: `dashboard.html` regenerieren.

**Job-ID & Dedup:**
- Primary Key: `<board>-<external_id>`.
- Cross-Board-Dedup im selben Run: Hash aus `(company_normalized, title_normalized)` → ein logischer Job mit mehreren `urls`.

**Konfiguration `searches.yaml`:**

```yaml
defaults:
  locations: [Leipzig, Berlin, Remote]
  remote: true
  date_posted_max_days: 14
  min_fit_score: 6   # nur informativ — niedriger gescorte Jobs landen trotzdem in state, aber im Dashboard default ausgeblendet

searches:
  - name: KI Manager
    keywords: [KI Manager, AI Product Manager, KI Produktmanager]
    boards: [linkedin, indeed, xing, stepstone, arbeitsagentur]
  # ...
```

**Scraper-Interface (`discovery/scrapers/__init__.py`):**

```python
class BoardAdapter(Protocol):
    name: str
    def search(self, keywords: list[str], location: str, max_age_days: int) -> list[RawJob]: ...

class RawJob(BaseModel):
    board: str
    external_id: str
    url: str
    title: str
    company: str
    location: str
    posted_date: date | None
    description_html: str | None  # ggf. erst in Enrich gefüllt
```

### Subsystem 3: Tailoring

**Verantwortung:** Pro Job ein Bewerbungspaket erzeugen (Lebenslauf + Anschreiben + Job-Snapshot) und versioniert ablegen.

**Komponenten:**

- `bewerber tailor <job_id>`
  - **Snapshot**: Playwright öffnet `job.url`, speichert `posting.html` (raw) + `posting.pdf` (print-Modus). Extrahiert Kontaktperson via LLM → `posting_meta.yaml`.
  - **Lebenslauf-Customizing (LLM Pass 1)**: Input = `master_profile.yaml` + Job-Beschreibung + Scoring (matched/missing skills). Output strukturiert: welche `berufserfahrung`-Einträge zeigen, welche `projekte` hervorheben, Reihenfolge der Skills, pro Position 2–3 zugespitzte Bullets. **Constraint im System-Prompt:** kein Erfinden, nur Auswählen/Umformulieren aus Master-Daten.
  - **Anschreiben (LLM Pass 2)**: Input = Master-Profil + Job-Beschreibung + `verbessern_in_anschreiben`-Hinweise + `anschreiben_examples/*.txt` als Few-Shot. Output: Markdown, deutsche Briefform, Anrede automatisch (Frau/Herr <Name> wenn aus Posting extrahierbar, sonst "Sehr geehrte Damen und Herren").
  - **Render**: WeasyPrint mit Jinja2-Templates → `lebenslauf.pdf`, `anschreiben.pdf`. Quellen `lebenslauf.html` + `anschreiben.md` bleiben im Bewerbungsordner editierbar.
  - **Persist**: `state.jobs[<id>].status = "tailored"`, `tailored_dir` setzen.
  - **Audit**: `tailoring_log.json` listet pro Bullet-Point-Änderung Original → angepasst → Begründung.

- `bewerber tailor <job_id> --rebuild`: nur PDFs neu rendern aus aktuellen HTML/MD-Quellen, kein LLM-Aufruf.

- `bewerber tailor <job_id> --llm`: wie Default, erzwingt aber neue LLM-Generation auch wenn Output schon existiert.

**Bewerbungsordner pro Job:**

```
Bewerbungsunterlagen/Bewerbungen/2026-05-04_BMW_KI-Manager/
├── posting.html
├── posting.pdf
├── posting_meta.yaml         # url, board, scraped_at, kontakt
├── lebenslauf.pdf
├── lebenslauf.html           # editierbar (rebuild → PDF)
├── anschreiben.pdf
├── anschreiben.md            # editierbar (rebuild → PDF)
├── tailoring_log.json        # Audit
└── notes.md                  # freie User-Notizen
```

Ordnername: `<YYYY-MM-DD>_<firma_slug>_<rolle_slug>` für chronologische Sortierung und Lesbarkeit.

**Templates:**
- `templates/lebenslauf.html.j2`: ein professionelles, modernes Layout mit eingebettetem CSS (Paged Media). User editierbar.
- `templates/anschreiben.html.j2`: Briefkopf, Datum, Empfängeradresse, Betreff, dann Markdown-Body als HTML.

### Subsystem 4: Dashboard

**Verantwortung:** Statisches HTML aus `state.json` rendern, Filter, Suche, Detailansicht.

**Komponenten:**

- `bewerber regen`: rendert `dashboard.html` aus aktuellem `state.json` mit `templates/dashboard.html.j2`.
- `bewerber serve`: ruft `regen` und öffnet die Datei via `open` im Default-Browser. Kein Server.

**HTML-Eigenschaften:**
- Eine Datei mit eingebettetem CSS + Vanilla-JS.
- Daten als JSON inline (`<script id="data" type="application/json">…</script>`) — funktioniert offline, auch über `file://`.
- Filter (Status, Board, Score), Volltextsuche, Sortierung clientseitig.
- Detailansicht klappt pro Job auf: vollständige Beschreibung, Scoring, Status-History, Notizen, Direktlinks zu allen Dateien im Bewerbungsordner und zur Application-URL.
- Top-Banner zeigt Scrape-Errors aus `state.scrape_errors`.

**Status-Mutation via CLI** (statisches HTML kann nicht schreiben):

```bash
bewerber mark <job_id> shortlisted
bewerber mark <job_id> applied --link "<url-zur-eingereichten-bewerbung>"
bewerber mark <job_id> interview --at "2026-05-12 14:00"
bewerber mark <job_id> rejected
bewerber note <job_id> "Recruiter: Frau Müller, Tel-Termin 06.05."
```

Jeder `mark`/`note`-Aufruf: state.json schreiben + dashboard.html regenerieren.

**Status-States:**
`discovered` → `shortlisted` → `tailored` → `applied` → `interview` → `offer` | `rejected` | `withdrawn`

## Datenmodelle

### `master_profile.yaml` (Auszug)

```yaml
person:
  name: Steve Eigenwillig
  email: s.eigenwillig@impericon.com
  # ...

berufsprofil: <2-3 Sätze>
zielposition: [...]
arbeitspräferenzen:
  remote: ja|teilweise|nein
  reisebereitschaft: ...
  gehaltserwartung_brutto_jahr: ...

ausbildung:
  - art: ...
    institution: ...
    abschluss: ...
    jahr: ...
    nachweis_pdf: <relativ zu Bewerber_Assistent>

berufserfahrung:
  - position: ...
    firma: ...
    von: YYYY-MM
    bis: YYYY-MM | null
    aufgaben: [...]
    erfolge: [...]
    skills: [...]
    nachweis_pdf: ...

projekte:
  - id: 8-n8n-builder
    titel: n8n Builder
    quelle: /Users/steve/Documents/8 n8n_builder/_profile.md
    kurzbeschreibung: ...
    rolle: ...
    skills_fachlich: [...]
    skills_methodisch: [...]
    sichtbar_in_lebenslauf: true

zertifikate: [...]
sprachen: [...]
interessen: [...]
```

### `state.json`

```json
{
  "schema_version": 1,
  "last_discovery_run": "2026-05-04T14:32:00",
  "scrape_errors": { "stepstone": { "last_error": "...", "at": "..." } },
  "jobs": {
    "<job_id>": {
      "board": "linkedin",
      "external_id": "...",
      "url": "...",
      "title": "...",
      "company": "...",
      "location": "...",
      "posted_date": "YYYY-MM-DD",
      "first_seen": "...",
      "description": "...",
      "description_hash": "...",
      "scoring": { "fit_score": 8, "begruendung": "...", "matched_skills": [], "missing_skills": [], "red_flags": [], "verbessern_in_anschreiben": [] },
      "status": "applied",
      "status_history": [ { "status": "...", "at": "..." } ],
      "tailored_dir": "Bewerbungsunterlagen/Bewerbungen/...",
      "application_link": "...",
      "interview_scheduled": null,
      "notes": "..."
    }
  }
}
```

## Ordnerstruktur

```
/Users/steve/Documents/Bewerber_Assistent/
├── docs/superpowers/specs/
│   └── 2026-05-04-bewerber-assistent-design.md  ← dieses Dokument
├── bewerber/                                    ← das Tool
│   ├── pyproject.toml
│   ├── README.md
│   ├── master_profile.yaml
│   ├── searches.yaml
│   ├── state.json
│   ├── dashboard.html
│   ├── .env                                     ← OPENAI_API_KEY, ARBEITSAGENTUR_API_KEY
│   ├── anschreiben_examples/
│   ├── templates/
│   │   ├── lebenslauf.html.j2
│   │   ├── anschreiben.html.j2
│   │   └── dashboard.html.j2
│   ├── tests/
│   │   ├── unit/
│   │   ├── integration/   # Scraper-Fixtures
│   │   └── fixtures/
│   └── src/bewerber/
│       ├── cli.py
│       ├── profile/
│       │   ├── extractor.py
│       │   ├── projects.py
│       │   └── sync.py
│       ├── discovery/
│       │   ├── scrapers/
│       │   │   ├── linkedin.py
│       │   │   ├── indeed.py
│       │   │   ├── xing.py
│       │   │   ├── stepstone.py
│       │   │   └── arbeitsagentur.py
│       │   ├── enrich.py
│       │   └── score.py
│       ├── tailoring/
│       │   ├── snapshot.py
│       │   ├── customize.py
│       │   └── render.py
│       ├── dashboard/
│       │   └── render.py
│       └── shared/
│           ├── state.py
│           ├── profile_schema.py
│           └── llm.py
├── scope/                                       ← geklonte ApplyPilot/AIHawk (Referenz)
└── Bewerbungsunterlagen/                        ← bestehend
    ├── *.pdf  (Zeugnisse)
    └── Bewerbungen/                             ← bestehende + tailored Outputs
        ├── (alte DOCX/PDFs)
        └── 2026-05-04_BMW_KI-Manager/           ← pro Job, vom Tool erzeugt
            └── ...
```

## CLI-Referenz

```bash
# Profil
bewerber profile init               # erstmaliger Aufbau aus Bewerbungsunterlagen
bewerber projects scan [--force]    # _profile.md in jedem Projektordner
bewerber profile sync               # _profile.md → master_profile.yaml

# Discovery
bewerber discover [--search NAME]   # alle oder benannte Suche

# Tailoring
bewerber tailor <job_id>            # Snapshot + LLM + PDFs
bewerber tailor <job_id> --rebuild  # nur PDFs neu (nach manuellen Edits)
bewerber tailor <job_id> --llm      # alles neu inkl. LLM

# Status
bewerber mark <job_id> <status> [--link URL] [--at DATETIME]
bewerber note <job_id> "<text>"
bewerber list [--status STATUS] [--min-score N]

# Dashboard
bewerber regen                      # dashboard.html neu rendern
bewerber serve                      # regen + im Browser öffnen
```

## Error-Handling

| Fehlerquelle           | Verhalten                                                                              |
|------------------------|----------------------------------------------------------------------------------------|
| Scraper schlägt fehl   | Isoliert pro Board, Eintrag in `state.scrape_errors[board]`, andere Boards laufen weiter, Dashboard-Banner zeigt Status. |
| LLM-Aufruf schlägt fehl | Retry × 2 mit exponential Backoff. Bei finalem Fehler: Job behält alten Score; im Dashboard "Score: N/A — Re-Run nötig" Badge. |
| PDF-Render-Fehler      | HTML/MD-Quellen bleiben erhalten, Error-Log nach `bewerbungsordner/render_error.log`, Status bleibt auf vorigem Wert. |
| `state.json` corrupt   | Vor jedem Write: Backup `state.json.bak`. Beim Lesen: bei JSON-Decode-Error fragt Tool ob Backup wiederhergestellt werden soll. |
| Master-YAML invalid    | Pydantic-Validation beim Laden, Tool weigert sich zu starten mit klarer Fehlermeldung welches Feld falsch ist. |

## Tests

- **Unit:** Schema-Validierung (pydantic), state.json-Mutationen, Slugification, Dedup-Hashing, Markdown-Front-Matter-Parser.
- **Integration mit Fixtures:** Pro Scraper ein gespeicherter HTML/JSON-Snapshot in `tests/fixtures/<board>/` → Parser-Tests ohne Live-Scraping.
- **LLM-Tests:** Mock OpenAI-Client mit vordefinierten Strukturierten-JSON-Antworten. Echte LLM-Aufrufe in `tests/manual/` (gated, kostenpflichtig, nicht in CI).
- **End-to-End-Smoke:** Beispiel-Master-Profil + Beispiel-Job → erwartet PDF-Output, validiert Dateigrößen + Existenz + grundlegenden Inhalt (Name + Firma im Output).

## Wichtige Eigenschaften (Querschnitt)

- **Idempotenz:** alle Operationen können wiederholt werden ohne Datenverlust.
- **Auditierbarkeit:** Jeder Master-YAML-Wert hat ein `quelle:` Feld; jede LLM-Tailoring-Entscheidung wird in `tailoring_log.json` protokolliert.
- **Edit-Friendly:** Quellen (HTML, MD, YAML, JSON) sind Plain Text, manuell editierbar. Tool respektiert User-Edits.
- **No-Fabrication:** LLM-Prompts haben harte Constraints, dass nur aus Master-Daten zitiert/umformuliert wird, keine erfundenen Skills/Erfahrungen.
- **Offline-fähig:** Dashboard läuft über `file://`, keine Netzwerkanforderung. LLM-Calls und Scraping benötigen natürlich Netz.
- **Privacy:** Alle Daten bleiben lokal. Einziger externer Service ist OpenAI API (für LLM-Calls).

## Offene Punkte für die Implementierungsphase

- Konkretes Lebenslauf-Layout (HTML+CSS): ein Default wird mitgeliefert, Anpassung erfolgt iterativ nach erstem Test-Output.
- Arbeitsagentur-API: API-Key-Registrierung erforderlich (kostenlos, Setup in README).
- Cloudflare-Härte bei StepStone: Fallback auf Selenium evtl. mit `undetected-chromedriver` falls einfacher Selenium nicht reicht.
- Doppelter "16"-Ordner (`16 API Gateway` + `16 Marketing`) — Tool sollte hier warnen oder eindeutige IDs vergeben (z.B. `16a-api-gateway`, `16b-marketing`).
