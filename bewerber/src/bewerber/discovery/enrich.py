import hashlib
import requests
from readability import Document
from typing import Optional
import re

from bewerber.shared.state_schema import RawJob


def _hash_description(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def extract_main_text(html: str) -> str:
    """Use readability to isolate main content, then strip remaining tags."""
    summary_html = Document(html).summary()
    # Strip tags + collapse whitespace
    text = re.sub(r"<[^>]+>", " ", summary_html)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def enrich_job(job: RawJob, timeout: int = 20) -> RawJob:
    """Fetch the posting URL and populate description if not already present.

    On network failure: leave description as-is and return the job unchanged.
    """
    if job.description:
        return job

    try:
        resp = requests.get(
            job.url,
            headers={"User-Agent": "bewerber/0.1 (+https://github.com/)"},
            timeout=timeout,
        )
        resp.raise_for_status()
    except requests.RequestException:
        return job

    text = extract_main_text(resp.text)
    if not text:
        return job
    return job.model_copy(update={
        "description": text,
        "description_hash": _hash_description(text),
    })
