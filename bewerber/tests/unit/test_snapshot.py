from pathlib import Path

from bewerber.tailoring.snapshot import (
    _looks_like_consent,
    _strip_tags,
    extract_job_text,
    snapshot_url,
)


def test_strip_tags_removes_html_tags():
    html = "<html><body><h1>KI Manager</h1><p>Sie&nbsp;leiten...</p><script>x()</script></body></html>"
    text = _strip_tags(html)
    assert "KI Manager" in text
    assert "Sie leiten" in text
    assert "<script>" not in text
    assert "x()" not in text


def test_extract_job_text_prefers_article(tmp_path):
    """When <article> exists, it wins over readability heuristics."""
    body = "Senior Consultant Digitalisierung gesucht. " * 30
    html = f"""
    <html><body>
      <header><p>Bei uns finden Sie Karriere</p></header>
      <article>{body}</article>
      <aside>Footer-Links und Werbung</aside>
    </body></html>
    """
    text = extract_job_text(html)
    assert "Senior Consultant" in text
    assert "Footer-Links" not in text


def test_extract_job_text_combines_multiple_articles_skips_small_recommendations():
    """Stepstone-Muster: ROLLE + PROFIL + BENEFITS als getrennte <article>s,
    Empfehlungs-Karten am Footer als kleine <article>s -> nur die grossen
    sollen kombiniert werden."""
    role = "DEINE ROLLE. Du berätst Kunden in der Prozessindustrie bei der Digitalisierung. " * 8
    profile = "DEIN PROFIL. Studium der Verfahrenstechnik oder Informatik. Erfahrung mit SAP. " * 8
    benefits = "DEINE BENEFITS. Flexible Arbeitszeiten, Bike-Leasing, Weiterbildung. " * 8
    related1 = "Andere Stelle bei Firma A"   # weniger als 300 Zeichen
    related2 = "Noch eine Stelle bei Firma B"
    html = f"""
    <html><body>
      <article>{role}</article>
      <article>{profile}</article>
      <article>{benefits}</article>
      <article>{related1}</article>
      <article>{related2}</article>
    </body></html>
    """
    text = extract_job_text(html)
    assert "DEINE ROLLE" in text
    assert "DEIN PROFIL" in text
    assert "DEINE BENEFITS" in text
    # Aehnliche-Stellen-Karten unter MIN_BLOCK_CHARS sollen NICHT drin sein
    assert "Firma A" not in text
    assert "Firma B" not in text


def test_extract_job_text_dedupes_nested_blocks():
    """Wenn <main> ein <article> enthaelt, soll nur EINER der beiden in den Output landen."""
    content = "Senior Consultant Digitalisierung. " * 30
    html = f"""
    <html><body>
      <main>
        <article>{content}</article>
      </main>
    </body></html>
    """
    text = extract_job_text(html)
    # Exakt eine Wiederholung der Phrase, nicht doppelt
    assert text.count("Senior Consultant Digitalisierung") == 30


def test_extract_job_text_strips_consent_containers():
    """Cookie-Banner mit id=GDPRConsentManagerContainer wird vor Extraktion entfernt."""
    consent_text = (
        "Wir uebermitteln personenbezogene Daten an Drittanbieter. "
        "Cookies werden gesetzt. Datenschutzerklaerung. Tracking. Akzeptieren. "
    ) * 5
    real_text = "Senior Consultant Digitalisierung fuer die Prozessindustrie. " * 30
    html = f"""
    <html><body>
      <div id="GDPRConsentManagerContainer">{consent_text}</div>
      <article>{real_text}</article>
    </body></html>
    """
    text = extract_job_text(html)
    assert "Senior Consultant" in text
    # Consent-Text darf NICHT enthalten sein (Container wurde entfernt)
    assert "Datenschutzerklaerung" not in text


def test_extract_job_text_skips_consent_looking_articles():
    """Wenn ein <article> wie Consent klingt, wird das andere bevorzugt."""
    consent_in_article = (
        "Cookies und Tracking. Akzeptieren Sie unsere Datenschutzerklaerung. "
        "Wir verwenden Cookies fuer Marketing-Zwecke. Akzeptieren. "
    ) * 8
    real = "Stellenbeschreibung: KI Manager bei Acme GmbH. " * 30
    html = f"""
    <html><body>
      <article>{consent_in_article}</article>
      <article>{real}</article>
    </body></html>
    """
    text = extract_job_text(html)
    assert "KI Manager bei Acme" in text
    assert "Marketing-Zwecke" not in text


def test_looks_like_consent_keyword_threshold():
    assert _looks_like_consent("cookie akzeptieren datenschutz tracking einwilligung")
    assert not _looks_like_consent("KI Manager bei Acme. Sie leiten ein Team.")


def test_snapshot_url_writes_files_and_uses_domcontentloaded(tmp_path, mocker):
    long_main = "Beschreibung der KI Manager Stelle. " * 30
    html_with_main = f"<html><body><article>{long_main}</article></body></html>"

    fake_page = mocker.Mock()
    fake_page.content.return_value = html_with_main
    fake_page.pdf.return_value = b"%PDF-fake"
    # Get_by_role raises -> consent dismissal silently skipped
    fake_page.get_by_role.side_effect = Exception("not present")

    fake_context = mocker.Mock()
    fake_context.new_page.return_value = fake_page
    fake_browser = mocker.Mock()
    fake_browser.new_context.return_value = fake_context
    fake_pw = mocker.Mock()
    fake_pw.chromium.launch.return_value = fake_browser
    fake_ctx_mgr = mocker.MagicMock()
    fake_ctx_mgr.__enter__.return_value = fake_pw
    mocker.patch("bewerber.tailoring.snapshot.sync_playwright", return_value=fake_ctx_mgr)

    text = snapshot_url("https://example.com/job", tmp_path)

    assert (tmp_path / "posting.html").is_file()
    assert (tmp_path / "posting.pdf").is_file()
    assert "KI Manager" in text

    fake_page.goto.assert_called_once_with(
        "https://example.com/job",
        wait_until="domcontentloaded",
        timeout=45000,
    )
    fake_browser.new_context.assert_called_once()
    assert "Chrome" in fake_browser.new_context.call_args.kwargs["user_agent"]


def test_snapshot_falls_back_to_requests_on_playwright_crash(tmp_path, mocker):
    """Wenn Playwright crashed, soll snapshot_url auf requests.get ausweichen."""
    long_article = "<html><body><article>" + "Job Beschreibung " * 60 + "</article></body></html>"

    # Playwright wirft direkt beim Context-Entry
    crashing_ctx = mocker.MagicMock()
    crashing_ctx.__enter__.side_effect = RuntimeError("Page.content: Target crashed")
    mocker.patch("bewerber.tailoring.snapshot.sync_playwright", return_value=crashing_ctx)

    # requests.get liefert sauberes HTML
    fake_resp = mocker.Mock()
    fake_resp.text = long_article
    fake_resp.raise_for_status = mocker.Mock()
    mocker.patch("bewerber.tailoring.snapshot.requests.get", return_value=fake_resp)

    text = snapshot_url("https://linkedin.com/jobs/view/42", tmp_path)
    assert "Job Beschreibung" in text
    # posting.html geschrieben, posting.pdf NICHT (kein Playwright = kein PDF)
    assert (tmp_path / "posting.html").is_file()
    assert not (tmp_path / "posting.pdf").exists()


def test_snapshot_raises_when_both_paths_fail(tmp_path, mocker):
    """Playwright crash + requests liefert leere Seite -> klare Fehlermeldung."""
    crashing_ctx = mocker.MagicMock()
    crashing_ctx.__enter__.side_effect = RuntimeError("Target crashed")
    mocker.patch("bewerber.tailoring.snapshot.sync_playwright", return_value=crashing_ctx)

    # Login wall returnt z.B. nur "Bitte einloggen"
    fake_resp = mocker.Mock()
    fake_resp.text = "<html><body>Bitte einloggen, um den Job zu sehen.</body></html>"
    fake_resp.raise_for_status = mocker.Mock()
    mocker.patch("bewerber.tailoring.snapshot.requests.get", return_value=fake_resp)

    import pytest
    with pytest.raises(RuntimeError, match="Beide Snapshot-Wege"):
        snapshot_url("https://linkedin.com/jobs/view/42", tmp_path)


def test_snapshot_tolerates_networkidle_failure(tmp_path, mocker):
    html = "<html><body><article>" + "Job Beschreibung " * 50 + "</article></body></html>"

    fake_page = mocker.Mock()
    fake_page.content.return_value = html
    fake_page.pdf.return_value = b"%PDF"
    fake_page.wait_for_load_state.side_effect = Exception("trackers")
    fake_page.get_by_role.side_effect = Exception("no consent button")

    fake_context = mocker.Mock()
    fake_context.new_page.return_value = fake_page
    fake_browser = mocker.Mock()
    fake_browser.new_context.return_value = fake_context
    fake_pw = mocker.Mock()
    fake_pw.chromium.launch.return_value = fake_browser
    fake_ctx_mgr = mocker.MagicMock()
    fake_ctx_mgr.__enter__.return_value = fake_pw
    mocker.patch("bewerber.tailoring.snapshot.sync_playwright", return_value=fake_ctx_mgr)

    text = snapshot_url("https://stepstone.de/job/x", tmp_path)
    assert "Job Beschreibung" in text
