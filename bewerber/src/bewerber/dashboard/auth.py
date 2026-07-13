"""Auth-Primitive fuer das Multi-User-Dashboard. Reine stdlib, keine Dependencies."""
import hashlib
import hmac
import json
import os
import re
import secrets
from pathlib import Path
from typing import Callable, Optional

_SCRYPT_N = 2 ** 14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SALT_BYTES = 16
_NONALNUM = re.compile(r"[^a-z0-9]")


def hash_password(password: str) -> str:
    """scrypt-Hash mit zufaelligem Salt. Rueckgabe '<salt_hex>$<hash_hex>'."""
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P
    )
    return f"{salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, hash_hex = stored.split("$", 1)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
    except (ValueError, AttributeError):
        return False
    actual = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P
    )
    return hmac.compare_digest(actual, expected)


def make_username(vorname: str, nachname: str, registry: dict) -> str:
    base = _NONALNUM.sub("", (vorname[:1] + nachname).lower()) or "user"
    if base not in registry:
        return base
    n = 2
    while f"{base}{n}" in registry:
        n += 1
    return f"{base}{n}"


def load_registry(path: Path) -> dict:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_registry(path: Path, registry: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def register_user(path: Path, vorname: str, nachname: str, password: str) -> str:
    registry = load_registry(path)
    username = make_username(vorname, nachname, registry)
    registry[username] = {
        "vorname": vorname,
        "nachname": nachname,
        "pw_hash": hash_password(password),
    }
    save_registry(path, registry)
    return username


def delete_user(path: Path, username: str) -> bool:
    """Entfernt den User aus der Registry. True, wenn er existierte."""
    registry = load_registry(path)
    if username not in registry:
        return False
    del registry[username]
    save_registry(path, registry)
    return True


def authenticate(path: Path, username: str, password: str) -> bool:
    registry = load_registry(path)
    entry = registry.get(username)
    if not entry:
        return False
    return verify_password(password, entry.get("pw_hash", ""))


def sign_session(username: str, secret: str) -> str:
    sig = hmac.new(secret.encode("utf-8"), username.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{username}.{sig}"


def verify_session(cookie_value: str, secret: str) -> Optional[str]:
    if not cookie_value or "." not in cookie_value:
        return None
    username, _, sig = cookie_value.rpartition(".")
    if not username or not sig:
        return None
    expected = hmac.new(secret.encode("utf-8"), username.encode("utf-8"), hashlib.sha256).hexdigest()
    if hmac.compare_digest(sig, expected):
        return username
    return None


def ensure_env_value(env_path: Path, key: str, generator: Callable[[], str]) -> str:
    """Liest key aus .env; generiert + haengt an, falls fehlt. Gibt den Wert zurueck."""
    existing = ""
    if env_path.is_file():
        existing = env_path.read_text(encoding="utf-8")
        for line in existing.splitlines():
            stripped = line.strip()
            if stripped.startswith(f"{key}="):
                return stripped.split("=", 1)[1]
    value = generator()
    sep = "" if existing.endswith("\n") or not existing else "\n"
    with env_path.open("a", encoding="utf-8") as fh:
        fh.write(f"{sep}{key}={value}\n")
    return value
