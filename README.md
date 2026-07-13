# Bewerber-Assistent

Personal job-application assistant — discovers job postings, scores them against
your master profile via LLM, generates DIN-5008-konformen Lebenslauf + Anschreiben,
and tracks the application pipeline in a local web dashboard.

**Status:** funktional, Single-User, lokales Localhost-Setup.
**Designed for:** German job market, deutsche Bewerbungsstandards.

## Features

- **Onboarding-Wizard** (Web): zieht aus deinen vorhandenen Lebensläufen + Anschreiben dein Master-Profil per LLM.
- **Discovery**: scrapt Job-Boards (Arbeitsagentur API, optional LinkedIn/Indeed) gegen konfigurierbare Suchen, filtert per `exclude_keywords`, scort jeden Treffer per LLM (1-10 Fit-Score).
- **Batch-Scoring**: mehrere URLs auf einmal manuell hinzufügen (Stepstone, LinkedIn) — Firma + Rolle werden vom LLM extrahiert.
- **Tailoring**: pro Job einen tailor-angepassten Lebenslauf + Anschreiben generieren (LLM customize + DIN-5008-PDF via WeasyPrint).
- **Batch-Tailor**: mehrere Jobs anhaken → mit einem Klick Bewerbungen erstellen lassen.
- **Anlagen-Verwaltung**: Zeugnisse/Urkunden zentral pflegen, werden bei jedem Tailor-Lauf automatisch in den Bewerbungsordner kopiert.
- **LLM-Fallback-Chain**: konfigurierbar Gemini ↔ OpenAI mit per-Role-Modellen (cheap-mini für Scoring, full model für Generation).
- **Status-Tracking**: pro Job — entdeckt / vorgemerkt / getailored / beworben / eingeladen / abgelehnt / abgewählt / etc., inkl. Beworben-am-Datum und Freitext-Notizen.
- **Drei Ansichten**: Tabelle, Kanban (Drag & Drop) und Fokus (kuratierte Gruppen: „Jetzt dran", „Neu & vielversprechend", „Warten auf Antwort").
- **Discover-Run mit Fortschritt + Abbruch**: Live-Anzeige („linkedin: Job 5/28 gescored"), Zwischenspeichern pro Board, Abbrechen-Button; LLM-Calls mit hartem Timeout + Circuit-Breaker gegen erschöpfte Provider-Quotas.
- **Organic-Design**: warmes Design-System (Caprasimo/Figtree, Terracotta/Salbei) über alle Seiten, Quelle in `bewerber/Organic Dashboard Redesign/` (lokal).
- **Multi-User**: Login + Registrierung per Invite-Code, Workspace pro Nutzer, Account-Selbstlöschung (Menü am Namen) inkl. restloser Datenlöschung.

## Voraussetzungen

- **Python 3.11+** (getestet mit 3.12)
- **Homebrew-Pakete** (macOS, für WeasyPrint PDF-Render):
  ```bash
  brew install pango cairo
  ```
  Auf Linux: `apt install libpango-1.0-0 libpangoft2-1.0-0 libcairo2`
- **API-Key**: mindestens ein LLM-Provider
  - **Gemini** (kostenloser Free-Tier bis ~1500 req/Tag): https://aistudio.google.com/apikey
  - **OpenAI** (kostenpflichtig, gpt-5-mini ab ~$0.25/1M Token): https://platform.openai.com/api-keys
- **Optional für Discover**: Arbeitsagentur-API-Key: https://jobsuche.api.bund.dev/

## Installation

```bash
# Clone + virtualenv
git clone https://github.com/Handsomedolan/bewerber-assistent.git
cd bewerber-assistent/bewerber
python3 -m venv .venv
source .venv/bin/activate

# Installation
pip install -e .
playwright install chromium    # einmalig, für URL-Snapshots beim manuellen Hinzufügen

# Erstmaliges Setup (.env mit API-Keys interaktiv anlegen)
bewerber setup

# Server starten
bewerber serve
```

Beim ersten `bewerber serve` ohne vorhandene `.env` startet der Setup-Wizard automatisch.

## Erstmaliger Workflow (frische Installation)

1. **`bewerber setup`** → API-Keys + Provider-Reihenfolge konfigurieren (oder wird automatisch beim ersten Start abgefragt)
2. **`bewerber serve`** → Browser öffnet sich auf http://127.0.0.1:`<port>`/
3. **Login** mit Vor- + Nachname (lokales Cookie, 30 Tage gültig)
4. **Onboarding-Wizard** (öffnet sich automatisch, da noch kein Profil):
   - **Step 1**: alte Lebensläufe + Anschreiben (PDF/DOCX) per Drag-and-Drop hochladen → LLM extrahiert dein Master-Profil
   - **Step 2**: Suchbegriffe + Locations + max-Tage + Boards
   - **Step 3** (optional): Pfad zu deinem Anlagen-Ordner (Zeugnisse etc.)
   - **Step 4** (optional): Anschreiben-Stil-Beispiele aus Step-1-Uploads auswählen
   - **Finish** → schreibt `master_profile.yaml`, `searches.yaml`, `anlagen.yaml`, `anschreiben_examples/`
5. **Dashboard** lädt automatisch → kein scrape gelaufen, du bist im leeren Zustand

## Täglicher Workflow

- **Automatisch (cron)**: einmalig `crontab -e` mit der Zeile aus [`bewerber/scripts/crontab.example`](bewerber/scripts/crontab.example) ergänzen — täglich 16:00 Mo-Fr läuft `bewerber discover` und scort neue Postings.
- **Manuell**: Web-Dashboard öffnen, Jobs mit gutem Fit-Score anschauen, Bemerkung schreiben, "Bewerbung erstellen" klicken → tailored PDFs landen in `~/Documents/Bewerbungsunterlagen/Bewerbungen/<datum>_<firma>_<rolle>/`.
- **Stepstone/LinkedIn-URLs manuell hinzufügen**: oben am Dashboard "+ Mehrere URLs auf einmal verarbeiten" — Server snapshotet jede URL und scort sie.

## Architektur

```
bewerber/
├── src/bewerber/
│   ├── cli.py                  # Click-CLI: setup, serve, discover, tailor, profile init, ...
│   ├── setup_wizard.py         # interaktiver .env-Wizard
│   ├── dashboard/
│   │   ├── server.py           # stdlib http.server: Routes + Session-Cookie + Endpoints
│   │   └── render.py           # Jinja2-Templates rendern
│   ├── discovery/
│   │   ├── orchestrator.py     # Suchen × Boards iterieren, scrape → enrich → score → state
│   │   ├── scrapers/           # arbeitsagentur, linkedin, indeed
│   │   └── scoring.py          # LLM-Scoring + Batch-Extraction (Firma+Rolle+Scoring in 1 Call)
│   ├── tailoring/
│   │   ├── orchestrator.py     # customize_resume + generate_anschreiben + render_pdf
│   │   ├── render.py           # Jinja-Templates → WeasyPrint PDF (DIN 5008)
│   │   └── snapshot.py         # Playwright + requests-Fallback für URL-Snapshots
│   ├── profile/
│   │   └── extractor.py        # LLM-Extraktion aus PDFs/DOCX → MasterProfile
│   ├── shared/
│   │   ├── llm.py              # Multi-Provider-Chain (OpenAI/Gemini), Quota-Fallback, Retry
│   │   ├── state_schema.py     # pydantic-Modelle: RawJob, Scoring, TrackedJob, BewerberState
│   │   ├── anlagen.py          # zentrale Anlagen-Verwaltung
│   │   └── paths.py            # Pfad-Konfiguration (BEWERBER_WORKSPACE, BEWERBER_DOCUMENTS env)
├── templates/                  # Jinja2: dashboard, login, onboarding, searches-editor, anlagen-editor, lebenslauf, anschreiben
├── scripts/
│   ├── run-discover.sh         # cron-Wrapper für täglichen Discover-Lauf
│   └── crontab.example         # paste-ready cron-Zeile
├── tests/
│   └── unit/                   # ~250 Tests (LLM-Mock, Schema, Render, Endpoints)
├── .env.example                # Vorlage (wird vom Setup-Wizard generiert)
├── searches.yaml.example
├── anlagen.yaml.example
└── pyproject.toml
```

## Daten auf der Platte

| Datei | Inhalt | Versioniert? |
|---|---|---|
| `bewerber/.env` | API-Keys + Modell-Konfiguration | NEIN (gitignored) |
| `bewerber/master_profile.yaml` | dein Profil (LLM-extrahiert) | NEIN |
| `bewerber/state.json` | Jobs + Status + History + Notizen | NEIN |
| `bewerber/searches.yaml` | deine Suchen | NEIN |
| `bewerber/anlagen.yaml` | Zeugnisse-Konfig | NEIN |
| `bewerber/anschreiben_examples/*.txt` | Few-Shot-Beispiele für LLM | NEIN |
| `bewerber/logs/discover-*.log` | tägliche Discover-Logs | NEIN |
| `bewerber/dashboard.html` | statisches Dashboard-Backup (offline-Lesemodus) | NEIN |
| `~/Documents/Bewerbungsunterlagen/Bewerbungen/<datum>_<firma>_<rolle>/` | tailored PDFs pro Bewerbung | NEIN — eigener Pfad |

Alles Personenbezogene bleibt lokal. Im Git ist nur Code + Beispiel-Configs.

## Tests

```bash
cd bewerber
source .venv/bin/activate
pytest tests/unit
```

~280 Tests, mocked LLM-Calls — laufen offline ohne API-Keys.

## CLI-Kommandos (Übersicht)

| Befehl | Was |
|---|---|
| `bewerber setup` | interaktiver .env-Wizard |
| `bewerber serve` | HTTP-Server für Dashboard (default ephemerer Port + Browser-Auto-Open) |
| `bewerber discover` | scrape + score (für cron) |
| `bewerber tailor --url <url> --firma <X> --rolle <Y> --starttermin "ab sofort"` | einzelne Bewerbung |
| `bewerber tailor --rebuild <ordner>` | PDFs aus saved HTML re-rendern (kein LLM) |
| `bewerber profile init` | CLI-Variante des Profil-Setups (Onboarding-Wizard im Web nutzt das gleiche) |
| `bewerber mark <job_id> <status>` | Status setzen |
| `bewerber note <job_id> <text>` | Timestamped Note anhängen |

## Roadmap

- Phase 4: Multi-User (per-User-Datenverzeichnisse) für Raspberry-Pi-Deployment
- Echte Auth (Passwort statt nur Vor-+Nachname) für Cloudflare-Tunnel-Setup
- API-Middleware für `/api/*`-Endpoints (aktuell offen, lokal OK)

## Lizenz

MIT — siehe [LICENSE](LICENSE).
