import pytest
import yaml
from pathlib import Path

from bewerber.shared.anlagen import (
    Anlage,
    AnlagenConfig,
    copy_anlagen_to,
    load_anlagen,
)


def test_load_returns_empty_when_file_missing(tmp_path):
    cfg = load_anlagen(tmp_path / "does_not_exist.yaml")
    assert isinstance(cfg, AnlagenConfig)
    assert cfg.anlagen == []
    assert cfg.labels == []


def test_load_parses_yaml(tmp_path):
    f = tmp_path / "anlagen.yaml"
    f.write_text(yaml.safe_dump({
        "anlagen": [
            {"label": "Arbeitszeugnisse", "files": ["/some/cert.pdf"]},
            {"label": "Technikerzeugnis", "files": ["/p1.pdf", "/p2.pdf"]},
        ],
    }, allow_unicode=True))

    cfg = load_anlagen(f)
    assert cfg.labels == ["Arbeitszeugnisse", "Technikerzeugnis"]
    assert cfg.anlagen[1].files == [Path("/p1.pdf"), Path("/p2.pdf")]


def test_copy_copies_files_into_target(tmp_path):
    src_dir = tmp_path / "anlagen_src"
    src_dir.mkdir()
    a = src_dir / "Arbeitszeugnis.pdf"
    a.write_bytes(b"%PDF-1.4 fake")
    b1 = src_dir / "Technikerzeugnis_S1.pdf"
    b1.write_bytes(b"%PDF page1")
    b2 = src_dir / "Technikerzeugnis_S2.pdf"
    b2.write_bytes(b"%PDF page2")

    cfg = AnlagenConfig(anlagen=[
        Anlage(label="Arbeitszeugnisse", files=[a]),
        Anlage(label="Technikerzeugnis", files=[b1, b2]),
    ])
    target = tmp_path / "bewerbungsordner"
    target.mkdir()

    missing = copy_anlagen_to(cfg, target)

    assert missing == []
    assert (target / "Arbeitszeugnis.pdf").is_file()
    assert (target / "Technikerzeugnis_S1.pdf").is_file()
    assert (target / "Technikerzeugnis_S2.pdf").is_file()
    assert (target / "Arbeitszeugnis.pdf").read_bytes() == b"%PDF-1.4 fake"


def test_copy_records_missing_files_by_default(tmp_path):
    target = tmp_path / "out"
    target.mkdir()
    cfg = AnlagenConfig(anlagen=[
        Anlage(label="Fehlend", files=[tmp_path / "does_not_exist.pdf"]),
    ])

    missing = copy_anlagen_to(cfg, target)

    assert len(missing) == 1
    assert "does_not_exist.pdf" in missing[0]


def test_copy_raises_when_skip_missing_false(tmp_path):
    target = tmp_path / "out"
    target.mkdir()
    cfg = AnlagenConfig(anlagen=[
        Anlage(label="X", files=[tmp_path / "nope.pdf"]),
    ])

    with pytest.raises(FileNotFoundError):
        copy_anlagen_to(cfg, target, skip_missing=False)


def test_copy_handles_empty_config(tmp_path):
    target = tmp_path / "out"
    target.mkdir()

    assert copy_anlagen_to(AnlagenConfig(), target) == []
    assert list(target.iterdir()) == []
