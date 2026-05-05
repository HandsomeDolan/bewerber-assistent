import frontmatter
from pathlib import Path
from bewerber.profile.projects import scan_project, gather_project_context, ProjectDraft


def test_gather_context_reads_readme_and_code(fixtures_dir: Path):
    folder = fixtures_dir / "sample_project_folder"
    ctx = gather_project_context(folder, max_chars=10000)
    assert "n8n Builder" in ctx
    assert "Freshdesk" in ctx
    assert "process_ticket" in ctx


def test_gather_context_truncates_at_limit(tmp_path):
    folder = tmp_path / "1 Big"
    folder.mkdir()
    (folder / "README.md").write_text("X" * 5000)
    (folder / "code.py").write_text("Y" * 5000)
    ctx = gather_project_context(folder, max_chars=2000)
    assert len(ctx) <= 2000


def test_scan_project_writes_profile_md(tmp_path, mocker):
    folder = tmp_path / "8 n8n_builder"
    folder.mkdir()
    (folder / "README.md").write_text("# n8n Builder\nWorkflow automation.")

    fake_llm = mocker.Mock()
    fake_llm.structured.return_value = ProjectDraft(
        kurzbeschreibung="Workflow tool.",
        rolle="Hauptentwickler.",
        skills_fachlich=["Python", "n8n"],
        skills_methodisch=["Agile"],
        erfolge=["Reduzierte Aufwand um 50%"],
    )

    out_path = scan_project(folder, llm=fake_llm, force=False)
    assert out_path == folder / "_profile.md"
    assert out_path.exists()
    post = frontmatter.load(str(out_path))
    assert post["id"] == "8-n8n-builder"
    assert post["titel"] == "n8n Builder"
    assert post["sichtbar_in_lebenslauf"] is True
    assert "Workflow tool." in post.content
    assert "Python" in post.content
    assert "Agile" in post.content


def test_scan_project_skips_existing_without_force(tmp_path, mocker):
    folder = tmp_path / "1 Existing"
    folder.mkdir()
    (folder / "_profile.md").write_text("---\nid: x\n---\noriginal")

    fake_llm = mocker.Mock()
    out = scan_project(folder, llm=fake_llm, force=False)
    assert out is None
    fake_llm.structured.assert_not_called()


def test_scan_project_overwrites_with_force(tmp_path, mocker):
    folder = tmp_path / "1 Existing"
    folder.mkdir()
    (folder / "README.md").write_text("# Existing")
    (folder / "_profile.md").write_text("---\nid: x\n---\noriginal")

    fake_llm = mocker.Mock()
    fake_llm.structured.return_value = ProjectDraft(
        kurzbeschreibung="new",
        rolle="r",
        skills_fachlich=[],
        skills_methodisch=[],
        erfolge=[],
    )
    out = scan_project(folder, llm=fake_llm, force=True)
    assert out is not None
    content = out.read_text()
    assert "new" in content
    assert "original" not in content


def test_id_slug_from_folder_name():
    from bewerber.profile.projects import folder_to_id
    assert folder_to_id("8 n8n_builder") == "8-n8n-builder"
    assert folder_to_id("1 Kleinanzeigen") == "1-kleinanzeigen"
    assert folder_to_id("16 API Gateway") == "16-api-gateway"


def test_folder_to_title_preserves_existing_caps():
    from bewerber.profile.projects import folder_to_title
    assert folder_to_title("8 n8n_builder") == "n8n Builder"
    assert folder_to_title("1 Kleinanzeigen") == "Kleinanzeigen"
    assert folder_to_title("16 API Gateway") == "API Gateway"
    assert folder_to_title("16 Marketing") == "Marketing"
    assert folder_to_title("9 HTTP Requests") == "HTTP Requests"


def test_gather_context_excludes_lockfiles(tmp_path):
    from bewerber.profile.projects import gather_project_context
    folder = tmp_path / "1 With Lockfile"
    folder.mkdir()
    (folder / "README.md").write_text("# Real Content")
    (folder / "package-lock.json").write_text('{"flood": "' + ("X" * 5000) + '"}')
    (folder / "main.min.js").write_text("Y" * 5000)
    ctx = gather_project_context(folder, max_chars=20_000)
    assert "Real Content" in ctx
    assert "flood" not in ctx
    assert "YYYY" not in ctx


def test_scan_project_skips_llm_for_empty_folder(tmp_path, mocker):
    folder = tmp_path / "1 Empty"
    folder.mkdir()
    # No README, no code — just a hidden file and a binary
    (folder / "image.png").write_bytes(b"\x89PNG fake")
    (folder / ".git").mkdir()

    fake_llm = mocker.Mock()
    out = scan_project(folder, llm=fake_llm, force=False)

    assert out is not None
    assert out.exists()
    fake_llm.structured.assert_not_called()
    content = out.read_text()
    assert "leer" in content.lower() or "(leer" in content


def test_scan_project_skips_llm_for_folder_with_only_lockfiles(tmp_path, mocker):
    folder = tmp_path / "5 OnlyLocks"
    folder.mkdir()
    (folder / "package-lock.json").write_text("{}")
    (folder / "yarn.lock").write_text("")

    fake_llm = mocker.Mock()
    out = scan_project(folder, llm=fake_llm, force=False)
    assert out is not None
    fake_llm.structured.assert_not_called()
