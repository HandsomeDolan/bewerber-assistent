from click.testing import CliRunner
from bewerber.cli import main


def test_cli_help_lists_command_groups():
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "profile" in result.output
    assert "projects" in result.output


def test_profile_help_lists_subcommands():
    runner = CliRunner()
    result = runner.invoke(main, ["profile", "--help"])
    assert result.exit_code == 0
    assert "init" in result.output
    assert "sync" in result.output


def test_projects_help_lists_scan():
    runner = CliRunner()
    result = runner.invoke(main, ["projects", "--help"])
    assert result.exit_code == 0
    assert "scan" in result.output


def test_projects_scan_iterates_folders(tmp_path, monkeypatch, mocker):
    monkeypatch.setenv("BEWERBER_DOCUMENTS", str(tmp_path))
    (tmp_path / "1 First").mkdir()
    (tmp_path / "1 First" / "README.md").write_text("# First")
    (tmp_path / "2 Second").mkdir()
    (tmp_path / "2 Second" / "README.md").write_text("# Second")
    (tmp_path / "ignored.txt").touch()

    fake_scan = mocker.patch("bewerber.cli.scan_project")
    fake_scan.return_value = tmp_path / "1 First" / "_profile.md"
    mocker.patch("bewerber.cli.LLMClient")

    runner = CliRunner()
    result = runner.invoke(main, ["projects", "scan"])
    assert result.exit_code == 0, result.output
    assert fake_scan.call_count == 2


def test_projects_scan_passes_force_flag(tmp_path, monkeypatch, mocker):
    monkeypatch.setenv("BEWERBER_DOCUMENTS", str(tmp_path))
    (tmp_path / "1 X").mkdir()
    fake_scan = mocker.patch("bewerber.cli.scan_project")
    mocker.patch("bewerber.cli.LLMClient")

    runner = CliRunner()
    result = runner.invoke(main, ["projects", "scan", "--force"])
    assert result.exit_code == 0
    _, kwargs = fake_scan.call_args
    assert kwargs.get("force") is True


def test_profile_sync_calls_sync_function(mocker):
    fake_sync = mocker.patch("bewerber.cli.sync_projects_into_profile")
    fake_sync.return_value = 3
    runner = CliRunner()
    result = runner.invoke(main, ["profile", "sync"])
    assert result.exit_code == 0, result.output
    assert "3" in result.output
    fake_sync.assert_called_once()


import yaml
from bewerber.shared.profile_schema import Person
from bewerber.profile.extractor import ExtractedProfile


def test_profile_init_writes_master_yaml(tmp_path, monkeypatch, mocker):
    bewerb_dir = tmp_path / "bewerber"
    bewerb_dir.mkdir(parents=True)
    docs_dir = tmp_path / "Bewerbungsunterlagen"
    docs_dir.mkdir()
    (docs_dir / "Lebenslauf.pdf").write_bytes(b"x")
    (docs_dir / "Bewerbungen").mkdir()
    (docs_dir / "Bewerbungen" / "Steve_KI.docx").write_bytes(b"x")

    monkeypatch.setenv("BEWERBER_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("BEWERBER_DOCUMENTS", str(tmp_path))
    monkeypatch.setattr(
        "bewerber.cli.extract_profile_from_documents",
        lambda d, llm: ExtractedProfile(
            person=Person(name="Steve", email="s@x.de"),
            berufsprofil="profil",
            zielposition=[],
            ausbildung=[],
            berufserfahrung=[],
            zertifikate=[],
            sprachen=[],
            interessen=[],
        ),
    )
    monkeypatch.setattr("bewerber.cli.LLMClient", mocker.Mock)
    monkeypatch.setattr(
        "bewerber.cli.save_anschreiben_examples",
        lambda srcs, out: [out / "01_x.txt"],
    )

    runner = CliRunner()
    # answer "no" to interactive anschreiben selection prompt → empty list
    result = runner.invoke(main, ["profile", "init"], input="\n")
    assert result.exit_code == 0, result.output

    master = bewerb_dir / "master_profile.yaml"
    assert master.exists()
    data = yaml.safe_load(master.read_text())
    assert data["person"]["name"] == "Steve"


def test_profile_init_aborts_if_master_exists_and_no_force(tmp_path, monkeypatch):
    bewerb_dir = tmp_path / "bewerber"
    bewerb_dir.mkdir(parents=True)
    (bewerb_dir / "master_profile.yaml").write_text("person: {name: existing}")
    docs_dir = tmp_path / "Bewerbungsunterlagen"
    docs_dir.mkdir()
    (docs_dir / "x.pdf").write_bytes(b"x")

    monkeypatch.setenv("BEWERBER_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("BEWERBER_DOCUMENTS", str(tmp_path))

    runner = CliRunner()
    result = runner.invoke(main, ["profile", "init"])
    assert result.exit_code != 0
    assert "existiert" in result.output.lower() or "force" in result.output.lower()


def test_tailor_requires_firma_and_rolle(tmp_path, mocker):
    posting = tmp_path / "posting.txt"
    posting.write_text("some job posting")
    runner = CliRunner()
    result = runner.invoke(main, ["tailor", "--posting-file", str(posting)])
    assert result.exit_code != 0
    assert "firma" in result.output.lower() or "missing" in result.output.lower()


def test_tailor_from_file_invokes_orchestrator(tmp_path, monkeypatch, mocker):
    posting = tmp_path / "posting.txt"
    posting.write_text("KI Manager bei BMW. Python gesucht.")

    monkeypatch.setattr("bewerber.cli.LLMClient", mocker.Mock)
    fake_tailor = mocker.patch("bewerber.cli.tailor")
    fake_result = mocker.Mock()
    fake_result.output_dir = tmp_path / "out"
    fake_result.lebenslauf_pdf = tmp_path / "out" / "lebenslauf.pdf"
    fake_result.anschreiben_pdf = tmp_path / "out" / "anschreiben.pdf"
    fake_tailor.return_value = fake_result

    runner = CliRunner()
    result = runner.invoke(main, [
        "tailor",
        "--posting-file", str(posting),
        "--firma", "BMW Group",
        "--rolle", "KI Manager",
        "--datum", "2026-06-12",
        "--kontakt", "Anna Müller",
    ])
    assert result.exit_code == 0, result.output

    inp = fake_tailor.call_args.args[0]
    assert inp.firma == "BMW Group"
    assert inp.rolle == "KI Manager"
    assert inp.datum == "2026-06-12"
    assert inp.kontakt_name == "Anna Müller"
    assert inp.source_url is None
    assert "KI Manager bei BMW" in inp.posting_text


def test_tailor_from_url_calls_snapshot(tmp_path, monkeypatch, mocker):
    monkeypatch.setattr("bewerber.cli.LLMClient", mocker.Mock)
    monkeypatch.setenv("BEWERBER_WORKSPACE", str(tmp_path))

    fake_snap = mocker.patch("bewerber.cli.snapshot_url", return_value="Posting text from URL.")
    fake_tailor = mocker.patch("bewerber.cli.tailor")
    fake_result = mocker.Mock()
    fake_result.output_dir = tmp_path / "out"
    fake_result.lebenslauf_pdf = tmp_path / "out" / "lebenslauf.pdf"
    fake_result.anschreiben_pdf = tmp_path / "out" / "anschreiben.pdf"
    fake_tailor.return_value = fake_result

    runner = CliRunner()
    result = runner.invoke(main, [
        "tailor",
        "--url", "https://example.com/job/123",
        "--firma", "BMW",
        "--rolle", "Manager",
        "--datum", "2026-06-12",
    ])
    assert result.exit_code == 0, result.output
    fake_snap.assert_called_once()
    inp = fake_tailor.call_args.args[0]
    assert inp.source_url == "https://example.com/job/123"
    assert inp.posting_text.startswith("Posting text from URL")


def test_tailor_rebuild_calls_rebuild_pdfs(tmp_path, monkeypatch, mocker):
    out_dir = tmp_path / "2026-06-12_BMW_KI"
    out_dir.mkdir()
    (out_dir / "lebenslauf.html").write_text("<html><body>test</body></html>")

    fake_rebuild = mocker.patch("bewerber.cli.rebuild_pdfs")
    runner = CliRunner()
    result = runner.invoke(main, ["tailor", "--rebuild", str(out_dir)])
    assert result.exit_code == 0, result.output
    fake_rebuild.assert_called_once_with(out_dir)
