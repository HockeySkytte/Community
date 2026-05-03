from __future__ import annotations

from flask import Flask

from .auth_helpers import ensure_csrf_token, get_current_user
from .config import Config
from .routes.auth import auth_bp
from .routes.community import community_bp
from . import supabase_client as sb


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)

    @app.after_request
    def add_security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        return response

    @app.get("/health")
    def health() -> tuple[dict, int]:
        return {"status": "ok"}, 200

    @app.context_processor
    def inject_shell_state() -> dict:
        auth_user = get_current_user()
        unread_count = 0
        if auth_user:
            try:
                unread_count = sb.count_unread_notifications(str(auth_user.get("user_id") or ""))
            except Exception:
                unread_count = 0
        return {
            "auth_user": auth_user,
            "csrf_token": ensure_csrf_token(),
            "unread_notification_count": unread_count,
        }

    app.register_blueprint(auth_bp)
    app.register_blueprint(community_bp)
    return app
