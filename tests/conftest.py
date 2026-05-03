from __future__ import annotations

import pytest

from app import create_app


@pytest.fixture()
def app():
    app = create_app({"TESTING": True, "SECRET_KEY": "test-secret"})
    yield app


@pytest.fixture()
def client(app):
    return app.test_client()


def login_session(client, *, csrf_token: str = "csrf-test") -> None:
    from app.auth_helpers import _AUTH_SESSION_KEY, _CSRF_SESSION_KEY

    with client.session_transaction() as session:
        session[_AUTH_SESSION_KEY] = {
            "user_id": "user-1",
            "email": "member@example.com",
            "username": "member",
            "display_name": "Member One",
            "is_admin": False,
        }
        session[_CSRF_SESSION_KEY] = csrf_token
