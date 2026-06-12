from typing import Protocol, runtime_checkable
from bewerber.shared.state_schema import RawJob


@runtime_checkable
class BoardAdapter(Protocol):
    """Each scraper module exposes one class/instance satisfying this protocol."""
    name: str

    def search(
        self,
        keywords: list[str],
        locations: list[str],
        max_age_days: int,
    ) -> list[RawJob]: ...


# Filled by individual scraper modules at import time (see arbeitsagentur.py etc.)
scraper_registry: dict[str, BoardAdapter] = {}
