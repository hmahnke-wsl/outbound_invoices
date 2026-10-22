"""Tests for the login gate (code/auth.py, wired into api.create_app) -- exercised
through the HTTP interface, against ldap3's in-memory MOCK_SYNC directory instead
of a real LDAP server.
"""
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from ldap3 import MOCK_SYNC, Connection, Server

from api import create_app
from auth import AuthSettings, LdapAuthenticator, settings_from_env

_USERS_OU = "ou=users,dc=wsl,dc=test"
_DASHBOARD_GROUP = "cn=invoice-tracking,ou=groups,dc=wsl,dc=test"


def _mock_directory(users: dict[str, str], groups: dict[str, list[str]] | None = None):
    """An ldap3 MOCK_SYNC directory seeded with {username: password} (and
    optional {username: [group DN, ...]}); returns a connection factory
    LdapAuthenticator binds through."""
    groups = groups or {}
    server = Server("fake")
    seed = Connection(server, user="cn=admin,dc=wsl,dc=test", password="x", client_strategy=MOCK_SYNC)
    for username, password in users.items():
        attrs = {"userPassword": password, "sAMAccountName": username}
        if groups.get(username):
            attrs["memberOf"] = groups[username]
        seed.strategy.add_entry(f"cn={username},{_USERS_OU}", attrs)

    def connect(user: str, password: str) -> Connection:
        return Connection(server, user=user, password=password, client_strategy=MOCK_SYNC)

    return connect


def _settings(**overrides) -> AuthSettings:
    base = AuthSettings(
        session_secret="test-secret",
        ldap_url="ldap://fake",
        user_template="cn={username},ou=users,dc=wsl,dc=test",
        cookie_secure=False,  # TestClient talks plain http://testserver
    )
    return replace(base, **overrides)


class FakeClock:
    def __init__(self, t: float = 1_000_000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t


def _client(tmp_path, *, auth=None, users=None, groups=None, clock=None) -> TestClient:
    auth = auth or _settings()
    authenticate = LdapAuthenticator(auth, connect=_mock_directory(users or {"jsmith": "s3cret"}, groups))
    return TestClient(create_app(tmp_path / "invoices.db", attachments_dir=tmp_path / "attachments",
                                 auth=auth, authenticate=authenticate, clock=clock or FakeClock()))


def _signed_in(tmp_path, **kwargs) -> TestClient:
    client = _client(tmp_path, **kwargs)
    resp = client.post("/api/auth/login", json={"username": "jsmith", "password": "s3cret"})
    assert resp.status_code == 200
    return client


def test_api_rejects_requests_without_a_session(tmp_path):
    client = _client(tmp_path)

    assert client.get("/api/invoices").status_code == 401


def test_without_a_login_gate_there_are_no_auth_routes(tmp_path):
    # The web app reads this 404 as "no gate" (AUTH_DISABLED) and goes straight to the dashboard.
    client = TestClient(create_app(tmp_path / "invoices.db"))

    assert client.get("/api/auth/me").status_code == 404
    assert client.get("/api/invoices").status_code == 200


def test_health_is_reachable_without_a_session(tmp_path):
    client = _client(tmp_path)

    resp = client.get("/api/health")

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_valid_login_sets_a_session_that_unlocks_the_api(tmp_path):
    client = _client(tmp_path, users={"jsmith": "s3cret"})

    resp = client.post("/api/auth/login", json={"username": "jsmith", "password": "s3cret"})

    assert resp.status_code == 200
    assert resp.json() == {"user": "jsmith"}
    assert client.get("/api/invoices").status_code == 200


@pytest.mark.parametrize("username, password", [
    ("jsmith", "wrong"),          # wrong password
    ("nobody", "s3cret"),         # no such user
    ("blank", ""),                # empty password: LDAP treats it as an anonymous bind that "succeeds"
    ("jsmith,ou=x", "s3cret"),    # DN-injection shaped username
    ("", "s3cret"),               # no username at all
])
def test_bad_login_is_rejected_and_sets_no_session(tmp_path, username, password):
    client = _client(tmp_path, users={"jsmith": "s3cret", "blank": ""})

    resp = client.post("/api/auth/login", json={"username": username, "password": password})

    assert resp.status_code == 401
    assert resp.json() == {"detail": "Incorrect username or password"}
    assert client.get("/api/invoices").status_code == 401


def test_me_reports_the_signed_in_user(tmp_path):
    client = _signed_in(tmp_path)

    resp = client.get("/api/auth/me")

    assert resp.status_code == 200
    assert resp.json() == {"user": "jsmith"}


def test_me_is_401_without_a_session(tmp_path):
    assert _client(tmp_path).get("/api/auth/me").status_code == 401


def test_a_tampered_session_cookie_is_rejected(tmp_path):
    client = _signed_in(tmp_path)
    token = client.cookies.get("it_session")
    client.cookies.set("it_session", token[:-2] + ("AA" if not token.endswith("AA") else "BB"))

    assert client.get("/api/invoices").status_code == 401
    assert client.get("/api/auth/me").status_code == 401


def test_a_session_signed_with_another_secret_is_rejected(tmp_path):
    other = _signed_in(tmp_path, auth=_settings(session_secret="someone-elses-secret"))
    client = _client(tmp_path)
    client.cookies.set("it_session", other.cookies.get("it_session"))

    assert client.get("/api/invoices").status_code == 401


def test_a_session_expires_after_twelve_hours(tmp_path):
    clock = FakeClock()
    client = _signed_in(tmp_path, clock=clock)

    clock.t += 12 * 3600 - 1
    assert client.get("/api/invoices").status_code == 200
    clock.t += 2
    assert client.get("/api/invoices").status_code == 401


def test_logout_ends_the_session(tmp_path):
    client = _signed_in(tmp_path)

    resp = client.post("/api/auth/logout")

    assert resp.status_code == 200
    assert client.get("/api/invoices").status_code == 401
    assert client.get("/api/auth/me").status_code == 401


@pytest.mark.parametrize("method, path", [
    ("GET", "/api/invoices"),
    ("PATCH", "/api/invoices/1"),
    ("GET", "/api/invoices/1/history"),
    ("GET", "/api/invoices/1/pdf"),
    ("GET", "/api/summary"),
    ("GET", "/api/paid-invoices"),
    ("GET", "/api/needs-attention"),
    ("GET", "/api/ignored"),
    ("GET", "/api/last-refresh"),
    ("POST", "/api/ingest"),
])
def test_every_dashboard_route_needs_a_session(tmp_path, method, path):
    client = _client(tmp_path)

    assert client.request(method, path).status_code == 401


def test_signed_in_user_can_open_an_invoice_pdf(tmp_path):
    from db import init_db

    (tmp_path / "attachments").mkdir()
    (tmp_path / "attachments" / "inv.pdf").write_bytes(b"%PDF-1.4")
    client = _signed_in(tmp_path)
    conn = init_db(tmp_path / "invoices.db")
    invoice_id = conn.execute("INSERT INTO invoices (customer, amount, pdf_file) VALUES ('Acme', 10, 'inv.pdf')").lastrowid
    conn.commit()
    conn.close()

    resp = client.get(f"/api/invoices/{invoice_id}/pdf")

    assert resp.status_code == 200
    assert resp.content == b"%PDF-1.4"


def _login(client, username, password):
    return client.post("/api/auth/login", json={"username": username, "password": password})


def test_five_failed_logins_lock_the_account_even_for_the_right_password(tmp_path):
    client = _client(tmp_path)
    for _ in range(5):
        assert _login(client, "jsmith", "wrong").status_code == 401

    resp = _login(client, "jsmith", "s3cret")

    assert resp.status_code == 429
    assert resp.json() == {"detail": "Too many attempts -- try again in 15 minutes"}
    assert client.get("/api/invoices").status_code == 401


def test_a_locked_account_unlocks_after_fifteen_minutes(tmp_path):
    clock = FakeClock()
    client = _client(tmp_path, clock=clock)
    for _ in range(5):
        _login(client, "jsmith", "wrong")

    clock.t += 15 * 60 + 1

    assert _login(client, "jsmith", "s3cret").status_code == 200


def test_lockout_is_per_username_and_case_insensitive(tmp_path):
    client = _client(tmp_path, users={"jsmith": "s3cret", "alee": "pw2"})
    for _ in range(5):
        _login(client, "JSmith", "wrong")

    assert _login(client, "jsmith", "s3cret").status_code == 429
    assert _login(client, "alee", "pw2").status_code == 200


def test_a_successful_login_clears_earlier_failures(tmp_path):
    client = _client(tmp_path)
    for _ in range(4):
        _login(client, "jsmith", "wrong")
    assert _login(client, "jsmith", "s3cret").status_code == 200
    for _ in range(4):
        _login(client, "jsmith", "wrong")

    assert _login(client, "jsmith", "s3cret").status_code == 200


def test_with_a_required_group_only_members_can_sign_in(tmp_path):
    client = _client(
        tmp_path,
        auth=_settings(base_dn="dc=wsl,dc=test", required_group=_DASHBOARD_GROUP),
        users={"jsmith": "s3cret", "alee": "pw2"},
        groups={"jsmith": [_DASHBOARD_GROUP], "alee": ["cn=marketing,ou=groups,dc=wsl,dc=test"]},
    )

    assert _login(client, "jsmith", "s3cret").status_code == 200
    assert _login(client, "alee", "pw2").status_code == 401


def test_an_unreachable_directory_is_a_503_and_does_not_count_toward_lockout(tmp_path):
    from ldap3.core.exceptions import LDAPSocketOpenError

    def unreachable(user, password):
        raise LDAPSocketOpenError("connection refused")

    auth = _settings()
    client = TestClient(create_app(tmp_path / "invoices.db", auth=auth,
                                   authenticate=LdapAuthenticator(auth, connect=unreachable)))

    for _ in range(6):
        resp = _login(client, "jsmith", "s3cret")
        assert resp.status_code == 503
        assert resp.json() == {"detail": "Can't reach the login server -- try again shortly"}


# --- settings_from_env ---------------------------------------------------- #

_GOOD_SECRET = "x" * 32
_FULL_ENV = {
    "SESSION_SECRET": _GOOD_SECRET,
    "LDAP_URL": "ldaps://ldap.wsl.test",
    "LDAP_USER_TEMPLATE": "{username}@worldsurfleague.com",
}


def test_auth_disabled_means_no_gate():
    assert settings_from_env({"AUTH_DISABLED": "true"}) is None


def test_full_env_builds_settings_with_secure_cookies_by_default():
    settings = settings_from_env(_FULL_ENV)

    assert settings.ldap_url == "ldaps://ldap.wsl.test"
    assert settings.user_template == "{username}@worldsurfleague.com"
    assert settings.cookie_secure is True
    assert settings.required_group is None


def test_optional_group_and_insecure_cookie_flag_are_read():
    settings = settings_from_env({**_FULL_ENV, "SESSION_COOKIE_SECURE": "false",
                                  "LDAP_REQUIRED_GROUP": "cn=g,dc=x", "LDAP_BASE_DN": "dc=x"})

    assert settings.cookie_secure is False
    assert settings.required_group == "cn=g,dc=x"
    assert settings.base_dn == "dc=x"


@pytest.mark.parametrize("env, missing", [
    ({}, "SESSION_SECRET, LDAP_URL, LDAP_USER_TEMPLATE"),
    ({k: v for k, v in _FULL_ENV.items() if k != "LDAP_URL"}, "LDAP_URL"),
    ({**_FULL_ENV, "LDAP_REQUIRED_GROUP": "cn=g,dc=x"}, "LDAP_BASE_DN"),
])
def test_missing_settings_fail_at_startup_naming_what_is_missing(env, missing):
    with pytest.raises(RuntimeError, match=f"missing: {missing}"):
        settings_from_env(env)


def test_a_short_session_secret_is_refused():
    with pytest.raises(RuntimeError, match="SESSION_SECRET must be at least 32 characters"):
        settings_from_env({**_FULL_ENV, "SESSION_SECRET": "short"})


def test_session_cookie_is_httponly_secure_lax_and_expires_with_the_session(tmp_path):
    client = _client(tmp_path, auth=_settings(cookie_secure=True))

    set_cookie = _login(client, "jsmith", "s3cret").headers["set-cookie"].lower()

    assert "httponly" in set_cookie
    assert "secure" in set_cookie
    assert "samesite=lax" in set_cookie
    assert f"max-age={12 * 3600}" in set_cookie


def test_plaintext_ldap_is_refused_unless_explicitly_allowed():
    env = {**_FULL_ENV, "LDAP_URL": "ldap://ldap.wsl.test"}
    with pytest.raises(RuntimeError, match="LDAP_URL must use ldaps://"):
        settings_from_env(env)

    assert settings_from_env({**env, "LDAP_ALLOW_PLAINTEXT": "true"}).ldap_url == "ldap://ldap.wsl.test"


# --- TLS certificate checking ---------------------------------------------- #

def test_ldaps_certificates_are_verified_by_default():
    import ssl

    from auth import ldap_server

    server = ldap_server(settings_from_env(_FULL_ENV))

    assert server.ssl is True
    assert server.tls.validate == ssl.CERT_REQUIRED


def test_a_private_ca_certificate_can_be_trusted(tmp_path):
    from auth import ldap_server

    ca = tmp_path / "azca1.pem"
    ca.write_text("-----BEGIN CERTIFICATE-----\n-----END CERTIFICATE-----\n")
    settings = settings_from_env({**_FULL_ENV, "LDAP_CA_CERT": str(ca)})

    assert ldap_server(settings).tls.ca_certs_file == str(ca)


def test_a_missing_ca_certificate_file_fails_at_startup():
    with pytest.raises(RuntimeError, match="LDAP_CA_CERT file not found"):
        settings_from_env({**_FULL_ENV, "LDAP_CA_CERT": "/nope/azca1.pem"})


def test_certificate_checking_can_be_switched_off_explicitly_for_local_testing():
    import ssl

    from auth import ldap_server

    settings = settings_from_env({**_FULL_ENV, "LDAP_TLS_VERIFY": "false"})

    assert settings.tls_verify is False
    assert ldap_server(settings).tls.validate == ssl.CERT_NONE
