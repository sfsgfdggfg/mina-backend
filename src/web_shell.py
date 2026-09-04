from __future__ import annotations

import html
import os
import secrets
from urllib.parse import parse_qs

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from src.core.pilot_access import pilot_mode_enabled
from src.core.web_session import (
    SESSION_COOKIE_NAME,
    authenticate_web_user,
    login_throttle,
    web_session_store,
    web_shell_enabled,
)

router = APIRouter()
_LOGIN_NONCE_COOKIE = "minai_login_nonce"


def _cookie_secure() -> bool:
    if pilot_mode_enabled():
        return True
    return (os.environ.get("MINAI_WEB_COOKIE_SECURE") or "").strip().lower() in {
        "1", "true", "yes", "on"
    }


def _secure_headers(response: Response) -> Response:
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "img-src 'self' data:; connect-src 'self'; base-uri 'none'; "
        "frame-ancestors 'none'; form-action 'self'"
    )
    return response


def _session_from_request(request: Request):
    return getattr(request.state, "web_session", None)


def _login_html(*, nonce: str, error: str | None = None) -> str:
    message = "" if not error else f'<p class="login-error">{html.escape(error)}</p>'
    return f'''<!doctype html>
<html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>MINAI Giriş</title><link rel="stylesheet" href="/app/assets/app.css"></head>
<body class="login-page"><main class="login-card">
<div class="brand-mark">M</div><h1>MINAI</h1><p class="muted">Freight Operations</p>{message}
<form method="post" action="/app/login" autocomplete="on">
<input type="hidden" name="login_nonce" value="{html.escape(nonce)}">
<label>E-posta<input type="email" name="email" autocomplete="username" required maxlength="254"></label>
<label>Şifre<input type="password" name="password" autocomplete="current-password" required maxlength="256"></label>
<button type="submit" class="primary">Giriş Yap</button></form>
</main></body></html>'''


def _shell_html(*, page: str, operator_name: str, csrf_token: str, job_id: str = "") -> str:
    operator = html.escape(operator_name)
    safe_job_id = html.escape(job_id)
    return f'''<!doctype html>
<html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="csrf-token" content="{html.escape(csrf_token)}"><title>MINAI</title>
<link rel="stylesheet" href="/app/assets/app.css"></head>
<body data-page="{html.escape(page)}" data-job-id="{safe_job_id}"><div class="shell">
<aside><a class="brand" href="/app/dashboard"><span class="brand-mark small">M</span><strong>MINAI</strong></a>
<nav><a href="/app/dashboard">Ana Ekran</a><a href="/app/work">İş Kuyruğu</a><a href="/app/jobs">MINA İşleri</a><a href="/app/reports">Raporlar</a></nav>
<div class="sidebar-footer"><span>{operator}</span><form method="post" action="/app/logout">
<input type="hidden" name="csrf_token" value="{html.escape(csrf_token)}"><button class="link-button" type="submit">Çıkış</button></form></div></aside>
<main><header><div><p class="eyebrow">Operasyon Merkezi</p><h1 id="page-title">MINAI</h1></div>
<div id="status-pill" class="status-pill">Bağlanıyor…</div></header><section id="app-content" class="content-card"></section></main>
</div><script src="/app/assets/app.js" defer></script></body></html>'''


async def _read_form(request: Request) -> dict[str, str]:
    raw = (await request.body()).decode("utf-8", errors="strict")
    parsed = parse_qs(raw, keep_blank_values=True, strict_parsing=False)
    return {key: values[-1] if values else "" for key, values in parsed.items()}


def _redirect_login() -> RedirectResponse:
    return RedirectResponse("/app/login", status_code=303)


@router.get("/app/login")
async def web_login_page(request: Request):
    if not web_shell_enabled():
        return Response(status_code=404)
    if _session_from_request(request) is not None:
        return RedirectResponse("/app/dashboard", status_code=303)
    nonce = secrets.token_urlsafe(24)
    response = _secure_headers(HTMLResponse(_login_html(nonce=nonce)))
    response.set_cookie(
        _LOGIN_NONCE_COOKIE, nonce, httponly=True, secure=_cookie_secure(),
        samesite="strict", max_age=300, path="/app",
    )
    return response


@router.post("/app/login")
async def web_login_submit(request: Request):
    if not web_shell_enabled():
        return Response(status_code=404)
    try:
        form = await _read_form(request)
    except (UnicodeDecodeError, ValueError):
        return _secure_headers(HTMLResponse("Geçersiz form.", status_code=400))
    cookie_nonce = request.cookies.get(_LOGIN_NONCE_COOKIE)
    form_nonce = form.get("login_nonce")
    if not cookie_nonce or not form_nonce or not secrets.compare_digest(cookie_nonce, form_nonce):
        return _secure_headers(HTMLResponse("Oturum doğrulaması başarısız.", status_code=403))
    client_key = request.client.host if request.client is not None else "unknown"
    if not login_throttle.allowed(client_key):
        nonce = secrets.token_urlsafe(24)
        response = _secure_headers(HTMLResponse(
            _login_html(nonce=nonce, error="Çok fazla başarısız giriş. Lütfen daha sonra tekrar deneyin."),
            status_code=429,
        ))
        response.set_cookie(
            _LOGIN_NONCE_COOKIE, nonce, httponly=True, secure=_cookie_secure(),
            samesite="strict", max_age=300, path="/app",
        )
        return response
    user = authenticate_web_user(form.get("email", ""), form.get("password", ""))
    if user is None:
        login_throttle.record_failure(client_key)
        nonce = secrets.token_urlsafe(24)
        response = _secure_headers(HTMLResponse(
            _login_html(nonce=nonce, error="E-posta veya şifre hatalı."), status_code=401
        ))
        response.set_cookie(
            _LOGIN_NONCE_COOKIE, nonce, httponly=True, secure=_cookie_secure(),
            samesite="strict", max_age=300, path="/app",
        )
        return response
    login_throttle.clear(client_key)
    session, cookie_value = web_session_store.create(user)
    response = RedirectResponse("/app/dashboard", status_code=303)
    response.set_cookie(
        SESSION_COOKIE_NAME, cookie_value, httponly=True, secure=_cookie_secure(),
        samesite="strict", max_age=int((session.expires_at - session.created_at).total_seconds()),
        path="/",
    )
    response.delete_cookie(_LOGIN_NONCE_COOKIE, path="/app")
    return _secure_headers(response)


@router.post("/app/logout")
async def web_logout(request: Request):
    session = _session_from_request(request)
    if session is None:
        return _redirect_login()
    form = await _read_form(request)
    if not web_session_store.verify_csrf(session, form.get("csrf_token")):
        return _secure_headers(HTMLResponse("CSRF doğrulaması başarısız.", status_code=403))
    web_session_store.invalidate(session.session_id)
    response = RedirectResponse("/app/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return _secure_headers(response)


def _shell_response(request: Request, *, page: str, job_id: str = ""):
    session = _session_from_request(request)
    if session is None:
        return _redirect_login()
    return _secure_headers(HTMLResponse(_shell_html(
        page=page, operator_name=session.operator_name,
        csrf_token=session.csrf_token, job_id=job_id,
    )))


@router.get("/app")
async def web_root(request: Request):
    return RedirectResponse(
        "/app/dashboard" if _session_from_request(request) is not None else "/app/login",
        status_code=303,
    )


@router.get("/app/dashboard")
async def web_dashboard(request: Request):
    return _shell_response(request, page="dashboard")


@router.get("/app/work")
async def web_work_queue(request: Request):
    return _shell_response(request, page="work")


@router.get("/app/jobs")
async def web_jobs(request: Request):
    return _shell_response(request, page="jobs")


@router.get("/app/jobs/{job_id}")
async def web_job_detail(request: Request, job_id: str):
    return _shell_response(request, page="job", job_id=job_id)


@router.get("/app/reports")
async def web_reports(request: Request):
    return _shell_response(request, page="reports")
