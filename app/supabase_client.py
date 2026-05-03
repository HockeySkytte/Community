from __future__ import annotations

import functools
import os
import posixpath
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote
from uuid import uuid4

from flask import current_app
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

try:
    from supabase import Client, create_client
except Exception:  # pragma: no cover - dependency presence is environment-specific
    Client = Any  # type: ignore[misc,assignment]
    create_client = None


_USERNAME_PATTERN = re.compile(r"[^a-z0-9._-]+")
_UUID_PATTERN = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$")


def _config_value(name: str) -> str:
    env_value = os.environ.get(name)
    if env_value:
        return env_value
    try:
        value = current_app.config.get(name)
    except RuntimeError:
        value = None
    return str(value or "")


def _require_create_client() -> None:
    if create_client is None:
        raise RuntimeError("Supabase client dependency is not installed. Install requirements.txt first.")


@functools.lru_cache(maxsize=8)
def _cached_client(url: str, key: str):
    _require_create_client()
    return create_client(url, key)


def get_client() -> Client:
    url = _config_value("SUPABASE_URL")
    key = _config_value("SUPABASE_SERVICE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be configured.")
    return _cached_client(url, key)


def create_auth_client(*, admin: bool = False) -> Client:
    url = _config_value("SUPABASE_URL")
    key = _config_value("SUPABASE_SERVICE_KEY") if admin else (_config_value("SUPABASE_ANON_KEY") or _config_value("SUPABASE_SERVICE_KEY"))
    if not url or not key:
        raise RuntimeError("Supabase auth credentials are not configured.")
    return _cached_client(url, key)


def auth_is_configured() -> bool:
    return bool(_config_value("SUPABASE_URL") and (_config_value("SUPABASE_ANON_KEY") or _config_value("SUPABASE_SERVICE_KEY")))


def _to_plain(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [_to_plain(item) for item in value]
    if isinstance(value, tuple):
        return [_to_plain(item) for item in value]
    if isinstance(value, dict):
        return {key: _to_plain(item) for key, item in value.items()}

    data = getattr(value, "data", None)
    user = getattr(value, "user", None)
    session = getattr(value, "session", None)
    if data is not None or user is not None or session is not None:
        out: dict[str, Any] = {}
        if data is not None:
            out["data"] = _to_plain(data)
        if user is not None:
            out["user"] = _to_plain(user)
        if session is not None:
            out["session"] = _to_plain(session)
        return out

    try:
        raw = vars(value)
    except Exception:
        raw = None
    if isinstance(raw, dict):
        return {key: _to_plain(item) for key, item in raw.items() if not str(key).startswith("_")}
    return value


def _rows_from_response(response: Any) -> list[dict]:
    rows = _to_plain(getattr(response, "data", None)) or []
    return rows if isinstance(rows, list) else []


def _first_row(response: Any) -> dict | None:
    rows = _rows_from_response(response)
    return rows[0] if rows else None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_username(value: Any) -> str:
    raw = str(value or "").strip().lower()
    normalized = _USERNAME_PATTERN.sub("", raw.replace(" ", "-"))
    return normalized[:32]


def _normalize_uuid(value: Any) -> str | None:
    text = str(value or "").strip()
    return text if _UUID_PATTERN.match(text) else None


def _is_missing_table_error(exc: Exception, table: str) -> bool:
    raw = str(_to_plain(exc) or exc or "").lower()
    table_name = table.lower()
    return table_name in raw and ("could not find the table" in raw or "pgrst205" in raw)


def _missing_column_name(exc: Exception, table: str) -> str | None:
    raw = str(_to_plain(exc) or exc or "")
    lowered = raw.lower()
    if table.lower() not in lowered:
        return None
    match = re.search(r'column\s+"([a-zA-Z0-9_]+)"\s+of\s+relation\s+"%s"\s+does\s+not\s+exist' % re.escape(table), raw, flags=re.IGNORECASE)
    if match:
        return str(match.group(1) or "").strip()
    match = re.search(r"could\s+not\s+find\s+the\s+'([a-zA-Z0-9_]+)'\s+column\s+of\s+'%s'" % re.escape(table), raw, flags=re.IGNORECASE)
    if match:
        return str(match.group(1) or "").strip()
    return None


def auth_sign_in_with_password(email: str, password: str) -> dict:
    client = create_auth_client(admin=False)
    response = client.auth.sign_in_with_password({"email": email, "password": password})
    return _to_plain(response) or {}


def auth_sign_up_with_password(email: str, password: str, *, username: str, display_name: str) -> dict:
    client = create_auth_client(admin=False)
    payload = {
        "email": email,
        "password": password,
        "options": {
            "data": {
                "username": _normalize_username(username) or username,
                "display_name": str(display_name or "").strip(),
            }
        },
    }
    response = client.auth.sign_up(payload)
    return _to_plain(response) or {}


def get_user_account(auth_user_id: str) -> dict | None:
    if not auth_user_id:
        return None
    client = get_client()
    try:
        response = client.table("user_accounts").select("*").eq("auth_user_id", auth_user_id).limit(1).execute()
    except Exception as exc:
        if _is_missing_table_error(exc, "user_accounts"):
            return None
        raise
    return _first_row(response)


def find_user_account_by_username(username: str) -> dict | None:
    normalized = _normalize_username(username)
    if not normalized:
        return None
    client = get_client()
    response = client.table("user_accounts").select("*").eq("username", normalized).limit(1).execute()
    return _first_row(response)


def upsert_user_account(record: dict) -> dict | None:
    auth_user_id = str((record or {}).get("auth_user_id") or "").strip()
    if not auth_user_id:
        raise ValueError("auth_user_id is required for user account upsert")
    payload = dict(record or {})
    client = get_client()
    for _ in range(10):
        try:
            client.table("user_accounts").upsert(payload, on_conflict="auth_user_id").execute()
            break
        except Exception as exc:
            if _is_missing_table_error(exc, "user_accounts"):
                return None
            missing_col = _missing_column_name(exc, "user_accounts")
            if missing_col and missing_col in payload:
                payload.pop(missing_col, None)
                continue
            raise
    return get_user_account(auth_user_id)


def sync_user_account_from_auth_user(user: dict) -> dict | None:
    auth_user_id = str(user.get("id") or "").strip()
    email = str(user.get("email") or "").strip().lower()
    user_meta = user.get("user_metadata") or {}
    app_meta = user.get("app_metadata") or {}
    raw_username = user_meta.get("username") or email.split("@", 1)[0]
    username = _normalize_username(raw_username)
    payload = {
        "auth_user_id": auth_user_id,
        "email": email,
        "username": username or None,
        "display_name": str(user_meta.get("display_name") or user_meta.get("name") or username or email or "Account").strip(),
        "is_admin": bool(app_meta.get("is_admin") or user_meta.get("is_admin") or False),
        "updated_at": _now_iso(),
    }
    return upsert_user_account(payload)


def _parse_iso_datetime(raw: Any) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _canonical_account_tier(raw_tier: Any, *, is_admin: bool = False) -> str:
    if is_admin:
        return "admin"
    value = str(raw_tier or "").strip().lower().replace(" ", "_").replace("-", "_")
    aliases = {
        "admin": "admin",
        "administrator": "admin",
        "pro": "pro",
        "free": "free",
        "trial": "trial",
        "trialing": "trial",
        "community": "community",
        "member": "community",
    }
    return aliases.get(value, "community")


def initialize_user_tier(*, auth_user_id: str, email: str, username: str, display_name: str, is_admin: bool) -> dict | None:
    initial_tier = "admin" if is_admin else "trial"
    trial_ends_at = (datetime.now(timezone.utc) + timedelta(days=14)).isoformat() if initial_tier == "trial" else None
    payload = {
        "auth_user_id": auth_user_id,
        "email": email,
        "username": username,
        "display_name": display_name,
        "is_admin": is_admin,
        "account_tier": initial_tier,
        "plan": initial_tier,
        "has_pro_access": True,
        "trial_ends_at": trial_ends_at,
        "updated_at": _now_iso(),
    }
    return upsert_user_account(payload)


def enforce_account_tier_rules(account: dict | None) -> dict | None:
    if not account:
        return None
    auth_user_id = str(account.get("auth_user_id") or "")
    if not auth_user_id:
        return account
    if not _normalize_uuid(auth_user_id):
        return account

    is_admin = bool(account.get("is_admin") or False)
    incoming_tier = account.get("account_tier") or account.get("plan") or account.get("user_tier")
    tier = _canonical_account_tier(incoming_tier, is_admin=is_admin)

    trial_ends = _parse_iso_datetime(account.get("trial_ends_at") or account.get("trial_end_at") or account.get("trial_expires_at"))
    now_utc = datetime.now(timezone.utc)
    if tier == "trial" and trial_ends and trial_ends <= now_utc:
        tier = "community"

    has_pro_access = bool(account.get("has_pro_access") or False)
    if tier in {"admin", "pro", "free", "trial"}:
        has_pro_access = True
    elif tier == "community":
        has_pro_access = False

    current_tier = _canonical_account_tier(account.get("account_tier") or account.get("plan") or account.get("user_tier"), is_admin=is_admin)
    if current_tier == tier and bool(account.get("has_pro_access") or False) == has_pro_access:
        return account

    email = str(account.get("email") or "").strip().lower()
    username = str(account.get("username") or "").strip()
    display_name = str(account.get("display_name") or username or email or "").strip()
    if not email:
        return account

    updated = upsert_user_account(
        {
            "auth_user_id": auth_user_id,
            "email": email,
            "username": username or None,
            "display_name": display_name or None,
            "is_admin": is_admin,
            "account_tier": tier,
            "plan": tier,
            "has_pro_access": has_pro_access,
            "updated_at": _now_iso(),
        }
    )
    return updated or account


def list_user_accounts(*, limit: int = 250, search: str | None = None) -> list[dict]:
    response = get_client().table("user_accounts").select("*").order("updated_at", desc=True).limit(limit).execute()
    rows = _rows_from_response(response)
    query = str(search or "").strip().lower()
    if not query:
        return rows
    filtered: list[dict] = []
    for row in rows:
        haystack = " ".join(
            [
                str(row.get("email") or ""),
                str(row.get("username") or ""),
                str(row.get("display_name") or ""),
                str(row.get("auth_user_id") or ""),
            ]
        ).lower()
        if query in haystack:
            filtered.append(row)
    return filtered


def set_community_ban(*, target_auth_user_id: str, banned_until: str | None, reason: str | None, banned_by_auth_user_id: str | None = None) -> dict | None:
    account = get_user_account(target_auth_user_id)
    if not account:
        raise ValueError("User account not found.")

    payload = {
        "auth_user_id": str(account.get("auth_user_id") or ""),
        "email": str(account.get("email") or "").strip().lower(),
        "username": str(account.get("username") or "") or None,
        "display_name": str(account.get("display_name") or "") or None,
        "is_admin": bool(account.get("is_admin") or False),
        "community_banned_until": banned_until,
        "community_ban_reason": str(reason or "").strip() or None,
        "community_banned_by": str(banned_by_auth_user_id or "").strip() or None,
        "updated_at": _now_iso(),
    }
    updated = upsert_user_account(payload)
    return updated or account


def get_active_community_ban(auth_user_id: str) -> dict | None:
    account = get_user_account(auth_user_id)
    if not account:
        return None
    banned_until_raw = account.get("community_banned_until")
    banned_until = _parse_iso_datetime(banned_until_raw)
    if not banned_until:
        return None

    now_utc = datetime.now(timezone.utc)
    if banned_until <= now_utc:
        set_community_ban(target_auth_user_id=auth_user_id, banned_until=None, reason=None, banned_by_auth_user_id=None)
        return None

    return {
        "until": banned_until,
        "reason": str(account.get("community_ban_reason") or "").strip(),
    }


def list_hubs() -> list[dict]:
    response = get_client().table("community_hubs").select("*").eq("is_active", True).order("sort_order").execute()
    return _rows_from_response(response)


def get_hub_by_slug(slug: str) -> dict | None:
    if not slug:
        return None
    response = get_client().table("community_hubs").select("*").eq("slug", slug).limit(1).execute()
    return _first_row(response)


def _fetch_hub_map(hub_ids: list[str]) -> dict[str, dict]:
    if not hub_ids:
        return {}
    response = get_client().table("community_hubs").select("*").in_("id", hub_ids).execute()
    return {str(row.get("id")): row for row in _rows_from_response(response)}


def _fetch_post_media_map(post_ids: list[str]) -> dict[str, list[dict]]:
    if not post_ids:
        return {}
    response = get_client().table("community_post_media").select("*").in_("post_id", post_ids).order("sort_order").execute()
    grouped: dict[str, list[dict]] = {post_id: [] for post_id in post_ids}
    for row in _rows_from_response(response):
        grouped.setdefault(str(row.get("post_id")), []).append(row)
    return grouped


def _attach_posts(rows: list[dict]) -> list[dict]:
    if not rows:
        return []
    hub_map = _fetch_hub_map([str(row.get("hub_id")) for row in rows if row.get("hub_id")])
    media_map = _fetch_post_media_map([str(row.get("id")) for row in rows if row.get("id")])
    attached: list[dict] = []
    for row in rows:
        item = dict(row)
        item["hub"] = hub_map.get(str(item.get("hub_id") or ""))
        item["media"] = media_map.get(str(item.get("id") or ""), [])
        attached.append(item)
    return attached


def list_posts(*, hub_slug: str | None = None, limit: int = 20, sort: str = "new", search: str | None = None, author_user_id: str | None = None) -> list[dict]:
    client = get_client()
    hub = get_hub_by_slug(hub_slug) if hub_slug else None
    query = client.table("community_posts").select("*").eq("status", "active")
    if hub:
        query = query.eq("hub_id", hub["id"])
    if author_user_id:
        query = query.eq("author_auth_user_id", author_user_id)
    if sort == "top":
        query = query.order("score", desc=True).order("comment_count", desc=True).order("created_at", desc=True)
    else:
        query = query.order("created_at", desc=True)
    response = query.limit(limit * 3 if search else limit).execute()
    rows = _attach_posts(_rows_from_response(response))
    if search:
        needle = search.lower()
        rows = [
            r for r in rows
            if needle in (r.get("title") or "").lower()
            or needle in (r.get("author_display_name") or "").lower()
            or needle in (r.get("created_at") or "")[:10]
        ][:limit]
    return rows


def list_recent_comments(*, limit: int = 12) -> list[dict]:
    response = (
        get_client()
        .table("community_comments")
        .select("*")
        .neq("status", "deleted")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return _rows_from_response(response)


def get_post(post_id: str) -> dict | None:
    if not post_id:
        return None
    response = get_client().table("community_posts").select("*").eq("id", post_id).limit(1).execute()
    row = _first_row(response)
    if not row:
        return None
    attached = _attach_posts([row])
    return attached[0] if attached else None


def create_post(post_payload: dict, media_rows: list[dict] | None = None) -> dict | None:
    payload = dict(post_payload)
    payload.setdefault("id", str(uuid4()))
    payload.setdefault("status", "active")
    payload.setdefault("created_at", _now_iso())
    payload.setdefault("updated_at", payload["created_at"])
    payload.setdefault("last_activity_at", payload["created_at"])
    payload.setdefault("comment_count", 0)
    payload.setdefault("like_count", 0)
    payload.setdefault("dislike_count", 0)
    payload.setdefault("score", 0)
    if not payload.get("preview_image_url") and media_rows:
        first_image = next((row for row in media_rows if row.get("media_kind") == "image"), None)
        if first_image:
            payload["preview_image_url"] = first_image.get("public_url")
    get_client().table("community_posts").insert(payload).execute()
    if media_rows:
        rows_to_insert = []
        for index, media in enumerate(media_rows):
            item = dict(media)
            item.setdefault("id", str(uuid4()))
            item["post_id"] = payload["id"]
            item["sort_order"] = index
            item.setdefault("created_at", payload["created_at"])
            rows_to_insert.append(item)
        get_client().table("community_post_media").insert(rows_to_insert).execute()
    return get_post(payload["id"])


def update_post(post_id: str, updates: dict) -> dict | None:
    if not post_id:
        return None
    payload = dict(updates or {})
    payload["updated_at"] = _now_iso()
    get_client().table("community_posts").update(payload).eq("id", post_id).execute()
    return get_post(post_id)


def soft_delete_post(post_id: str) -> None:
    if not post_id:
        return
    payload = {"status": "deleted", "updated_at": _now_iso()}
    get_client().table("community_posts").update(payload).eq("id", post_id).execute()


def add_post_media(post_id: str, media_rows: list[dict]) -> None:
    if not post_id or not media_rows:
        return
    existing = (
        get_client()
        .table("community_post_media")
        .select("id")
        .eq("post_id", post_id)
        .execute()
    )
    start_index = len(_rows_from_response(existing))
    rows_to_insert = []
    timestamp = _now_iso()
    for offset, media in enumerate(media_rows):
        item = dict(media)
        item.setdefault("id", str(uuid4()))
        item["post_id"] = post_id
        item["sort_order"] = start_index + offset
        item.setdefault("created_at", timestamp)
        rows_to_insert.append(item)
    get_client().table("community_post_media").insert(rows_to_insert).execute()


def track_post_event(post_id: str, *, event_type: str, auth_user_id: str | None = None) -> None:
    normalized_post_id = _normalize_uuid(post_id)
    if event_type not in {"view", "share"} or not normalized_post_id:
        return
    payload = {
        "id": str(uuid4()),
        "post_id": normalized_post_id,
        "event_type": event_type,
        "actor_auth_user_id": _normalize_uuid(auth_user_id),
        "created_at": _now_iso(),
    }
    try:
        get_client().table("community_post_events").insert(payload).execute()
    except Exception as exc:
        if _is_missing_table_error(exc, "community_post_events"):
            return
        raise


def list_post_events(post_id: str, *, event_type: str, start_at: datetime | None = None, limit: int = 8000) -> list[dict]:
    if event_type not in {"view", "share"} or not post_id:
        return []
    try:
        query = (
            get_client()
            .table("community_post_events")
            .select("*")
            .eq("post_id", post_id)
            .eq("event_type", event_type)
            .order("created_at")
            .limit(limit)
        )
        if start_at:
            query = query.gte("created_at", start_at.isoformat())
        response = query.execute()
    except Exception as exc:
        if _is_missing_table_error(exc, "community_post_events"):
            return []
        raise
    return _rows_from_response(response)


def _bump_post_counts(post_id: str, *, comments: int = 0, likes: int = 0, dislikes: int = 0, touch: bool = False) -> dict | None:
    post = get_post(post_id)
    if not post:
        return None
    like_count = max(0, int(post.get("like_count") or 0) + likes)
    dislike_count = max(0, int(post.get("dislike_count") or 0) + dislikes)
    comment_count = max(0, int(post.get("comment_count") or 0) + comments)
    payload = {
        "like_count": like_count,
        "dislike_count": dislike_count,
        "comment_count": comment_count,
        "score": like_count - dislike_count,
        "updated_at": _now_iso(),
    }
    if touch:
        payload["last_activity_at"] = _now_iso()
    get_client().table("community_posts").update(payload).eq("id", post_id).execute()
    return payload


def decrement_post_comment_count(post_id: str) -> dict | None:
    return _bump_post_counts(post_id, comments=-1, touch=True)


def _bump_comment_counts(comment_id: str, *, likes: int = 0, dislikes: int = 0) -> dict | None:
    comment = get_comment(comment_id)
    if not comment:
        return None
    like_count = max(0, int(comment.get("like_count") or 0) + likes)
    dislike_count = max(0, int(comment.get("dislike_count") or 0) + dislikes)
    payload = {
        "like_count": like_count,
        "dislike_count": dislike_count,
        "score": like_count - dislike_count,
        "updated_at": _now_iso(),
    }
    get_client().table("community_comments").update(payload).eq("id", comment_id).execute()
    return payload


def list_comments(post_id: str) -> list[dict]:
    if not post_id:
        return []
    response = get_client().table("community_comments").select("*").eq("post_id", post_id).neq("status", "deleted").order("created_at").execute()
    return _rows_from_response(response)


def list_comments_by_user(auth_user_id: str, limit: int = 50) -> list[dict]:
    if not auth_user_id:
        return []
    response = (
        get_client()
        .table("community_comments")
        .select("*")
        .eq("author_auth_user_id", auth_user_id)
        .neq("status", "deleted")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return _rows_from_response(response)


def get_comment(comment_id: str) -> dict | None:
    if not comment_id:
        return None
    response = get_client().table("community_comments").select("*").eq("id", comment_id).limit(1).execute()
    return _first_row(response)


def soft_delete_comment(comment_id: str) -> None:
    if not comment_id:
        return
    payload = {"status": "deleted", "updated_at": _now_iso()}
    get_client().table("community_comments").update(payload).eq("id", comment_id).execute()


def create_comment(comment_payload: dict) -> dict | None:
    payload = dict(comment_payload)
    payload.setdefault("id", str(uuid4()))
    payload.setdefault("status", "active")
    payload.setdefault("created_at", _now_iso())
    payload.setdefault("updated_at", payload["created_at"])
    payload.setdefault("like_count", 0)
    payload.setdefault("dislike_count", 0)
    payload.setdefault("score", 0)
    parent_comment_id = str(payload.get("parent_comment_id") or "").strip() or None
    if parent_comment_id:
        parent = get_comment(parent_comment_id)
        if not parent or str(parent.get("post_id") or "") != str(payload.get("post_id") or ""):
            raise ValueError("Invalid reply target.")
        payload["parent_comment_id"] = parent_comment_id
        payload["depth"] = min(int(parent.get("depth") or 0) + 1, 6)
    else:
        payload["parent_comment_id"] = None
        payload["depth"] = 0
    get_client().table("community_comments").insert(payload).execute()
    _bump_post_counts(str(payload.get("post_id") or ""), comments=1, touch=True)
    post = get_post(str(payload.get("post_id") or ""))
    if post and str(post.get("author_auth_user_id") or "") != str(payload.get("author_auth_user_id") or ""):
        create_notification(
            recipient_auth_user_id=str(post.get("author_auth_user_id") or ""),
            actor_auth_user_id=str(payload.get("author_auth_user_id") or ""),
            actor_name=str(payload.get("author_display_name") or payload.get("author_username") or "Member"),
            notification_type="comment",
            entity_type="post",
            entity_id=str(payload.get("post_id") or ""),
            post_id=str(payload.get("post_id") or ""),
            message=f"commented on your post: {str(post.get('title') or '').strip()}",
        )
    if parent_comment_id:
        parent = get_comment(parent_comment_id)
        if parent and str(parent.get("author_auth_user_id") or "") not in {str(payload.get("author_auth_user_id") or ""), str(post.get("author_auth_user_id") or "") if post else ""}:
            create_notification(
                recipient_auth_user_id=str(parent.get("author_auth_user_id") or ""),
                actor_auth_user_id=str(payload.get("author_auth_user_id") or ""),
                actor_name=str(payload.get("author_display_name") or payload.get("author_username") or "Member"),
                notification_type="reply",
                entity_type="comment",
                entity_id=str(parent_comment_id),
                post_id=str(payload.get("post_id") or ""),
                message="replied to your comment",
            )
    return get_comment(payload["id"])


def _get_reaction(auth_user_id: str, target_type: str, target_id: str) -> dict | None:
    response = (
        get_client()
        .table("community_reactions")
        .select("*")
        .eq("auth_user_id", auth_user_id)
        .eq("target_type", target_type)
        .eq("target_id", target_id)
        .limit(1)
        .execute()
    )
    return _first_row(response)


def _get_reaction_target(target_type: str, target_id: str) -> dict | None:
    if target_type == "post":
        return get_post(target_id)
    if target_type == "comment":
        return get_comment(target_id)
    return None


def set_reaction(*, auth_user_id: str, actor_name: str, target_type: str, target_id: str, vote_type: str) -> dict:
    if target_type not in {"post", "comment"}:
        raise ValueError("Unsupported reaction target.")
    if vote_type not in {"like", "dislike"}:
        raise ValueError("Unsupported reaction type.")

    target = _get_reaction_target(target_type, target_id)
    if not target:
        raise ValueError("Target was not found.")

    existing = _get_reaction(auth_user_id, target_type, target_id)
    like_delta = 0
    dislike_delta = 0
    inserted_or_updated = False

    if existing and str(existing.get("vote_type") or "") == vote_type:
        get_client().table("community_reactions").delete().eq("id", existing["id"]).execute()
        if vote_type == "like":
            like_delta = -1
        else:
            dislike_delta = -1
    elif existing:
        payload = {"vote_type": vote_type, "updated_at": _now_iso()}
        get_client().table("community_reactions").update(payload).eq("id", existing["id"]).execute()
        if vote_type == "like":
            like_delta = 1
            dislike_delta = -1
        else:
            like_delta = -1
            dislike_delta = 1
        inserted_or_updated = True
    else:
        payload = {
            "id": str(uuid4()),
            "auth_user_id": auth_user_id,
            "target_type": target_type,
            "target_id": target_id,
            "vote_type": vote_type,
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        }
        get_client().table("community_reactions").insert(payload).execute()
        if vote_type == "like":
            like_delta = 1
        else:
            dislike_delta = 1
        inserted_or_updated = True

    updated_counts: dict | None
    if target_type == "post":
        updated_counts = _bump_post_counts(target_id, likes=like_delta, dislikes=dislike_delta)
    else:
        updated_counts = _bump_comment_counts(target_id, likes=like_delta, dislikes=dislike_delta)

    if inserted_or_updated and str(target.get("author_auth_user_id") or "") != auth_user_id:
        create_notification(
            recipient_auth_user_id=str(target.get("author_auth_user_id") or ""),
            actor_auth_user_id=auth_user_id,
            actor_name=actor_name,
            notification_type=f"{vote_type}",
            entity_type=target_type,
            entity_id=target_id,
            post_id=str(target.get("post_id") or target.get("id") or ""),
            message=f"reacted to your {target_type}",
        )

    counts = updated_counts or {"score": 0, "like_count": 0, "dislike_count": 0}
    return {
        "target_id": target_id,
        "target_type": target_type,
        "score": int(counts.get("score") or 0),
        "like_count": int(counts.get("like_count") or 0),
        "dislike_count": int(counts.get("dislike_count") or 0),
    }


def create_notification(
    *,
    recipient_auth_user_id: str,
    actor_auth_user_id: str,
    actor_name: str,
    notification_type: str,
    entity_type: str,
    entity_id: str,
    post_id: str | None = None,
    message: str,
) -> None:
    if not recipient_auth_user_id or recipient_auth_user_id == actor_auth_user_id:
        return
    payload = {
        "id": str(uuid4()),
        "recipient_auth_user_id": recipient_auth_user_id,
        "actor_auth_user_id": actor_auth_user_id,
        "actor_name": actor_name,
        "notification_type": notification_type,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "post_id": post_id,
        "message": message,
        "is_read": False,
        "created_at": _now_iso(),
    }
    get_client().table("community_notifications").insert(payload).execute()


def list_notifications(auth_user_id: str, *, limit: int = 50) -> list[dict]:
    response = (
        get_client()
        .table("community_notifications")
        .select("*")
        .eq("recipient_auth_user_id", auth_user_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return _rows_from_response(response)


def get_notification(auth_user_id: str, notification_id: str) -> dict | None:
    if not auth_user_id or not notification_id:
        return None
    response = (
        get_client()
        .table("community_notifications")
        .select("*")
        .eq("recipient_auth_user_id", auth_user_id)
        .eq("id", notification_id)
        .limit(1)
        .execute()
    )
    return _first_row(response)


def count_unread_notifications(auth_user_id: str) -> int:
    if not auth_user_id:
        return 0
    response = (
        get_client()
        .table("community_notifications")
        .select("id")
        .eq("recipient_auth_user_id", auth_user_id)
        .eq("is_read", False)
        .execute()
    )
    return len(_rows_from_response(response))


def mark_notifications_read(auth_user_id: str, notification_id: str | None = None) -> None:
    query = get_client().table("community_notifications").update({"is_read": True}).eq("recipient_auth_user_id", auth_user_id)
    if notification_id:
        query = query.eq("id", notification_id)
    query.execute()


def get_or_create_chat_channel(hub_id: str) -> dict:
    response = get_client().table("community_chat_channels").select("*").eq("hub_id", hub_id).eq("slug", "general").limit(1).execute()
    existing = _first_row(response)
    if existing:
        return existing
    payload = {
        "id": str(uuid4()),
        "hub_id": hub_id,
        "slug": "general",
        "name": "General",
        "created_at": _now_iso(),
    }
    get_client().table("community_chat_channels").insert(payload).execute()
    return payload


def list_chat_messages(hub_slug: str, *, limit: int = 80) -> list[dict]:
    hub = get_hub_by_slug(hub_slug)
    if not hub:
        return []
    channel = get_or_create_chat_channel(str(hub.get("id") or ""))
    response = (
        get_client()
        .table("community_chat_messages")
        .select("*")
        .eq("channel_id", channel["id"])
        .neq("status", "deleted")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return list(reversed(_rows_from_response(response)))


def create_chat_message(hub_slug: str, *, author_auth_user_id: str, author_username: str, author_display_name: str, body: str) -> dict | None:
    hub = get_hub_by_slug(hub_slug)
    if not hub:
        return None
    channel = get_or_create_chat_channel(str(hub.get("id") or ""))
    payload = {
        "id": str(uuid4()),
        "channel_id": channel["id"],
        "author_auth_user_id": author_auth_user_id,
        "author_username": author_username,
        "author_display_name": author_display_name,
        "body": body,
        "status": "active",
        "created_at": _now_iso(),
    }
    get_client().table("community_chat_messages").insert(payload).execute()
    return payload


def list_conversations(auth_user_id: str) -> list[dict]:
    if not auth_user_id:
        return []
    membership_response = (
        get_client()
        .table("community_conversation_members")
        .select("*")
        .eq("auth_user_id", auth_user_id)
        .execute()
    )
    memberships = _rows_from_response(membership_response)
    conversation_ids = [str(row.get("conversation_id")) for row in memberships if row.get("conversation_id")]
    if not conversation_ids:
        return []

    conversation_rows = (
        get_client().table("community_conversations").select("*").in_("id", conversation_ids).order("updated_at", desc=True).execute()
    )
    member_rows = (
        get_client().table("community_conversation_members").select("*").in_("conversation_id", conversation_ids).execute()
    )
    message_rows = (
        get_client().table("community_direct_messages").select("*").in_("conversation_id", conversation_ids).order("created_at", desc=True).execute()
    )

    members_by_conversation: dict[str, list[dict]] = {}
    for row in _rows_from_response(member_rows):
        members_by_conversation.setdefault(str(row.get("conversation_id") or ""), []).append(row)

    latest_by_conversation: dict[str, dict] = {}
    for row in _rows_from_response(message_rows):
        conversation_id = str(row.get("conversation_id") or "")
        latest_by_conversation.setdefault(conversation_id, row)

    conversations: list[dict] = []
    for row in _rows_from_response(conversation_rows):
        conversation_id = str(row.get("id") or "")
        participant_rows = [member for member in members_by_conversation.get(conversation_id, []) if str(member.get("auth_user_id") or "") != auth_user_id]
        title = ", ".join(str(member.get("display_name") or member.get("username") or "Member") for member in participant_rows) or "Direct message"
        item = dict(row)
        item["participants"] = participant_rows
        item["title"] = title
        item["latest_message"] = latest_by_conversation.get(conversation_id)
        conversations.append(item)
    return conversations


def _conversation_memberships(conversation_id: str) -> list[dict]:
    response = get_client().table("community_conversation_members").select("*").eq("conversation_id", conversation_id).execute()
    return _rows_from_response(response)


def _is_conversation_member(conversation_id: str, auth_user_id: str) -> bool:
    memberships = _conversation_memberships(conversation_id)
    return any(str(member.get("auth_user_id") or "") == auth_user_id for member in memberships)


def get_or_create_conversation(*, auth_user_id: str, author_username: str, author_display_name: str, other_username: str) -> dict:
    other = find_user_account_by_username(other_username)
    if not other:
        raise ValueError("That username was not found.")
    other_auth_user_id = str(other.get("auth_user_id") or "")
    if other_auth_user_id == auth_user_id:
        raise ValueError("You cannot start a direct message with yourself.")

    existing = list_conversations(auth_user_id)
    for conversation in existing:
        participant_ids = {str(member.get("auth_user_id") or "") for member in conversation.get("participants") or []}
        if participant_ids == {other_auth_user_id}:
            return conversation

    conversation_id = str(uuid4())
    timestamp = _now_iso()
    conversation = {"id": conversation_id, "created_at": timestamp, "updated_at": timestamp}
    get_client().table("community_conversations").insert(conversation).execute()
    members = [
        {
            "id": str(uuid4()),
            "conversation_id": conversation_id,
            "auth_user_id": auth_user_id,
            "username": author_username,
            "display_name": author_display_name,
            "joined_at": timestamp,
        },
        {
            "id": str(uuid4()),
            "conversation_id": conversation_id,
            "auth_user_id": other_auth_user_id,
            "username": str(other.get("username") or ""),
            "display_name": str(other.get("display_name") or other.get("username") or other.get("email") or "Member"),
            "joined_at": timestamp,
        },
    ]
    get_client().table("community_conversation_members").insert(members).execute()
    return {
        **conversation,
        "participants": [members[1]],
        "title": members[1]["display_name"],
        "latest_message": None,
    }


def list_direct_messages(conversation_id: str, *, auth_user_id: str, limit: int = 80) -> list[dict]:
    if not _is_conversation_member(conversation_id, auth_user_id):
        raise ValueError("You do not have access to this conversation.")
    response = (
        get_client()
        .table("community_direct_messages")
        .select("*")
        .eq("conversation_id", conversation_id)
        .neq("status", "deleted")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return list(reversed(_rows_from_response(response)))


def create_direct_message(
    conversation_id: str,
    *,
    auth_user_id: str,
    author_username: str,
    author_display_name: str,
    body: str,
) -> dict:
    if not _is_conversation_member(conversation_id, auth_user_id):
        raise ValueError("You do not have access to this conversation.")
    payload = {
        "id": str(uuid4()),
        "conversation_id": conversation_id,
        "author_auth_user_id": auth_user_id,
        "author_username": author_username,
        "author_display_name": author_display_name,
        "body": body,
        "status": "active",
        "created_at": _now_iso(),
    }
    get_client().table("community_direct_messages").insert(payload).execute()
    get_client().table("community_conversations").update({"updated_at": payload["created_at"]}).eq("id", conversation_id).execute()
    for member in _conversation_memberships(conversation_id):
        member_auth_user_id = str(member.get("auth_user_id") or "")
        if member_auth_user_id != auth_user_id:
            create_notification(
                recipient_auth_user_id=member_auth_user_id,
                actor_auth_user_id=auth_user_id,
                actor_name=author_display_name or author_username,
                notification_type="direct_message",
                entity_type="conversation",
                entity_id=conversation_id,
                message="sent you a direct message",
            )
    return payload


def upload_post_image(file_storage: FileStorage, *, auth_user_id: str) -> dict:
    filename = secure_filename(file_storage.filename or "upload")
    if not filename:
        raise ValueError("Image upload is missing a file name.")

    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    allowed_extensions = {"png", "jpg", "jpeg", "gif", "webp"}
    if extension not in allowed_extensions:
        raise ValueError("Only png, jpg, jpeg, gif, and webp images are supported.")

    content = file_storage.read()
    file_storage.stream.seek(0)
    max_bytes = int(current_app.config.get("COMMUNITY_IMAGE_MAX_BYTES") or 10 * 1024 * 1024)
    if len(content) > max_bytes:
        raise ValueError("Image is too large for the current upload limit.")

    bucket = current_app.config.get("COMMUNITY_MEDIA_BUCKET") or "community-media"
    storage_path = posixpath.join("posts", auth_user_id, f"{uuid4().hex}-{filename}")
    options = {"content-type": file_storage.mimetype or "application/octet-stream", "upsert": "false"}
    storage = get_client().storage.from_(bucket)
    storage.upload(storage_path, content, options)
    public_url = storage.get_public_url(storage_path)
    if isinstance(public_url, dict):
        public_url = public_url.get("publicUrl") or public_url.get("public_url") or ""
    return {
        "id": str(uuid4()),
        "media_kind": "image",
        "storage_bucket": bucket,
        "storage_path": storage_path,
        "public_url": str(public_url),
    }


def upload_profile_image(file_storage: FileStorage, *, auth_user_id: str) -> dict:
    filename = secure_filename(file_storage.filename or "profile-image")
    if not filename:
        raise ValueError("Profile image upload is missing a file name.")

    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    allowed_extensions = {"png", "jpg", "jpeg", "gif", "webp"}
    if extension not in allowed_extensions:
        raise ValueError("Only png, jpg, jpeg, gif, and webp images are supported.")

    content = file_storage.read()
    file_storage.stream.seek(0)
    max_bytes = int(current_app.config.get("COMMUNITY_IMAGE_MAX_BYTES") or 10 * 1024 * 1024)
    if len(content) > max_bytes:
        raise ValueError("Image is too large for the current upload limit.")

    bucket = current_app.config.get("COMMUNITY_MEDIA_BUCKET") or "community-media"
    storage_path = posixpath.join("profiles", auth_user_id, f"{uuid4().hex}-{filename}")
    options = {"content-type": file_storage.mimetype or "application/octet-stream", "upsert": "false"}
    storage = get_client().storage.from_(bucket)
    storage.upload(storage_path, content, options)
    public_url = storage.get_public_url(storage_path)
    if isinstance(public_url, dict):
        public_url = public_url.get("publicUrl") or public_url.get("public_url") or ""
    return {
        "storage_bucket": bucket,
        "storage_path": storage_path,
        "public_url": str(public_url),
    }


def quote_username(value: str) -> str:
    return quote(_normalize_username(value))
