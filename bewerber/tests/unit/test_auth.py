from pathlib import Path

from bewerber.dashboard import auth


def test_hash_verify_roundtrip():
    stored = auth.hash_password("hunter2pw")
    assert "$" in stored
    assert auth.verify_password("hunter2pw", stored) is True
    assert auth.verify_password("wrong", stored) is False


def test_make_username_schema_and_collision():
    assert auth.make_username("Steve", "Eigenwillig", {}) == "seigenwillig"
    assert auth.make_username("Test", "User", {}) == "tuser"
    # Sonderzeichen raus
    assert auth.make_username("Jean-Luc", "Picard!", {}) == "jpicard"
    # Kollision -> Suffix
    reg = {"seigenwillig": {}, "seigenwillig2": {}}
    assert auth.make_username("Sven", "Eigenwillig", reg) == "seigenwillig3"


def test_registry_save_load_roundtrip(tmp_path):
    path = tmp_path / "registry.json"
    assert auth.load_registry(path) == {}
    auth.save_registry(path, {"tuser": {"vorname": "Test"}})
    assert auth.load_registry(path)["tuser"]["vorname"] == "Test"


def test_register_user_creates_entry(tmp_path):
    path = tmp_path / "registry.json"
    username = auth.register_user(path, "Test", "User", "geheimpw1")
    assert username == "tuser"
    reg = auth.load_registry(path)
    assert reg["tuser"]["vorname"] == "Test"
    assert reg["tuser"]["nachname"] == "User"
    assert "pw_hash" in reg["tuser"]
    assert auth.authenticate(path, "tuser", "geheimpw1") is True
    assert auth.authenticate(path, "tuser", "falsch") is False
    assert auth.authenticate(path, "unbekannt", "geheimpw1") is False


def test_register_user_duplicate_name_gets_suffix(tmp_path):
    path = tmp_path / "registry.json"
    u1 = auth.register_user(path, "Test", "User", "geheimpw1")
    u2 = auth.register_user(path, "Tom", "User", "geheimpw2")
    assert u1 == "tuser"
    assert u2 == "tuser2"


def test_session_sign_verify_roundtrip():
    secret = "supersecret-key"
    cookie = auth.sign_session("tuser", secret)
    assert auth.verify_session(cookie, secret) == "tuser"


def test_session_rejects_tampering_and_wrong_secret():
    secret = "supersecret-key"
    cookie = auth.sign_session("tuser", secret)
    # Username manipuliert, Signatur passt nicht mehr
    tampered = "admin." + cookie.split(".", 1)[1]
    assert auth.verify_session(tampered, secret) is None
    # Falsches Secret
    assert auth.verify_session(cookie, "anderes-secret") is None
    # Müll
    assert auth.verify_session("kaputt", secret) is None
    assert auth.verify_session("", secret) is None


def test_session_roundtrip_with_dotted_username():
    secret = "supersecret-key"
    cookie = auth.sign_session("j.picard", secret)
    assert auth.verify_session(cookie, secret) == "j.picard"


def test_ensure_env_value_appends_and_is_stable(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("OPENAI_API_KEY=x\n", encoding="utf-8")
    counter = {"n": 0}

    def gen():
        counter["n"] += 1
        return f"generated{counter['n']}"

    v1 = auth.ensure_env_value(env_path, "BEWERBER_SECRET_KEY", gen)
    assert v1 == "generated1"
    assert "BEWERBER_SECRET_KEY=generated1" in env_path.read_text()
    # Zweiter Aufruf liest bestehenden Wert, generiert NICHT neu
    v2 = auth.ensure_env_value(env_path, "BEWERBER_SECRET_KEY", gen)
    assert v2 == "generated1"
    assert counter["n"] == 1


def test_delete_user_removes_registry_entry(tmp_path):
    reg = tmp_path / "registry.json"
    username = auth.register_user(reg, "Max", "Muster", "geheim123")
    assert auth.authenticate(reg, username, "geheim123")

    assert auth.delete_user(reg, username) is True
    assert username not in auth.load_registry(reg)
    assert not auth.authenticate(reg, username, "geheim123")


def test_delete_user_unknown_returns_false(tmp_path):
    reg = tmp_path / "registry.json"
    auth.register_user(reg, "Max", "Muster", "geheim123")
    assert auth.delete_user(reg, "gibtsnicht") is False
