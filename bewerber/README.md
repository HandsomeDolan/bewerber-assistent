# bewerber

Persönliches Bewerber-Werkzeug: Profil-Aufbau, Job-Discovery, Tailoring, Dashboard.

## Setup

```bash
cd bewerber
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
# .env editieren: OPENAI_API_KEY eintragen
```

## Commands

Plan A (verfügbar):
- `bewerber projects scan` — generiert `_profile.md` in jedem Projektordner
- `bewerber profile sync` — `_profile.md` → `master_profile.yaml`
- `bewerber profile init` — `Bewerbungsunterlagen/` → `master_profile.yaml`

Plan B + C: folgen.
