from __future__ import annotations

from app.routes import auth, community
from tests.conftest import login_session


def test_root_redirects_to_login_when_logged_out(client):
    response = client.get("/")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_home_renders_hubs_and_posts(monkeypatch, client):
    monkeypatch.setattr(community.sb, "count_unread_notifications", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(
        community.sb,
        "list_hubs",
        lambda: [
            {"id": "hub-1", "slug": "nhl", "name": "NHL", "description": "NHL hub"},
            {"id": "hub-2", "slug": "pwhl", "name": "PWHL", "description": "PWHL hub"},
        ],
    )
    monkeypatch.setattr(
        community.sb,
        "list_posts",
        lambda **_kwargs: [
            {
                "id": "post-1",
                "hub_id": "hub-1",
                "hub": {"id": "hub-1", "slug": "nhl", "name": "NHL"},
                "author_display_name": "Member One",
                "title": "Opening night thread",
                "body": "The first implementation slice is live.",
                "score": 4,
                "comment_count": 2,
                "media": [],
                "video_url": None,
            }
        ],
    )
    login_session(client)

    response = client.get("/home")
    assert response.status_code == 200
    assert b"Opening night thread" in response.data
    assert b"NHL" in response.data


def test_login_post_stores_session(monkeypatch, client):
    monkeypatch.setattr(auth.sb, "auth_is_configured", lambda: True)
    monkeypatch.setattr(auth.sb, "auth_sign_in_with_password", lambda *_args, **_kwargs: {"user": {"id": "auth-1", "email": "member@example.com"}})
    monkeypatch.setattr(auth.sb, "get_user_account", lambda *_args, **_kwargs: {"auth_user_id": "auth-1", "email": "member@example.com", "username": "member", "display_name": "Member One", "is_admin": False})

    response = client.post(
        "/login",
        data={
            "csrf_token": client.get("/login").text.split('meta name="csrf-token" content="')[1].split('"', 1)[0],
            "email": "member@example.com",
            "password": "password123",
            "next": "/home",
        },
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/home")


def test_create_post_requires_csrf(monkeypatch, client):
    monkeypatch.setattr(community.sb, "count_unread_notifications", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(community.sb, "get_hub_by_slug", lambda _slug: {"id": "hub-1", "slug": "nhl", "name": "NHL"})
    monkeypatch.setattr(community.sb, "create_post", lambda *_args, **_kwargs: {"id": "post-1"})
    login_session(client)

    response = client.post("/hubs/nhl/posts", data={"title": "Test post", "body": "Body"})
    assert response.status_code == 400


def test_post_detail_renders_thread(monkeypatch, client):
    monkeypatch.setattr(community.sb, "count_unread_notifications", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(
        community.sb,
        "get_post",
        lambda _post_id: {
            "id": "post-1",
            "hub_id": "hub-1",
            "hub": {"id": "hub-1", "slug": "nhl", "name": "NHL"},
            "author_display_name": "Member One",
            "title": "Game thread",
            "body": "Line one is flying.",
            "score": 6,
            "comment_count": 1,
            "media": [],
            "video_url": None,
        },
    )
    monkeypatch.setattr(
        community.sb,
        "list_comments",
        lambda _post_id: [
            {
                "id": "comment-1",
                "post_id": "post-1",
                "parent_comment_id": None,
                "author_display_name": "Reply Guy",
                "body": "Power play looked sharp.",
                "score": 2,
                "depth": 0,
                "created_at": "2026-04-30T10:00:00+00:00",
            }
        ],
    )
    login_session(client)

    response = client.get("/posts/post-1")
    assert response.status_code == 200
    assert b"Game thread" in response.data
    assert b"Power play looked sharp." in response.data


def test_reaction_api_returns_updated_counts(monkeypatch, client):
    monkeypatch.setattr(community.sb, "count_unread_notifications", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(
        community.sb,
        "set_reaction",
        lambda **_kwargs: {"target_id": "post-1", "target_type": "post", "score": 3, "like_count": 4, "dislike_count": 1},
    )
    login_session(client)

    response = client.post(
        "/api/reactions",
        json={"target_id": "post-1", "target_type": "post", "vote_type": "like"},
        headers={"X-CSRF-Token": "csrf-test"},
    )
    assert response.status_code == 200
    assert response.get_json()["score"] == 3