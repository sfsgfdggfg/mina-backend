# P2-09 Pilot Web Shell Setup

The pilot web shell is opt-in and does not replace bearer authentication for CLI or integration clients.

## Required configuration

Keep every value below outside the repository and source it through the controlled pilot environment.

```text
MINAI_WEB_SHELL_ENABLED=1
MINAI_WEB_SESSION_SECRET=<random secret, at least 32 characters>
MINAI_WEB_USERS_JSON={"ops@example.com":{"name":"Named Operator","password_hash":"<scrypt hash>","active":true}}
MINAI_PILOT_TLS_CERTFILE=<absolute external certificate path>
MINAI_PILOT_TLS_KEYFILE=<absolute external private-key path>
```

The web shell requires HTTPS even when `MINAI_PILOT_BIND_HOST` is loopback.

## Create password and session-secret material

Generate the password hash interactively so the plaintext password is not placed in shell history:

```text
python -m src.web_auth hash-password
```

Generate a separate session secret with a secure local tool, for example Python `secrets.token_urlsafe(48)`. Do not reuse a pilot bearer token as the session secret.

## Session behavior

- Passwords use the fixed supported scrypt parameters; arbitrary higher-cost hashes are rejected.
- Cookies are opaque, Secure, HttpOnly and SameSite=Strict.
- Absolute session TTL defaults to 480 minutes.
- Idle timeout defaults to 60 minutes.
- Process restart invalidates all browser sessions.
- Unsafe API calls made with browser session auth require `X-CSRF-Token`.

## Initial browser surface

After launch, open:

```text
https://<pilot-host>:<pilot-port>/app/login
```

The first pilot shell includes:

- MINA Jobs list and search
- bounded MINA job detail
- supplier and customer approval-required preview/approve/reject actions
- backend-authoritative reporting overview

Streamlit remains a development/debug interface. It is not the controlled pilot browser authority.
