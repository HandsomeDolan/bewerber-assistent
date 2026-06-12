import os
import re
from pathlib import Path


class Paths:
    """Central path configuration. Allows override via env vars for testing."""

    PROJECT_FOLDER_REGEX = re.compile(r"^\d+[\s_]+.+")
    _LEADING_NUMBER_REGEX = re.compile(r"^(\d+)")

    def __init__(self) -> None:
        self.workspace = Path(
            os.environ.get(
                "BEWERBER_WORKSPACE", "/Users/steve/Documents/Bewerber_Assistent"
            )
        )
        self.documents = Path(
            os.environ.get("BEWERBER_DOCUMENTS", "/Users/steve/Documents")
        )

    @property
    def bewerber_dir(self) -> Path:
        return self.workspace / "bewerber"

    @property
    def master_profile(self) -> Path:
        return self.bewerber_dir / "master_profile.yaml"

    @property
    def bewerbungsunterlagen(self) -> Path:
        return self.documents / "Bewerbungsunterlagen"

    @property
    def bewerbungen(self) -> Path:
        return self.bewerbungsunterlagen / "Bewerbungen"

    @property
    def anschreiben_examples(self) -> Path:
        return self.bewerber_dir / "anschreiben_examples"

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
