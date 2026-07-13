# Backlog

Stand: 2026-07-13 (abends, nach Fix-Deploy). Quelle: Incident-Analyse „Discovery-Run
hängt seit Stunden auf dem Pi".

## Incident-Kontext (2026-07-13)

Ein Nutzer startete auf dem Pi um 16:30 die Onboarding-Extraktion, um 16:48 einen
Discovery-Run („▶ Discover jetzt starten") und packte um 18:02 zusätzlich 9 Links in die
Batch-Verarbeitung. Der Batch lief in ~6 min durch; Onboarding- und Discovery-Thread
hingen dagegen seit ~16:49 in je einem Gemini-Call fest (`ssl.read`, kein Timeout,
Free-Tier-Quota von `gemini-3.5-flash` erschöpft). Der Discovery-Run stand nach 95 min
bei Job 2 seiner ersten LinkedIn-Charge. Diagnose per `py-spy dump` + journalctl +
Socket-Forensik (`ss -tnoi`: Requests gesendet & geackt, danach 0 Bytes empfangen).

## Erledigt am 2026-07-13 (deployed auf Pi, Service neu gestartet, Smoke-Test grün)

- [x] **Service-Restart** — durch Feature-Deploy der anderen Session (18:50) miterledigt;
  hängende Threads beseitigt.
- [x] **Playwright-Browser installiert** — `chromium-1223` + `chromium_headless_shell-1223`
  + deps auf dem Pi; Snapshots laufen nicht mehr in den requests-Fallback.
- [x] **Fix 1: HTTP-Timeout für alle LLM-Calls** (`shared/llm.py`) — 120 s Default,
  `BEWERBER_LLM_TIMEOUT_S` als Override. Gemini: `http_options={"timeout": ms}`
  (verhindert das SDK-Verhalten `timeout=None` → ewiger `ssl.read`); OpenAI: explizit
  120 s statt SDK-Default 600 s. httpx-Timeouts/Netzfehler aus dem genai-SDK werden als
  `LLMTransientError` klassifiziert → Fallback-Kette greift. Auf dem Pi in der Live-Env
  verifiziert (gemini 120000 ms / openai 120.0 s).
- [x] **Fix 2: Circuit-Breaker im `LLMClient`** — Provider wird nach 2 aufeinander-
  folgenden Quota-Fails bzw. 3 persistierenden Transient-Fails für den Rest des Laufs
  übersprungen (Erfolg resettet die Zähler). Kein minutenlanges Neu-Durchprobieren pro Job.
- [x] **Fix 3: Discovery-Cancel** — `POST /api/discover/cancel` + „■ Abbrechen"-Button
  im Dashboard; Orchestrator stoppt vor dem nächsten Job/Board, Teilergebnisse werden
  gesichert (Status `cancelling` → `cancelled`).
- [x] **Fix 4: Fortschritts-Reporting** — Orchestrator meldet `{search, board, done, total}`
  pro Job; Status-Endpoint liefert `progress` mit; UI zeigt „linkedin: Job 5/28 gescored".
- [x] **Fix 5: State-Zwischenspeichern** — Checkpoint (`save_state`) nach jedem Board
  statt nur am Run-Ende; Restart/Abbruch verliert keine gescorten Boards mehr.

Provider-Order bleibt bewusst `gemini,openai` (gratis zuerst): Mit Timeout + Breaker
kostet eine tote Gemini-Quota jetzt ~2 Fehlversuche pro Run statt Stunden.

## Offen (Code)

1. [ ] **`ThreadingHTTPServer` statt `HTTPServer`** (`server.py`, `serve()`): Der synchrone
   Batch-Add blockierte das komplette Dashboard für alle Nutzer ~6 min. Achtung:
   vorher Nebenläufigkeit der state.json-Zugriffe klären (siehe Punkt 4).
2. [ ] **Batch-Add in Hintergrund-Thread** mit Status-Polling (analog Discover), statt
   synchron im Request-Handler (`server.py:_handle_batch_add`).
3. [ ] **`_discover_state` pro User scopen** (`server.py`): global → jeder Nutzer sieht
   fremde Runs als „läuft", systemweit nur 1 Run möglich. Mindestens Run-Status an
   Session-User binden.
4. [ ] **Lost-Update-Race auf `state.json`** (beim Incident-Review gefunden, vorbestehend):
   Discover-Thread hält den State über den ganzen Run im Speicher und speichert ihn
   komplett; markiert ein Nutzer währenddessen einen Job (HTTP-Handler: load→modify→save),
   überschreibt der nächste Checkpoint die Änderung. Fix-Idee: beim Checkpoint frisch
   laden + upserten statt blind schreiben (Merge-on-Save).
5. [ ] **Onboarding-Extraktion: Status/Abbruch** analog Discover (Timeout/Breaker greifen
   dort seit Fix 1+2 bereits; es fehlen Progress + Cancel).
6. [ ] **`results_wanted=30` im LinkedIn-Adapter konfigurierbar machen**
   (`discovery/scrapers/linkedin.py`). Optional dabei prüfen:
   `linkedin_fetch_description=True` (JobSpy) statt Einzel-Fetches in `enrich_job`.

## Offen (Wartung / Tests)

7. [ ] **5 vorbestehende Test-Fails auf main** (unabhängig von den Fixes, identisch auf
   8a99ba7): `test_discovery_e2e` (Mock ohne `for_scoring`-Attribut — Mock veraltet seit
   Provider-Refactor), `test_e2e_profile`, `test_tailor_e2e`, `test_cli_b::
   test_serve_calls_regen_then_open`, `test_scraper_arbeitsagentur::
   test_adapter_calls_api_and_parses`.
8. [ ] **WeasyPrint auf dem Mac**: Testlauf braucht `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib`,
   sonst brechen 9 Module bei der Collection (`libgobject-2.0-0` nicht gefunden).
   In `conftest.py` oder Doku verankern.
9. [ ] **Stale `bewerber/bewerber/`-Runtime-Ordner** überschattet das Paket bei Imports
   aus `cwd=bewerber/` (bekannt aus progress.md). Aufräumen oder umbenennen.
