"""Headless-Chromium-Snapshot fuer Job-Postings.

Hintergrund zur `wait_until`-Wahl: "networkidle" wartet auf 500 ms ohne
Netzwerk-Aktivitaet. Tracker-/Analytics-lastige Job-Boards (Stepstone,
LinkedIn, ...) erreichen das nie zuverlaessig. Deshalb hier
"domcontentloaded" plus best-effort networkidle-Wartung mit 3-Sekunden-Cap.

Consent-Banner: viele Boards (Stepstone, indeed, ...) blenden ein Cookie-/
Datenschutz-Overlay ein, das readability-lxml als "Hauptcontent" einstuft.
Wir versuchen das Banner per Click (Text-Selektor, sprach-agnostisch)
wegzudruecken, BEVOR wir den HTML-Stand snapshoten. Wenn der Click
fehlschlaegt, hilft der Content-Extraktor: er bevorzugt <article>- bzw.
<main>-Container und filtert Texte raus, die nach Consent klingen.

Fallback: Wenn Playwright crashed (z.B. LinkedIn anti-bot triggert
"Target crashed"), wechseln wir auf einen reinen requests.get-Pfad.
Damit gibt es keinen PDF-Snapshot, aber wenigstens den Text - die
nachgelagerten Schritte (Scoring, Customize) brauchen nur den Text.
"""
import json
import logging
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests
from lxml import html as lxml_html
from playwright.sync_api import Page, sync_playwright

from bewerber.discovery.enrich import extract_main_text

log = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0.0.0 Safari/537.36"
)

DEFAULT_TIMEOUT_MS = 45000
NETWORK_IDLE_GRACE_MS = 3000
CONSENT_CLICK_TIMEOUT_MS = 1500

# Beschriftungen, die typische Accept-all-Buttons tragen (Text-Selektor
# matched mit Playwright per :has-text). Reihenfolge: spezifisch -> generisch.
CONSENT_BUTTON_LABELS = [
    "Alle akzeptieren",
    "Alle Cookies akzeptieren",
    "Accept all",
    "Accept All Cookies",
    "Akzeptieren",
    "Zustimmen",
    "Agree",
    "I agree",
    "OK",
]

# Klassische Consent-Wrapper-IDs/Klassen. Werden aus dem HTML entfernt,
# falls der Click-Versuch fehlgeschlagen ist - readability wuerde sonst den
# Banner-Text als Hauptcontent ausgeben.
CONSENT_CONTAINER_XPATHS = [
    "//*[@id='GDPRConsentManagerContainer']",       # Stepstone
    "//*[@id='ccmgt_explicit_cookie_policy']",      # Stepstone Variante
    "//*[@id='onetrust-banner-sdk']",               # OneTrust
    "//*[@id='onetrust-consent-sdk']",
    "//*[@id='CybotCookiebotDialog']",              # Cookiebot
    "//*[contains(@class, 'cmp-container')]",       # generisch
    "//*[contains(@class, 'cookie-banner')]",
    "//*[contains(@class, 'consent-banner')]",
]

# Wenn ein Text-Block (>500 chars) drei oder mehr dieser Keywords enthaelt,
# behandeln wir ihn als Consent-Inhalt und ignorieren.
_CONSENT_KEYWORDS = ("cookie", "akzeptieren", "datenschutz", "tracking", "einwilligung")


def snapshot_url(url: str, out_dir: Path, *, timeout_ms: int = DEFAULT_TIMEOUT_MS) -> str:
    """Try Playwright first; if it crashes/times-out, fall back to requests.

    Returns extracted job text. Writes:
      - posting.html (immer)
      - posting.pdf  (nur bei erfolgreichem Playwright-Lauf)
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    # Ashby ist eine reine JS-SPA: der HTML-Stand enthaelt fast keinen Text,
    # der Job-Inhalt wird erst per API nachgeladen. Weder Playwright (auf dem
    # RasPi gar nicht erst verfuegbar) noch requests liefern brauchbaren Text.
    # Ashby hat aber eine oeffentliche, unauthentifizierte Posting-API. Greift
    # fuer direkte jobs.ashbyhq.com-URLs UND fuer eingebettete Boards wie
    # n8n.io/careers/?ashby_jid=... (dort steht die Beschreibung weit unten und
    # wird vom generischen Extraktor nicht zuverlaessig erkannt).
    orgs, job_id = _resolve_ashby(url)
    if job_id is not None:
        try:
            return _snapshot_via_ashby_api(orgs, job_id, out_dir)
        except Exception as e:  # noqa: BLE001 - API weg/umbenannt -> normaler Weg
            log.warning(
                "[snapshot] Ashby-API fuer %s fehlgeschlagen (%s). Falle auf den normalen Weg zurueck.",
                url, e,
            )

    try:
        return _snapshot_via_playwright(url, out_dir, timeout_ms)
    except Exception as e:  # noqa: BLE001 - crashes / timeouts / nav errors -> versuche requests
        log.warning(
            "[snapshot] Playwright fuer %s fehlgeschlagen (%s). Falle auf requests zurueck.",
            url, e,
        )
        return _snapshot_via_requests(url, out_dir)


# Direkte Ashby-Posting-URLs: jobs.ashbyhq.com/<orgSlug>/<jobId>[?...]
_ASHBY_HOST_RE = re.compile(r"(?:^|\.)ashbyhq\.com$", re.IGNORECASE)
_UUID_RE = re.compile(r"[0-9a-fA-F-]{16,}")


def _resolve_ashby(url: str) -> tuple[list[str], str | None]:
    """Erkennt Ashby-Postings (direkt ODER eingebettet).

    Liefert (org_kandidaten, job_id). job_id ist None, wenn die URL kein
    Ashby-Posting ist. Fuer eingebettete Boards (?ashby_jid=...) ist der
    Org-Slug nicht in der URL enthalten - wir leiten Kandidaten aus dem Host
    ab und probieren sie in _snapshot_via_ashby_api der Reihe nach durch.
    """
    try:
        parsed = urlparse(url)
    except Exception:  # noqa: BLE001
        return [], None
    host = (parsed.netloc or "").split(":")[0]

    # Fall 1: direkte jobs.ashbyhq.com/<org>/<jobId>-URL
    if _ASHBY_HOST_RE.search(host):
        parts = [p for p in (parsed.path or "").split("/") if p]
        if len(parts) >= 2 and _UUID_RE.fullmatch(parts[1]):
            return [parts[0]], parts[1]

    # Fall 2: eingebettetes Board, z.B. n8n.io/careers/?ashby_jid=<jobId>
    qs = parse_qs(parsed.query or "")
    jid = (qs.get("ashby_jid") or [""])[0].strip()
    if jid and _UUID_RE.fullmatch(jid):
        return _ashby_org_candidates(host), jid

    return [], None


def _ashby_org_candidates(host: str) -> list[str]:
    """Plausible Ashby-Board-Slugs aus dem Host raten (n8n.io -> 'n8n')."""
    labels = [l for l in host.lower().split(".") if l and l != "www"]
    _TLDS = {"com", "io", "co", "net", "org", "ai", "dev", "app", "jobs", "careers", "uk", "de"}
    candidates: list[str] = []
    # Haupt-Label: vorletztes (n8n.io -> n8n, careers.acme.io -> acme), dann erstes.
    if len(labels) >= 2:
        candidates.append(labels[-2])
    candidates += [l for l in labels if l not in _TLDS]
    # dedupe unter Beibehaltung der Reihenfolge
    seen: set[str] = set()
    return [c for c in candidates if not (c in seen or seen.add(c))]


def _snapshot_via_ashby_api(
    orgs: list[str], job_id: str, out_dir: Path, *, timeout_s: int = 20,
) -> str:
    """Holt das Posting ueber die oeffentliche Ashby-Job-Board-API.

    Probiert die Org-Kandidaten der Reihe nach; nimmt den ersten, der das
    Posting enthaelt. Schreibt posting.html (die descriptionHtml), kein PDF.
    Die nachgelagerte LLM-Pipeline braucht nur den Text.
    """
    job = None
    tried: list[str] = []
    for org in orgs:
        api = f"https://api.ashbyhq.com/posting-api/job-board/{org}?includeCompensation=true"
        try:
            resp = requests.get(api, headers={"User-Agent": USER_AGENT}, timeout=timeout_s)
            resp.raise_for_status()
            jobs = (resp.json() or {}).get("jobs", [])
        except Exception:  # noqa: BLE001 - falscher Slug -> naechster Kandidat
            tried.append(org)
            continue
        tried.append(org)
        job = next(
            (j for j in jobs if j.get("id") == job_id or job_id in (j.get("jobUrl") or "")),
            None,
        )
        if job is not None:
            break

    if job is None:
        raise RuntimeError(
            f"Job {job_id} in keinem Ashby-Board gefunden (geprueft: {', '.join(tried) or '-'}) "
            f"- evtl. abgelaufen, unveroeffentlicht oder anderer Board-Slug."
        )

    desc_html = job.get("descriptionHtml") or ""
    (out_dir / "posting.html").write_text(desc_html, encoding="utf-8")

    # Strukturierte Felder voranstellen - die SPA zeigt sie auch separat an.
    header_lines = [f"# {job.get('title', '').strip()}"]
    if job.get("location"):
        header_lines.append(f"Standort: {job['location']}")
    if job.get("employmentType"):
        header_lines.append(f"Beschaeftigungsart: {job['employmentType']}")
    if job.get("department") or job.get("team"):
        header_lines.append(f"Bereich: {job.get('department') or ''} / {job.get('team') or ''}".strip(" /"))
    header = "\n".join(line for line in header_lines if line.strip())

    body = job.get("descriptionPlain") or extract_job_text(desc_html)
    text = f"{header}\n\n{body}".strip()
    if not text or len(text) < 100:
        raise RuntimeError(f"Ashby-API lieferte fuer {job_id} zu wenig Text ({len(text)} Zeichen).")
    return text


def _snapshot_via_playwright(url: str, out_dir: Path, timeout_ms: int) -> str:
    """Primary path: headless Chromium + PDF + extract."""
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            context = browser.new_context(user_agent=USER_AGENT)
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            try:
                page.wait_for_load_state("networkidle", timeout=NETWORK_IDLE_GRACE_MS)
            except Exception:  # noqa: BLE001 - trackers may keep firing forever
                pass
            _try_dismiss_consent(page)
            html = page.content()
            pdf_bytes = page.pdf(
                format="A4",
                margin={"top": "1cm", "right": "1cm", "bottom": "1cm", "left": "1cm"},
            )
        finally:
            browser.close()

    (out_dir / "posting.html").write_text(html, encoding="utf-8")
    (out_dir / "posting.pdf").write_bytes(pdf_bytes)
    return extract_job_text(html)


def _snapshot_via_requests(url: str, out_dir: Path, *, timeout_s: int = 20) -> str:
    """Fallback: plain HTTP GET + readability/article extraction.

    Kein PDF. Funktioniert nur fuer Seiten ohne JS-Pflicht, kann an Login-Walls
    scheitern. Die nachgelagerte LLM-Pipeline kommt auch ohne PDF aus.
    """
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "de,en;q=0.7",
    }
    resp = requests.get(url, headers=headers, timeout=timeout_s, allow_redirects=True)
    resp.raise_for_status()
    html = resp.text
    (out_dir / "posting.html").write_text(html, encoding="utf-8")
    text = extract_job_text(html)
    if not text or len(text) < 100:
        raise RuntimeError(
            f"Beide Snapshot-Wege ergaben zu wenig Text fuer {url} "
            f"(Playwright crashed, requests lieferte {len(text or '')} Zeichen - "
            f"vermutlich Login-Wall). Kopier den Job-Text manuell und benutze "
            f"den --posting-file-Modus."
        )
    return text


def _try_dismiss_consent(page: Page) -> None:
    """Best-effort consent-banner dismissal via text selectors. Never raises."""
    for label in CONSENT_BUTTON_LABELS:
        try:
            page.get_by_role("button", name=label).first.click(
                timeout=CONSENT_CLICK_TIMEOUT_MS,
            )
            page.wait_for_timeout(500)
            return
        except Exception:  # noqa: BLE001 - we try one after the other
            continue


MIN_BLOCK_CHARS = 300  # alles drueber zaehlt als sinnvoller Content-Block


def extract_job_text(html: str) -> str:
    """Extract the job-posting main text from snapshot HTML.

    Strategy:
      1. Remove known consent-container elements (Stepstone, OneTrust, ...).
      2. Sammle ALLE <article>/<main>-Bloecke, die nicht nach Consent klingen,
         deduplicate sie und reihe sie in DOM-Reihenfolge aneinander. Damit
         decken wir Boards ab, die das Posting in mehrere Sub-Sektionen
         splitten (Stepstone: ROLLE / PROFIL / BENEFITS).
         Verworfen werden Mini-Bloecke (<300 Zeichen) - das filtert die
         "Aehnliche Stellen"-Karten am Footer raus.
      3. Fall back to readability-lxml on the cleaned HTML.
      4. Last resort: tag-stripped raw HTML.
    """
    try:
        tree = lxml_html.fromstring(html)
    except Exception:  # noqa: BLE001 - malformed HTML -> raw fallback
        return _strip_tags(html)

    for xp in CONSENT_CONTAINER_XPATHS:
        for el in tree.xpath(xp):
            parent = el.getparent()
            if parent is not None:
                parent.remove(el)

    blocks: list[str] = []
    seen: set[str] = set()
    # XPath-Union haelt die DOM-Reihenfolge bei (article vor main, falls beides verschachtelt).
    for el in tree.xpath("//article | //main"):
        text = re.sub(r"\s+", " ", " ".join(el.itertext())).strip()
        if len(text) < MIN_BLOCK_CHARS:
            continue
        if _looks_like_consent(text):
            continue
        # Dedupe: <main> kann <article>s enthalten, dann waeren beide quasi gleicher Text.
        # Wir verwerfen Bloecke, deren Text bereits Teil eines vorherigen ist
        # (oder umgekehrt: einen neuen Block droppen, falls er schon abgedeckt wird).
        if any(text in existing or existing in text for existing in seen):
            continue
        blocks.append(text)
        seen.add(text)
    if blocks:
        return "\n\n".join(blocks)

    cleaned_html = lxml_html.tostring(tree, encoding="unicode")
    text = extract_main_text(cleaned_html)
    if text and len(text) >= 200 and not _looks_like_consent(text):
        return text
    return _strip_tags(cleaned_html)


def _looks_like_consent(text: str) -> bool:
    lower = text.lower()
    return sum(1 for kw in _CONSENT_KEYWORDS if kw in lower) >= 3


def _strip_tags(html: str) -> str:
    """Fallback: roher Regex-Stripper, falls strukturierte Extraktion versagt."""
    text = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = (text
            .replace("&nbsp;", " ").replace("&amp;", "&")
            .replace("&lt;", "<").replace("&gt;", ">")
            .replace("&quot;", '"').replace("&#39;", "'"))
    return re.sub(r"\s+", " ", text).strip()


# Backward-compatible alias for any callers of the old internal name
_extract_text_from_html = _strip_tags
