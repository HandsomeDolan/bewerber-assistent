import os
import re
from pathlib import Path


class Paths:
    """Central path configuration. Allows override via env vars for testing."""

    PROJECT_FOLDER_REGEX = re.compile(r"^\d+\s+.+")

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
        """Return sorted list of folders matching `<number> <name>` pattern."""
        if not self.documents.is_dir():
            return []
        return sorted(
            p
            for p in self.documents.iterdir()
            if p.is_dir() and self.PROJECT_FOLDER_REGEX.match(p.name)
        )
