from bewerber.shared.slug import slug_part, bewerbungsordner_name


def test_slug_part_handles_umlauts():
    assert slug_part("Müller GmbH") == "Mueller-GmbH"
    assert slug_part("Bäcker & Söhne") == "Baecker-Soehne"


def test_slug_part_handles_special_chars():
    assert slug_part("KI Manager (m/w/d)") == "KI-Manager-m-w-d"
    assert slug_part("C++") == "C"  # special chars dropped


def test_slug_part_collapses_dashes():
    assert slug_part("A    B---C") == "A-B-C"


def test_slug_part_preserves_case():
    """Firma names like BMW, SAP should not become bmw, sap."""
    assert slug_part("BMW Group") == "BMW-Group"


def test_slug_part_strips_leading_trailing_dashes():
    assert slug_part("---hello---") == "hello"


def test_bewerbungsordner_name():
    name = bewerbungsordner_name("2026-06-12", "BMW Group", "KI Manager (m/w/d)")
    assert name == "2026-06-12_BMW-Group_KI-Manager-m-w-d"


def test_bewerbungsordner_name_empty_role():
    name = bewerbungsordner_name("2026-06-12", "Acme", "")
    assert name == "2026-06-12_Acme"
