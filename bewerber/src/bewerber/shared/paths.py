import os
import re
from pathlib import Path


class Paths:
    """Central path configuration. Allows override via env vars for testing."""

    PROJECT_FOLDER_REGEX = re.compile(r"^\d+[\s_]+.+")
    _LEADING_NUMBER_REGEX = re.compile(r"^(\d+)")

    def __init__(self) -> None:
        # BEWERBER_WORKSPACE override hat Vorrang. Sonst auto-detecten via
        # __file__ - das funktioniert robust egal welcher cwd der User hat,
        # solange das Paket via `pip install -e .` installiert wurde.
        env_workspace = os.environ.get("BEWERBER_WORKSPACE")
        if env_workspace:
            self.workspace = Path(env_workspace)
        else:
            self.workspace = self._autodetect_workspace()
        self.documents = Path(
            os.environ.get("BEWERBER_DOCUMENTS", str(Path.home() / "Documents"))
        )

    @staticmethod
    def _autodetect_workspace() -> Path:
        """Heuristik wenn BEWERBER_WORKSPACE nicht gesetzt ist.

        Bei editable-install (`pip install -e .`) liegt diese Datei unter
            <workspace>/bewerber/src/bewerber/shared/paths.py
        also ist <workspace> = parents[4]. Wir validieren das, indem wir
        pruefen ob das gefundene Verzeichnis die erwartete Struktur hat
        (bewerber/src/bewerber existiert) - sonst Fallback auf cwd-Heuristik.

        Damit funktioniert `bewerber serve` egal ob aus dem Repo-Root oder
        aus dem bewerber/-Unterordner gestartet.
        """
        try:
            anchored = Path(__file__).resolve().parents[4]
        except IndexError:  # noqa: PERF203 - sehr seltener Fall
            anchored = None
        if anchored and (anchored / "bewerber" / "src" / "bewerber").is_dir():
            return anchored
        # Non-editable Install oder ungewoehnliches Layout: nimm cwd, aber wenn
        # cwd selbst der bewerber-Unterordner ist, dessen Parent verwenden.
        cwd = Path.cwd()
        return cwd.parent if cwd.name == "bewerber" else cwd

    @property
    def bewerber_dir(self) -> Path:
        return self.workspace / "bewerber"

    @property
    def master_profile(self) -> Path:
        return self.bewerber_dir / "master_profile.yaml"

    @property
    def state_json(self) -> Path:
        return self.bewerber_dir / "state.json"

    @property
    def dashboard_html(self) -> Path:
        return self.bewerber_dir / "dashboard.html"

    @property
    def bewerbungsunterlagen(self) -> Path:
        return self.documents / "Bewerbungsunterlagen"

    @property
    def bewerbungen(self) -> Path:
        return self.bewerbungsunterlagen / "Bewerbungen"

    @property
    def anschreiben_examples(self) -> Path:
        return self.bewerber_dir / "anschreiben_examples"

    @property
    def anlagen_yaml(self) -> Path:
        return self.bewerber_dir / "anlagen.yaml"

    def project_folders(self) -> list[Path]:
        """Return folders matching `<number> <name>`, sorted by (leading_number, name)."""
        if not self.documents.is_dir():
            return []
        candidates = [
            p
            for p in self.documents.iterdir()
            if p.is_dir() and self.PROJECT_FOLDER_REGEX.match(p.name)
        ]
        return sorted(candidates, key=self._sort_key)

    @classmethod
    def _sort_key(cls, p: Path) -> tuple[int, str]:
        """Sort by (leading number, full name) for natural ordering.

        Handles both space and underscore separators (e.g. `5 DeadEnd` and `20_SEO_AFM`).
        """
        match = cls._LEADING_NUMBER_REGEX.match(p.name)
        leading = int(match.group(1)) if match else 0
        return (leading, p.name)
