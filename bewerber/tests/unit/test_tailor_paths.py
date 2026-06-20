from pathlib import Path
from unittest.mock import patch

from bewerber.shared.paths import Paths
from bewerber.tailoring.orchestrator import TailorInput


def test_tailorinput_carries_paths(monkeypatch, tmp_path):
    monkeypatch.setenv("BEWERBER_WORKSPACE", str(tmp_path))
    p = Paths(user="tuser")
    inp = TailorInput(
        posting_text="x", firma="Acme", rolle="Dev", datum="2026-06-20",
        kontakt_name=None, source_url=None, snapshot_dir=None, llm=object(),
        paths=p,
    )
    assert inp.paths is p


def test_tailor_uses_input_paths_not_global(monkeypatch, tmp_path):
    """tailor() muss inp.paths nutzen, nicht Paths(). Wir prueffen, dass der
    master_profile-Read am User-Pfad erfolgt."""
    monkeypatch.setenv("BEWERBER_WORKSPACE", str(tmp_path))
    user_paths = Paths(user="tuser")
    user_paths.data_dir.mkdir(parents=True, exist_ok=True)
    user_paths.master_profile.write_text(
        "person: {name: T, email: t@x.de}\nberufsprofil: x\nzielposition: []", encoding="utf-8",
    )
    # Wenn tailor faelschlich Paths() (ohne user) nutzt, ist master_profile dort nicht da.
    # Wir mocken die teuren Schritte weg und pruefen nur den paths-Bezug ueber _load_master.
    from bewerber.tailoring import orchestrator as orch
    with patch.object(orch, "_load_master", side_effect=lambda p: _assert_user_path(p, user_paths)) as m:
        try:
            orch.tailor(TailorInput(
                posting_text="x", firma="Acme", rolle="Dev", datum="2026-06-20",
                kontakt_name=None, source_url=None, snapshot_dir=None, llm=object(),
                paths=user_paths,
            ))
        except _PathOK:
            pass
    assert m.called


class _PathOK(Exception):
    pass


def _assert_user_path(p, user_paths):
    assert Path(p) == user_paths.master_profile
    raise _PathOK()
