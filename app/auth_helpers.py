from __future__ import annotations

from functools import wraps
from secrets import token_urlsafe

from flask import abort, jsonify, redirect, request, session, url_for


_AUTH_SESSION_KEY = "community_auth_user"
_CSRF_SESSION_KEY = "community_csrf_token"


def get_current_user() -> dict | None:
    user = session.get(_AUTH_SESSION_KEY)
    return user if isinstance(user, dict) else None


def login_user(user: dict) -> None:
    session[_AUTH_SESSION_KEY] = user


def logout_user() -> None:
    session.pop(_AUTH_SESSION_KEY, None)


def ensure_csrf_token() -> str:
    token = session.get(_CSRF_SESSION_KEY)
    if not token:
        token = token_urlsafe(24)
        session[_CSRF_SESSION_KEY] = token
    return str(token)


def validate_csrf_token(token: str | None) -> bool:
    if not token:
        return False
    return str(token) == str(session.get(_CSRF_SESSION_KEY) or "")


def require_csrf() -> None:
    token = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
    if not validate_csrf_token(token):
        abort(400, "Invalid CSRF token")


def login_required(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if get_current_user():
            return view_func(*args, **kwargs)
        if request.path.startswith("/api/") or request.is_json:
            return jsonify({"error": "authentication_required"}), 401
        next_url = request.full_path if request.query_string else request.path
        return redirect(url_for("auth.login", next=next_url))

    return wrapped
