from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Mapping

SESSION_COOKIE_NAME = "minai_session"
CSRF_HEADER_NAME = "X-CSRF-Token"
_PASSWORD_SCHEME = "scrypt"
_DEFAULT_TTL_MINUTES = 480
_DEFAULT_IDLE_MINUTES = 60
_MAX_SESSIONS = 500


class WebSessionConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class WebUser:
    email: str
    operator_name: str
    password_hash: str
    active: bool = True


@dataclass
class WebSession:
    session_id: str
    email: str
    operator_name: str
    csrf_token: str
    created_at: datetime
    expires_at: datetime
    last_seen_at: datetime


def _env_truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def web_shell_enabled(environ: Mapping[str, str] | None = None) -> bool:
    env = environ if environ is not None else os.environ
    return _env_truthy(env.get("MINAI_WEB_SHELL_ENABLED"))


def _b64_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64_decode(value: str) -> bytes:
    padding = "=" * ((4 - len(value) % 4) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    if len(password) < 12:
        raise ValueError("Web-shell passwords must contain at least 12 characters.")
    salt_bytes = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt_bytes,
        n=16384, r=8, p=1, dklen=32, maxmem=64 * 1024 * 1024,
    )
    return f"{_PASSWORD_SCHEME}$16384$8$1${_b64_encode(salt_bytes)}${_b64_encode(digest)}"


def password_hash_supported(encoded_hash: str) -> bool:
    try:
        scheme, raw_n, raw_r, raw_p, raw_salt, raw_digest = encoded_hash.split("$", 5)
        return (
            scheme == _PASSWORD_SCHEME
            and (int(raw_n), int(raw_r), int(raw_p)) == (16384, 8, 1)
            and len(_b64_decode(raw_salt)) == 16
            and len(_b64_decode(raw_digest)) == 32
        )
    except (ValueError, TypeError):
        return False


def verify_password(password: str, encoded_hash: str) -> bool:
    try:
        if not password_hash_supported(encoded_hash):
            return False
        _, _, _, _, raw_salt, raw_digest = encoded_hash.split("$", 5)
        digest = hashlib.scrypt(
            password.encode("utf-8"), salt=_b64_decode(raw_salt),
            n=16384, r=8, p=1, dklen=32, maxmem=64 * 1024 * 1024,
        )
        return hmac.compare_digest(digest, _b64_decode(raw_digest))
    except (ValueError, TypeError):
        return False


def _load_web_users(env: Mapping[str, str]) -> dict[str, WebUser]:
    raw = (env.get("MINAI_WEB_USERS_JSON") or "").strip()
    if not raw:
        raise WebSessionConfigurationError("MINAI_WEB_USERS_JSON is required when the web shell is enabled.")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise WebSessionConfigurationError("MINAI_WEB_USERS_JSON must be valid JSON.") from exc
    if not isinstance(payload, dict) or not payload:
        raise WebSessionConfigurationError("Web-shell users must be a non-empty JSON object.")
    users: dict[str, WebUser] = {}
    for raw_email, raw_user in payload.items():
        email = str(raw_email).strip().lower()
        if "@" not in email or len(email) > 254:
            raise WebSessionConfigurationError("Web-shell user keys must be valid email-like identities.")
        if not isinstance(raw_user, dict):
            raise WebSessionConfigurationError("Each web-shell user must be an object.")
        name = str(raw_user.get("name") or "").strip()
        password_hash = str(raw_user.get("password_hash") or "").strip()
        if len(name) < 2 or len(name) > 120:
            raise WebSessionConfigurationError("Web-shell user names must be explicit bounded identities.")
        if not password_hash_supported(password_hash):
            raise WebSessionConfigurationError(
                "Web-shell passwords must use the supported scrypt hash parameters, never plaintext."
            )
        users[email] = WebUser(
            email=email, operator_name=name, password_hash=password_hash,
            active=bool(raw_user.get("active", True)),
        )
    return users


def _session_secret(env: Mapping[str, str]) -> bytes:
    secret = (env.get("MINAI_WEB_SESSION_SECRET") or "").strip()
    if len(secret) < 32:
        raise WebSessionConfigurationError("MINAI_WEB_SESSION_SECRET must contain at least 32 characters.")
    return secret.encode("utf-8")


def _bounded_minutes(env: Mapping[str, str], key: str, default: int, maximum: int) -> int:
    raw = (env.get(key) or str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise WebSessionConfigurationError(f"{key} must be an integer.") from exc
    if value < 5 or value > maximum:
        raise WebSessionConfigurationError(f"{key} must be between 5 and {maximum} minutes.")
    return value


def validate_web_session_configuration(environ: Mapping[str, str] | None = None) -> None:
    env = environ if environ is not None else os.environ
    if not web_shell_enabled(env):
        return
    _load_web_users(env)
    _session_secret(env)
    ttl = _bounded_minutes(env, "MINAI_WEB_SESSION_TTL_MINUTES", _DEFAULT_TTL_MINUTES, 1440)
    idle = _bounded_minutes(env, "MINAI_WEB_SESSION_IDLE_MINUTES", _DEFAULT_IDLE_MINUTES, 720)
    if idle > ttl:
        raise WebSessionConfigurationError("Web-shell idle timeout cannot exceed absolute session TTL.")


_DUMMY_PASSWORD_HASH = hash_password(
    "minai-dummy-password", salt=b"minai-web-dummy!"
)


def authenticate_web_user(
    email: str, password: str, *, environ: Mapping[str, str] | None = None,
) -> WebUser | None:
    env = environ if environ is not None else os.environ
    users = _load_web_users(env)
    normalized = (email or "").strip().lower()
    user = users.get(normalized)
    candidate_hash = user.password_hash if user is not None else _DUMMY_PASSWORD_HASH
    valid = verify_password(password or "", candidate_hash)
    return user if user is not None and user.active and valid else None


class InMemoryWebSessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, WebSession] = {}
        self._lock = threading.RLock()

    def _sign(self, session_id: str, env: Mapping[str, str]) -> str:
        signature = hmac.new(_session_secret(env), session_id.encode("ascii"), hashlib.sha256).digest()
        return _b64_encode(signature)

    def create(
        self, user: WebUser, *, now: datetime | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> tuple[WebSession, str]:
        env = environ if environ is not None else os.environ
        validate_web_session_configuration(env)
        current = now or datetime.now(timezone.utc)
        ttl = _bounded_minutes(env, "MINAI_WEB_SESSION_TTL_MINUTES", _DEFAULT_TTL_MINUTES, 1440)
        session = WebSession(
            session_id=secrets.token_urlsafe(32), email=user.email,
            operator_name=user.operator_name, csrf_token=secrets.token_urlsafe(32),
            created_at=current, expires_at=current + timedelta(minutes=ttl), last_seen_at=current,
        )
        with self._lock:
            self._prune_locked(current, env)
            if len(self._sessions) >= _MAX_SESSIONS:
                oldest = min(self._sessions.values(), key=lambda item: item.last_seen_at)
                self._sessions.pop(oldest.session_id, None)
            self._sessions[session.session_id] = session
        cookie_value = f"{session.session_id}.{self._sign(session.session_id, env)}"
        return session, cookie_value

    def resolve(
        self, cookie_value: str | None, *, now: datetime | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> WebSession | None:
        if not cookie_value:
            return None
        env = environ if environ is not None else os.environ
        validate_web_session_configuration(env)
        session_id, separator, signature = cookie_value.partition(".")
        if separator != "." or not session_id or not signature:
            return None
        expected = self._sign(session_id, env)
        if not hmac.compare_digest(signature, expected):
            return None
        current = now or datetime.now(timezone.utc)
        users = _load_web_users(env)
        idle_minutes = _bounded_minutes(
            env, "MINAI_WEB_SESSION_IDLE_MINUTES", _DEFAULT_IDLE_MINUTES, 720
        )
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            user = users.get(session.email)
            if user is None or not user.active:
                self._sessions.pop(session_id, None)
                return None
            if current >= session.expires_at or current - session.last_seen_at >= timedelta(minutes=idle_minutes):
                self._sessions.pop(session_id, None)
                return None
            session.last_seen_at = current
            return session

    def invalidate(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)

    def verify_csrf(self, session: WebSession, token: str | None) -> bool:
        return bool(token) and hmac.compare_digest(session.csrf_token, str(token))

    def _prune_locked(self, current: datetime, env: Mapping[str, str]) -> None:
        idle_minutes = _bounded_minutes(
            env, "MINAI_WEB_SESSION_IDLE_MINUTES", _DEFAULT_IDLE_MINUTES, 720
        )
        expired = [
            session_id
            for session_id, session in self._sessions.items()
            if current >= session.expires_at
            or current - session.last_seen_at >= timedelta(minutes=idle_minutes)
        ]
        for session_id in expired:
            self._sessions.pop(session_id, None)


web_session_store = InMemoryWebSessionStore()


class InMemoryLoginThrottle:
    def __init__(self, *, max_failures: int = 10, window_minutes: int = 10) -> None:
        self.max_failures = max_failures
        self.window = timedelta(minutes=window_minutes)
        self._failures: dict[str, list[datetime]] = {}
        self._lock = threading.RLock()

    def allowed(self, client_key: str, *, now: datetime | None = None) -> bool:
        current = now or datetime.now(timezone.utc)
        key = (client_key or "unknown").strip()[:160]
        with self._lock:
            recent = [item for item in self._failures.get(key, []) if current - item < self.window]
            self._failures[key] = recent
            return len(recent) < self.max_failures

    def record_failure(self, client_key: str, *, now: datetime | None = None) -> None:
        current = now or datetime.now(timezone.utc)
        key = (client_key or "unknown").strip()[:160]
        with self._lock:
            self._failures.setdefault(key, []).append(current)

    def clear(self, client_key: str) -> None:
        key = (client_key or "unknown").strip()[:160]
        with self._lock:
            self._failures.pop(key, None)


login_throttle = InMemoryLoginThrottle()
