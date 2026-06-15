#!/usr/bin/env bash
# Geplanter Discover-Run. Aus cron / launchd / systemd aufrufbar.
#
# Loggt nach bewerber/logs/discover-<YYYY-MM-DD>.log (eine Datei pro Tag).
# stdout + stderr werden zusammengefasst -> cron schickt keine Mails.
#
# Wichtig:
#   - Skript liegt unter bewerber/scripts/, das uebergeordnete Verzeichnis
#     ist das Bewerber-Hauptverzeichnis.
#   - `source .venv/bin/activate` setzt PATH UND DYLD_LIBRARY_PATH
#     (das wird auf macOS fuer WeasyPrint Pango/Cairo gebraucht).
#   - PYTHONPATH=src umgeht den .pth-debugpy-Konflikt mit VSCode site.py.

BEWERBER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$BEWERBER_DIR" || exit 2

mkdir -p logs
LOG="logs/discover-$(date +%Y-%m-%d).log"

{
  echo
  echo "=== $(date '+%Y-%m-%d %H:%M:%S') discover START ==="
  echo "    host=$(hostname) cwd=$(pwd)"

  # shellcheck disable=SC1091
  source .venv/bin/activate

  PYTHONPATH=src python -m bewerber.cli discover
  rc=$?

  echo "=== $(date '+%Y-%m-%d %H:%M:%S') discover END (exit=$rc) ==="
} >> "$LOG" 2>&1
