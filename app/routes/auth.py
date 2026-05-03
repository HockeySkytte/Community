from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for

from ..auth_helpers import ensure_csrf_token, login_user, logout_user, require_csrf
from .. import supabase_client as sb


auth_bp = Blueprint("auth", __name__)


def _build_session_user(account: dict) -> dict:
    return {
        "user_id": str(account.get("auth_user_id") or ""),
        "email": str(account.get("email") or ""),
        "username": str(account.get("username") or ""),
        "display_name": str(account.get("display_name") or account.get("username") or account.get("email") or "Account"),
        "profile_image_url": str(account.get("profile_image_url") or account.get("avatar_url") or ""),
        "account_tier": str(account.get("account_tier") or account.get("plan") or "community"),
        "has_pro_access": bool(account.get("has_pro_access") or False),
        "is_admin": bool(account.get("is_admin") or False),
    }


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    next_url = request.values.get("next") or "/home"
    if request.method == "GET":
        return render_template("login.html", next_url=next_url, auth_enabled=sb.auth_is_configured())

    require_csrf()
    email = str(request.form.get("email") or "").strip().lower()
    password = str(request.form.get("password") or "")
    if not email or not password:
        flash("Email and password are required.", "error")
        return render_template("login.html", next_url=next_url, auth_enabled=sb.auth_is_configured()), 400

    try:
        response = sb.auth_sign_in_with_password(email, password)
    except Exception as exc:
        flash(f"Login failed: {exc}", "error")
        return render_template("login.html", next_url=next_url, auth_enabled=sb.auth_is_configured()), 400

    auth_user = response.get("user") or (response.get("session") or {}).get("user") or {}
    auth_user_id = str(auth_user.get("id") or "").strip()
    if not auth_user_id:
        flash("Login failed: Supabase did not return a user record.", "error")
        return render_template("login.html", next_url=next_url, auth_enabled=sb.auth_is_configured()), 400

    account = sb.get_user_account(auth_user_id)
    if not account:
        account = sb.sync_user_account_from_auth_user(auth_user)
    account = sb.enforce_account_tier_rules(account)
    if not account:
        flash("Your account exists in auth, but user_accounts is not available yet.", "error")
        return render_template("login.html", next_url=next_url, auth_enabled=sb.auth_is_configured()), 400

    login_user(_build_session_user(account))
    ensure_csrf_token()
    return redirect(next_url)


@auth_bp.route("/signup", methods=["GET", "POST"])
def signup():
    next_url = request.values.get("next") or "/home"
    if request.method == "GET":
        return render_template("signup.html", next_url=next_url, auth_enabled=sb.auth_is_configured())

    require_csrf()
    email = str(request.form.get("email") or "").strip().lower()
    password = str(request.form.get("password") or "")
    confirm_password = str(request.form.get("confirm_password") or "")
    username = str(request.form.get("username") or "").strip().lower()
    display_name = " ".join(str(request.form.get("display_name") or "").split()).strip()

    if not email or not password or not username or not display_name:
        flash("Email, display name, username, and password are required.", "error")
        return render_template("signup.html", next_url=next_url, auth_enabled=sb.auth_is_configured()), 400
    if password != confirm_password:
        flash("Passwords do not match.", "error")
        return render_template("signup.html", next_url=next_url, auth_enabled=sb.auth_is_configured()), 400
    if len(password) < 8:
        flash("Password must be at least 8 characters.", "error")
        return render_template("signup.html", next_url=next_url, auth_enabled=sb.auth_is_configured()), 400

    existing = sb.find_user_account_by_username(username)
    if existing:
        flash("That username is already taken.", "error")
        return render_template("signup.html", next_url=next_url, auth_enabled=sb.auth_is_configured()), 400

    try:
        response = sb.auth_sign_up_with_password(email, password, username=username, display_name=display_name)
    except Exception as exc:
        flash(f"Sign up failed: {exc}", "error")
        return render_template("signup.html", next_url=next_url, auth_enabled=sb.auth_is_configured()), 400

    auth_user = response.get("user") or (response.get("session") or {}).get("user") or {}
    auth_user_id = str(auth_user.get("id") or "").strip()
    if not auth_user_id:
        flash("Account created, but your email may require verification before first login.", "info")
        return redirect(url_for("auth.login", next=next_url))

    account = sb.sync_user_account_from_auth_user(auth_user)
    account = sb.initialize_user_tier(
        auth_user_id=auth_user_id,
        email=email,
        username=username,
        display_name=display_name,
        is_admin=False,
    ) or account
    account = sb.enforce_account_tier_rules(account)
    if not account:
        flash("Account was created, but profile initialization failed. Please sign in.", "info")
        return redirect(url_for("auth.login", next=next_url))

    login_user(_build_session_user(account))
    ensure_csrf_token()
    flash("Account created. Welcome to Hockey Community.", "success")
    return redirect(next_url)


@auth_bp.post("/logout")
def logout():
    require_csrf()
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))
