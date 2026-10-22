"""Login gate for the hosted dashboard, the same LDAP sign-in as Friday Dashboard's.

IT asked for LDAP: the login form's username/password are checked by binding
*as that user* against the directory, then a signed session cookie carries
the identity. A cookie (not a bearer token) because the invoice PDF link
(`<a target=_blank>`) can't send headers.
"""
from __future__ import annotations

import logging
import os
import re
import threading
from dataclasses import dataclass

# A plain directory username (optionally user@domain). Anything else -- commas,
# '=', parens, '*' -- is refused before it gets near a DN or a search filter.
_USERNAME = re.compile(r"^[A-Za-z0-9._-]{1,64}(@[A-Za-z0-9.-]{1,190})?$")


@dataclass(frozen=True)
class AuthSettings:
    session_secret: str
    ldap_url: str
    # e.g. "{username}@worldsurfleague.com" (AD UPN bind) or a full DN template
    user_template: str
    cookie_secure: bool = True
    session_max_age_seconds: int = 12 * 3600
    # Optional: only members of this group DN may sign in (searched under base_dn)
    required_group: str | None = None
    base_dn: str | None = None
    user_filter: str = "(sAMAccountName={username})"
    # ldaps:// certificate checking. Off only for local testing against a
    # directory whose certificate can't be verified yet (LDAP_TLS_VERIFY=false).
    tls_verify: bool = True
    # PEM file of a private CA to trust (e.g. WSL's internal AZCA1-CA)
    ca_cert_file: str | None = None


_MIN_SECRET_LEN = 32


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in ("1", "true", "yes")


def settings_from_env(env) -> AuthSettings | None:
    """None when AUTH_DISABLED is set (local dev only). Otherwise every
    required setting must be present -- the server refuses to start rather
    than run ungated."""
    if _truthy(env.get("AUTH_DISABLED")):
        return None
    required = ["SESSION_SECRET", "LDAP_URL", "LDAP_USER_TEMPLATE"]
    if env.get("LDAP_REQUIRED_GROUP"):
        required.append("LDAP_BASE_DN")
    missing = [name for name in required if not env.get(name)]
    if missing:
        raise RuntimeError(f"login is enabled but settings are missing: {', '.join(missing)} "
                           "(set them, or AUTH_DISABLED=true for local dev)")
    if len(env["SESSION_SECRET"]) < _MIN_SECRET_LEN:
        raise RuntimeError(f"SESSION_SECRET must be at least {_MIN_SECRET_LEN} characters")
    if not env["LDAP_URL"].lower().startswith("ldaps://") and not _truthy(env.get("LDAP_ALLOW_PLAINTEXT")):
        # The bind carries the user's real password -- never over an unencrypted connection by accident.
        raise RuntimeError("LDAP_URL must use ldaps:// (or set LDAP_ALLOW_PLAINTEXT=true to override)")
    ca_cert_file = env.get("LDAP_CA_CERT") or None
    if ca_cert_file and not os.path.isfile(ca_cert_file):
        raise RuntimeError(f"LDAP_CA_CERT file not found: {ca_cert_file}")
    tls_verify = env.get("LDAP_TLS_VERIFY", "true").strip().lower() != "false"
    if not tls_verify:
        logging.getLogger(__name__).warning(
            "LDAP_TLS_VERIFY=false: the directory's certificate is NOT checked -- local testing only")
    return AuthSettings(
        session_secret=env["SESSION_SECRET"],
        ldap_url=env["LDAP_URL"],
        user_template=env["LDAP_USER_TEMPLATE"],
        cookie_secure=env.get("SESSION_COOKIE_SECURE", "true").strip().lower() != "false",
        required_group=env.get("LDAP_REQUIRED_GROUP") or None,
        base_dn=env.get("LDAP_BASE_DN") or None,
        tls_verify=tls_verify,
        ca_cert_file=ca_cert_file,
    )


# Not Friday Dashboard's "fd_session": cookies ignore the port, so both
# dashboards on one host would otherwise overwrite each other's session.
SESSION_COOKIE = "it_session"


class DirectoryUnavailable(Exception):
    """The LDAP server couldn't be reached -- not the user's fault, so it
    must not count as a failed login."""


def ldap_server(settings: AuthSettings):
    """The ldap3 Server for `settings.ldap_url`. For ldaps://, the server's
    certificate must chain to a trusted CA and match its hostname -- otherwise
    anything answering on that address could collect users' passwords."""
    import ssl

    from ldap3 import Server, Tls

    tls = Tls(
        validate=ssl.CERT_REQUIRED if settings.tls_verify else ssl.CERT_NONE,
        ca_certs_file=settings.ca_cert_file,
    )
    return Server(settings.ldap_url, connect_timeout=5, tls=tls)


def _default_connect(settings: AuthSettings):
    from ldap3 import Connection

    server = ldap_server(settings)

    def connect(user: str, password: str):
        return Connection(server, user=user, password=password, receive_timeout=10)

    return connect


class LdapAuthenticator:
    """`authenticate(username, password) -> bool` by binding as that user.
    `connect(user, password)` builds an unbound ldap3 Connection -- swappable
    so tests can bind against ldap3's MOCK_SYNC directory."""

    def __init__(self, settings: AuthSettings, connect=None):
        self._settings = settings
        self._connect = connect or _default_connect(settings)

    def __call__(self, username: str, password: str) -> bool:
        # An empty password is an LDAP *anonymous* bind, which most servers
        # accept -- it must never count as a successful login.
        if not password or not _USERNAME.match(username):
            return False
        from ldap3.core.exceptions import LDAPException

        conn = None
        try:
            conn = self._connect(self._settings.user_template.format(username=username), password)
            if not conn.bind():
                return False
            return self._settings.required_group is None or self._in_required_group(conn, username)
        except LDAPException as exc:
            raise DirectoryUnavailable(str(exc)) from exc
        finally:
            if conn is not None and not conn.closed:  # also closes the socket after a failed bind
                conn.unbind()

    def _in_required_group(self, conn, username: str) -> bool:
        from ldap3.utils.conv import escape_filter_chars

        user = self._settings.user_filter.format(username=escape_filter_chars(username))
        group = escape_filter_chars(self._settings.required_group)
        conn.search(self._settings.base_dn, f"(&{user}(memberOf={group}))", attributes=[])
        return len(conn.entries) > 0


class SessionCodec:
    """Signed cookie value <-> username, valid for `session_max_age_seconds`
    from sign-in. `now` is injectable so tests don't wait 12 hours."""

    def __init__(self, settings: AuthSettings, now):
        from itsdangerous import URLSafeSerializer

        self._serializer = URLSafeSerializer(settings.session_secret, salt="invoice-session")
        self._max_age = settings.session_max_age_seconds
        self._now = now

    def encode(self, user: str) -> str:
        return self._serializer.dumps({"user": user, "iat": self._now()})

    def decode(self, token: str | None) -> str | None:
        from itsdangerous import BadSignature

        if not token:
            return None
        try:
            payload = self._serializer.loads(token)
            user, issued_at = payload["user"], float(payload["iat"])
        except (BadSignature, KeyError, TypeError, ValueError):
            return None
        if self._now() - issued_at > self._max_age:
            return None
        return user


class LoginLimiter:
    """In-memory lockout: `max_failures` failed logins for a username within
    `window_seconds` locks it until the oldest of those failures ages out.
    Per process -- fine for the single-worker deployment this app requires."""

    def __init__(self, now, max_failures: int = 5, window_seconds: int = 15 * 60):
        self._now = now
        self._max = max_failures
        self._window = window_seconds
        self._failures: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def _recent(self, key: str) -> list[float]:
        cutoff = self._now() - self._window
        recent = [t for t in self._failures.get(key, []) if t > cutoff]
        if recent:
            self._failures[key] = recent
        else:
            self._failures.pop(key, None)
        return recent

    def is_locked(self, username: str) -> bool:
        with self._lock:
            return len(self._recent(username.lower())) >= self._max

    def record_failure(self, username: str) -> None:
        with self._lock:
            key = username.lower()
            self._failures[key] = self._recent(key) + [self._now()]

    def record_success(self, username: str) -> None:
        with self._lock:
            self._failures.pop(username.lower(), None)
