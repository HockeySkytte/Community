from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
import re
from urllib.parse import urlparse

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for
from markupsafe import Markup, escape

from ..auth_helpers import get_current_user, login_required, login_user, require_csrf
from .. import supabase_client as sb


community_bp = Blueprint("community", __name__)
_IMAGE_TOKEN_PATTERN = re.compile(r"^\s*\[\[image\]\]\s*$", flags=re.IGNORECASE)
_IMAGE_URL_LINE_PATTERN = re.compile(r"^\s*\[image=(https?://[^\]]+)\]\s*$", flags=re.IGNORECASE)


def _is_admin(user: dict | None) -> bool:
    return bool((user or {}).get("is_admin"))


def _can_edit_post(user: dict | None, post: dict | None) -> bool:
    if not user or not post:
        return False
    return str(user.get("user_id") or "") == str(post.get("author_auth_user_id") or "")


def _can_delete_post(user: dict | None, post: dict | None) -> bool:
    return _can_edit_post(user, post) or _is_admin(user)


def _can_delete_comment(user: dict | None, comment: dict | None) -> bool:
    if not user or not comment:
        return False
    return _is_admin(user) or str(user.get("user_id") or "") == str(comment.get("author_auth_user_id") or "")


def _ensure_can_participate(user: dict | None) -> tuple[bool, str | None]:
    user_id = str((user or {}).get("user_id") or "")
    if not user_id:
        return False, "Authentication is required."
    active_ban = sb.get_active_community_ban(user_id)
    if not active_ban:
        return True, None
    until = active_ban.get("until")
    until_text = until.strftime("%Y-%m-%d %H:%M UTC") if isinstance(until, datetime) else "a later date"
    reason = str(active_ban.get("reason") or "").strip()
    detail = f"You are banned from posting and commenting until {until_text}."
    if reason:
        detail = f"{detail} Reason: {reason}"
    return False, detail


def _parse_iso_timestamp(raw: str | None) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        value = datetime.fromisoformat(text)
    except ValueError:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _timeframe_start(range_key: str) -> datetime | None:
    now = datetime.now(timezone.utc)
    mapping = {
        "24h": now - timedelta(hours=24),
        "7d": now - timedelta(days=7),
        "30d": now - timedelta(days=30),
        "90d": now - timedelta(days=90),
    }
    return mapping.get(range_key)


def _build_cumulative_view_points(events: list[dict], range_key: str) -> list[dict]:
    now = datetime.now(timezone.utc)
    start_at = _timeframe_start(range_key)
    if range_key == "24h":
        step = timedelta(hours=1)
        align = "hour"
        start = (start_at or (now - timedelta(hours=24))).replace(minute=0, second=0, microsecond=0)
    else:
        step = timedelta(days=1)
        align = "day"
        start = (start_at or (now - timedelta(days=30))).replace(hour=0, minute=0, second=0, microsecond=0)

    if range_key == "all" and events:
        first_event_at = _parse_iso_timestamp(events[0].get("created_at"))
        if first_event_at:
            start = first_event_at.replace(hour=0, minute=0, second=0, microsecond=0)

    counts_by_bucket: dict[str, int] = {}
    for event in events:
        created_at = _parse_iso_timestamp(event.get("created_at"))
        if not created_at:
            continue
        if align == "hour":
            bucket_dt = created_at.replace(minute=0, second=0, microsecond=0)
            bucket_key = bucket_dt.strftime("%Y-%m-%d %H:00")
        else:
            bucket_dt = created_at.replace(hour=0, minute=0, second=0, microsecond=0)
            bucket_key = bucket_dt.strftime("%Y-%m-%d")
        counts_by_bucket[bucket_key] = counts_by_bucket.get(bucket_key, 0) + 1

    points: list[dict] = []
    running_total = 0
    cursor = start
    while cursor <= now:
        if align == "hour":
            label = cursor.strftime("%b %d %H:00")
            key = cursor.strftime("%Y-%m-%d %H:00")
        else:
            label = cursor.strftime("%b %d")
            key = cursor.strftime("%Y-%m-%d")
        running_total += counts_by_bucket.get(key, 0)
        points.append({"label": label, "value": running_total})
        cursor += step

    return points


def _format_inline_markup(line: str, allow_size: bool = True) -> str:
    rendered = str(escape(line))

    allowed_fonts = {
        "ibm plex sans",
        "space grotesk",
        "merriweather",
        "georgia",
        "courier new",
    }

    def size_replace(match: re.Match[str]) -> str:
        size = max(12, min(48, int(match.group(1))))
        return f'<span style="font-size:{size}px">{match.group(2)}</span>'

    def color_replace(match: re.Match[str]) -> str:
        color_value = str(match.group(1) or "").strip()
        if not re.fullmatch(r"#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?", color_value) and not re.fullmatch(
            r"[a-zA-Z]{3,20}", color_value
        ):
            return match.group(2)
        return f'<span style="color:{color_value.lower()}">{match.group(2)}</span>'

    def font_replace(match: re.Match[str]) -> str:
        font_raw = str(match.group(1) or "").strip().replace('"', "")
        font_value = re.sub(r"[^a-zA-Z0-9\s\-]", "", font_raw)
        if font_value.strip().lower() not in allowed_fonts:
            return match.group(2)
        safe_font = str(escape(font_value.strip()))
        return f'<span style="font-family:{safe_font}">{match.group(2)}</span>'

    def link_replace(match: re.Match[str]) -> str:
        href = str(match.group(1) or "")
        if not href.startswith(("http://", "https://")):
            return match.group(2)
        safe_href = str(escape(href))
        return f'<a href="{safe_href}" target="_blank" rel="noopener noreferrer">{match.group(2)}</a>'

    # Allow nested bbcode-like tags by applying replacements until stable.
    for _ in range(6):
        before = rendered
        rendered = re.sub(r"\[b\](.*?)\[/b\]", r"<strong>\1</strong>", rendered, flags=re.IGNORECASE)
        rendered = re.sub(r"\[i\](.*?)\[/i\]", r"<em>\1</em>", rendered, flags=re.IGNORECASE)
        rendered = re.sub(r"\[u\](.*?)\[/u\]", r"<u>\1</u>", rendered, flags=re.IGNORECASE)
        rendered = re.sub(r"\[s\](.*?)\[/s\]", r"<s>\1</s>", rendered, flags=re.IGNORECASE)
        if allow_size:
            rendered = re.sub(r"\[size=(\d{1,2})\](.*?)\[/size\]", size_replace, rendered, flags=re.IGNORECASE)
        rendered = re.sub(r"\[color=(.*?)\](.*?)\[/color\]", color_replace, rendered, flags=re.IGNORECASE)
        rendered = re.sub(r"\[font=(.*?)\](.*?)\[/font\]", font_replace, rendered, flags=re.IGNORECASE)
        rendered = re.sub(r"\[link=(.*?)\](.*?)\[/link\]", link_replace, rendered, flags=re.IGNORECASE)
        if rendered == before:
            break
    return rendered


def _render_rich_text_html(body: str, media_rows: list[dict] | None = None, allow_size: bool = True) -> Markup:
    lines = str(body or "").replace("\r\n", "\n").split("\n")
    image_rows = [row for row in (media_rows or []) if str(row.get("media_kind") or "") == "image"]
    image_index = 0
    html_parts: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            html_parts.append("<br>")
            continue

        image_url_match = _IMAGE_URL_LINE_PATTERN.match(stripped)
        if image_url_match:
            image_url = escape(str(image_url_match.group(1) or ""))
            html_parts.append(f'<figure class="inline-media"><img src="{image_url}" alt="Embedded image"></figure>')
            continue

        if _IMAGE_TOKEN_PATTERN.match(stripped):
            image_row = image_rows[image_index] if image_index < len(image_rows) else None
            image_index += 1
            if image_row and image_row.get("public_url"):
                image_url = escape(str(image_row.get("public_url") or ""))
                html_parts.append(f'<figure class="inline-media"><img src="{image_url}" alt="Embedded image"></figure>')
            continue

        embed_url = _parse_video_embed(stripped)
        if embed_url:
            safe_embed = escape(embed_url)
            html_parts.append(
                f'<div class="video-frame inline-video"><iframe src="{safe_embed}" title="Embedded video" loading="lazy" allowfullscreen></iframe></div>'
            )
            continue

        html_parts.append(f"<p>{_format_inline_markup(line, allow_size=allow_size)}</p>")

    return Markup("".join(html_parts))


def _notification_target_url(notification: dict) -> str:
    entity_type = str(notification.get("entity_type") or "").strip().lower()
    entity_id = str(notification.get("entity_id") or "").strip()
    post_id = str(notification.get("post_id") or "").strip()

    if entity_type == "conversation" and entity_id:
        return url_for("community.notifications_page")
    if entity_type == "post" and entity_id:
        return url_for("community.post_detail", post_id=entity_id)
    if post_id:
        return url_for("community.post_detail", post_id=post_id)
    return url_for("community.notifications_page")


def _embed_comment_image_urls(body: str, image_urls: list[str]) -> str:
    if not image_urls:
        return body
    lines = str(body or "").replace("\r\n", "\n").split("\n")
    out_lines: list[str] = []
    image_index = 0

    for line in lines:
        if _IMAGE_TOKEN_PATTERN.match(line.strip()) and image_index < len(image_urls):
            out_lines.append(f"[image={image_urls[image_index]}]")
            image_index += 1
            continue
        out_lines.append(line)

    while image_index < len(image_urls):
        out_lines.append(f"[image={image_urls[image_index]}]")
        image_index += 1

    return "\n".join(out_lines).strip()


def _normalize_multiline_text(value: str) -> str:
    return "\n".join(line.rstrip() for line in str(value or "").replace("\r\n", "\n").split("\n")).strip()


def _parse_video_embed(video_url: str) -> str | None:
    raw = str(video_url or "").strip()
    if not raw:
        return None
    parsed = urlparse(raw)
    host = (parsed.netloc or "").lower().replace("www.", "")
    path = parsed.path or ""
    query_pairs = {}
    if parsed.query:
        for pair in parsed.query.split("&"):
            if "=" not in pair:
                continue
            key, value = pair.split("=", 1)
            query_pairs[key] = value

    if host in {"youtube.com", "m.youtube.com"}:
        video_id = query_pairs.get("v")
        if video_id:
            return f"https://www.youtube.com/embed/{video_id}"
        if path.startswith("/embed/"):
            return f"https://www.youtube.com{path}"
        if path.startswith("/shorts/"):
            return f"https://www.youtube.com/embed/{path.split('/')[2]}"
    if host == "youtu.be":
        video_id = path.strip("/")
        if video_id:
            return f"https://www.youtube.com/embed/{video_id}"
    if host == "vimeo.com":
        video_id = path.strip("/")
        if video_id:
            return f"https://player.vimeo.com/video/{video_id}"
    if host == "player.vimeo.com" and path.startswith("/video/"):
        return f"https://player.vimeo.com{path}"
    if host == "loom.com" and path.startswith("/share/"):
        video_id = path.split("/")[-1]
        if video_id:
            return f"https://www.loom.com/embed/{video_id}"
    if host == "loom.com" and path.startswith("/embed/"):
        return f"https://www.loom.com{path}"
    return None


def _render_post_body_html(body: str, media_rows: list[dict] | None = None) -> Markup:
    return _render_rich_text_html(body, media_rows, allow_size=True)


def _has_inline_image_tokens(body: str) -> bool:
    text = str(body or "")
    if "[[image]]" in text.lower():
        return True
    return bool(re.search(r"\[image=https?://[^\]]+\]", text, flags=re.IGNORECASE))


def _decorate_post(post: dict | None) -> dict | None:
    if not post:
        return None
    item = dict(post)
    item["video_embed_url"] = _parse_video_embed(str(item.get("video_url") or ""))
    item["share_url"] = url_for("community.post_detail", post_id=item["id"], _external=True)
    item["insights_url"] = url_for("community.post_insights", post_id=item["id"])
    item["has_inline_images"] = _has_inline_image_tokens(str(item.get("body") or ""))
    item["rendered_body_html"] = _render_post_body_html(str(item.get("body") or ""), item.get("media") or [])
    _body_raw = re.sub(r"\[\[image\]\]", "", str(item.get("body") or ""), flags=re.IGNORECASE)
    _body_raw = re.sub(r"\[/?(?:b|i|u|s)\]", "", _body_raw, flags=re.IGNORECASE)
    _body_raw = re.sub(r"\[(?:size|color|font|link)=[^\]]+\]", "", _body_raw, flags=re.IGNORECASE)
    _body_raw = re.sub(r"\[/(?:size|color|font|link)\]", "", _body_raw, flags=re.IGNORECASE)
    _body_raw = re.sub(r"\[image=[^\]]+\]", "", _body_raw, flags=re.IGNORECASE)
    item["body_preview"] = _body_raw.strip()[:220]
    return item


def _hub_site_url(hub_slug: str | None) -> str | None:
    slug = str(hub_slug or "").strip().lower()
    if slug == "nhl":
        return "https://nhl.hockey-statistics.com/"
    if slug == "pwhl":
        return "https://nhl.hockey-statistics.com/"
    return None


def _decorate_hub(hub: dict | None) -> dict | None:
    if not hub:
        return None
    item = dict(hub)
    item["site_url"] = _hub_site_url(item.get("slug"))
    return item


def _decorate_hubs(hubs: list[dict]) -> list[dict]:
    return [_decorate_hub(hub) for hub in hubs if hub]


def _decorate_posts(posts: list[dict]) -> list[dict]:
    return [_decorate_post(post) for post in posts if post]


def _build_comment_tree(comments: list[dict], auth_user: dict | None = None) -> list[dict]:
    comments_by_parent: dict[str | None, list[dict]] = defaultdict(list)
    items: dict[str, dict] = {}
    for row in comments:
        item = dict(row)
        item["children"] = []
        item["rendered_body_html"] = _render_rich_text_html(str(item.get("body") or ""), None, allow_size=False)
        item["can_delete"] = _can_delete_comment(auth_user, item)
        items[str(item.get("id") or "")] = item
        parent_id = str(item.get("parent_comment_id") or "") or None
        comments_by_parent[parent_id].append(item)

    for parent_id, children in comments_by_parent.items():
        if parent_id and parent_id in items:
            items[parent_id]["children"] = children
    return comments_by_parent.get(None, [])


@community_bp.get("/")
def index():
    return redirect(url_for("community.home"))


@community_bp.get("/home")
def home():
    hubs = _decorate_hubs(sb.list_hubs())
    posts = _decorate_posts(sb.list_posts(limit=18, sort="new"))
    recent_comments = sb.list_recent_comments(limit=18)
    return render_template("home.html", hubs=hubs, posts=posts, recent_comment_count=len(recent_comments), active_tab="home")


@community_bp.get("/hubs/<hub_slug>")
def hub_feed(hub_slug: str):
    auth_user = get_current_user() or {}
    sort = str(request.args.get("sort") or "new").strip().lower()
    if sort not in {"new", "top", "my_posts"}:
        sort = "new"
    if sort == "my_posts" and not auth_user.get("user_id"):
        sort = "new"
    search_query = str(request.args.get("q") or "").strip() or None
    hub = _decorate_hub(sb.get_hub_by_slug(hub_slug))
    if not hub:
        abort(404)
    author_user_id = str(auth_user.get("user_id") or "") if sort == "my_posts" else None
    posts = _decorate_posts(
        sb.list_posts(hub_slug=hub_slug, limit=30, sort=sort, search=search_query, author_user_id=author_user_id)
    )
    return render_template("hub.html", hub=hub, posts=posts, sort=sort, search_query=search_query, active_tab=f"hub:{hub_slug}")


@community_bp.get("/hubs/<hub_slug>/posts/new")
@login_required
def new_post_page(hub_slug: str):
    hub = sb.get_hub_by_slug(hub_slug)
    if not hub:
        abort(404)
    auth_user = get_current_user() or {}
    allowed, message = _ensure_can_participate(auth_user)
    if not allowed:
        flash(str(message or "You cannot post right now."), "error")
        return redirect(url_for("community.hub_feed", hub_slug=hub_slug))
    return render_template("create_post.html", hub=hub, active_tab=f"hub:{hub_slug}")


@community_bp.post("/hubs/<hub_slug>/posts")
@login_required
def create_post(hub_slug: str):
    require_csrf()
    hub = sb.get_hub_by_slug(hub_slug)
    if not hub:
        abort(404)

    auth_user = get_current_user() or {}
    allowed, message = _ensure_can_participate(auth_user)
    if not allowed:
        flash(str(message or "You cannot post right now."), "error")
        return redirect(url_for("community.hub_feed", hub_slug=hub_slug))
    title = " ".join(str(request.form.get("title") or "").split()).strip()
    body = _normalize_multiline_text(str(request.form.get("body") or ""))
    video_url = str(request.form.get("video_url") or "").strip()
    if not title:
        flash("Posts need a title.", "error")
        return redirect(url_for("community.new_post_page", hub_slug=hub_slug))
    if video_url and not _parse_video_embed(video_url):
        flash("Only YouTube, Vimeo, and Loom video links are supported in this slice.", "error")
        return redirect(url_for("community.new_post_page", hub_slug=hub_slug))

    media_rows = []
    files = [file for file in request.files.getlist("images") if file and file.filename]
    if len(files) > 4:
        flash("You can attach up to four images per post right now.", "error")
        return redirect(url_for("community.new_post_page", hub_slug=hub_slug))
    for file in files:
        try:
            media_rows.append(sb.upload_post_image(file, auth_user_id=str(auth_user.get("user_id") or "")))
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("community.new_post_page", hub_slug=hub_slug))

    thumbnail_url = None
    thumbnail_file = request.files.get("thumbnail")
    if thumbnail_file and thumbnail_file.filename:
        try:
            thumbnail_media = sb.upload_post_image(thumbnail_file, auth_user_id=str(auth_user.get("user_id") or ""))
            thumbnail_url = str(thumbnail_media.get("public_url") or "") or None
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("community.new_post_page", hub_slug=hub_slug))
    
    # If no explicit thumbnail, use first uploaded image as thumbnail
    if not thumbnail_url and media_rows:
        thumbnail_url = str(media_rows[0].get("public_url") or "") or None

    post = sb.create_post(
        {
            "hub_id": hub["id"],
            "author_auth_user_id": str(auth_user.get("user_id") or ""),
            "author_username": str(auth_user.get("username") or ""),
            "author_display_name": str(auth_user.get("display_name") or auth_user.get("username") or "Member"),
            "title": title,
            "body": body,
            "video_url": video_url or None,
            "preview_image_url": thumbnail_url,
        },
        media_rows,
    )
    if not post:
        flash("The post could not be saved.", "error")
        return redirect(url_for("community.new_post_page", hub_slug=hub_slug))
    flash("Post created.", "success")
    return redirect(url_for("community.post_detail", post_id=post["id"]))


@community_bp.get("/posts/<post_id>")
def post_detail(post_id: str):
    auth_user = get_current_user() or {}
    post = _decorate_post(sb.get_post(post_id))
    if not post:
        abort(404)
    sb.track_post_event(post_id, event_type="view", auth_user_id=str(auth_user.get("user_id") or ""))
    post["can_edit"] = _can_edit_post(auth_user, post)
    post["can_delete"] = _can_delete_post(auth_user, post)
    post["can_view_insights"] = post["can_delete"]
    comments = sb.list_comments(post_id)
    comment_tree = _build_comment_tree(comments, auth_user)
    return render_template("post_detail.html", post=post, comment_tree=comment_tree, active_tab=f"post:{post_id}")


@community_bp.post("/comments/<comment_id>/delete")
@login_required
def delete_comment(comment_id: str):
    require_csrf()
    auth_user = get_current_user() or {}
    allowed, message = _ensure_can_participate(auth_user)
    if not allowed:
        flash(str(message or "You cannot modify comments right now."), "error")
        return redirect(url_for("community.home"))
    comment = sb.get_comment(comment_id)
    if not comment:
        abort(404)
    if not _can_delete_comment(auth_user, comment):
        abort(403)
    sb.soft_delete_comment(comment_id)
    post_id = str(comment.get("post_id") or "")
    if post_id:
        sb.decrement_post_comment_count(post_id)
    flash("Comment deleted.", "info")
    return redirect(url_for("community.post_detail", post_id=post_id) + "#comments")


@community_bp.get("/posts/<post_id>/edit")
@login_required
def edit_post_page(post_id: str):
    auth_user = get_current_user() or {}
    post = sb.get_post(post_id)
    if not post:
        abort(404)
    if not _can_edit_post(auth_user, post):
        abort(403)
    hub = post.get("hub") or sb.get_hub_by_slug(str((post.get("hub") or {}).get("slug") or ""))
    return render_template("edit_post.html", post=_decorate_post(post), hub=hub, active_tab=f"post:{post_id}")


@community_bp.post("/posts/<post_id>/edit")
@login_required
def update_post(post_id: str):
    require_csrf()
    auth_user = get_current_user() or {}
    allowed, message = _ensure_can_participate(auth_user)
    if not allowed:
        flash(str(message or "You cannot post right now."), "error")
        return redirect(url_for("community.post_detail", post_id=post_id))
    post = sb.get_post(post_id)
    if not post:
        abort(404)
    if not _can_edit_post(auth_user, post):
        abort(403)

    title = " ".join(str(request.form.get("title") or "").split()).strip()
    body = _normalize_multiline_text(str(request.form.get("body") or ""))
    if not title:
        flash("Posts need a title.", "error")
        return redirect(url_for("community.edit_post_page", post_id=post_id))

    thumbnail_url = None
    thumbnail_file = request.files.get("thumbnail")
    if thumbnail_file and thumbnail_file.filename:
        try:
            thumbnail_media = sb.upload_post_image(thumbnail_file, auth_user_id=str(auth_user.get("user_id") or ""))
            thumbnail_url = str(thumbnail_media.get("public_url") or "") or None
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("community.edit_post_page", post_id=post_id))

    new_media_rows: list[dict] = []
    files = [file for file in request.files.getlist("images") if file and file.filename]
    if len(files) > 4:
        flash("You can attach up to four new images per edit.", "error")
        return redirect(url_for("community.edit_post_page", post_id=post_id))
    for file in files:
        try:
            new_media_rows.append(sb.upload_post_image(file, auth_user_id=str(auth_user.get("user_id") or "")))
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("community.edit_post_page", post_id=post_id))

    updated = sb.update_post(
        post_id,
        {
            "title": title,
            "body": body,
            "preview_image_url": thumbnail_url or post.get("preview_image_url"),
        },
    )
    if not updated:
        flash("The post could not be updated.", "error")
        return redirect(url_for("community.edit_post_page", post_id=post_id))
    if new_media_rows:
        sb.add_post_media(post_id, new_media_rows)
    flash("Post updated.", "success")
    return redirect(url_for("community.post_detail", post_id=post_id))


@community_bp.post("/posts/<post_id>/delete")
@login_required
def delete_post(post_id: str):
    require_csrf()
    auth_user = get_current_user() or {}
    allowed, message = _ensure_can_participate(auth_user)
    if not allowed:
        flash(str(message or "You cannot post right now."), "error")
        return redirect(url_for("community.post_detail", post_id=post_id))
    post = sb.get_post(post_id)
    if not post:
        abort(404)
    if not _can_delete_post(auth_user, post):
        abort(403)
    sb.soft_delete_post(post_id)
    flash("Post deleted.", "info")
    return redirect(url_for("community.hub_feed", hub_slug=str((post.get("hub") or {}).get("slug") or "nhl")))


@community_bp.get("/posts/<post_id>/insights")
@login_required
def post_insights(post_id: str):
    auth_user = get_current_user() or {}
    post = sb.get_post(post_id)
    if not post:
        abort(404)
    if not _can_delete_post(auth_user, post):
        abort(403)

    range_key = str(request.args.get("range") or "30d").strip().lower()
    if range_key not in {"24h", "7d", "30d", "90d", "all"}:
        range_key = "30d"
    start_at = _timeframe_start(range_key)

    views = sb.list_post_events(post_id, event_type="view", start_at=start_at)
    shares = sb.list_post_events(post_id, event_type="share", start_at=start_at)
    points = _build_cumulative_view_points(views, range_key)

    post_decorated = _decorate_post(post)
    post_decorated["can_edit"] = _can_edit_post(auth_user, post)
    post_decorated["can_delete"] = _can_delete_post(auth_user, post)
    return render_template(
        "post_insights.html",
        post=post_decorated,
        range_key=range_key,
        points=points,
        metrics={
            "views": len(views),
            "shares": len(shares),
            "likes": int(post.get("like_count") or 0),
            "dislikes": int(post.get("dislike_count") or 0),
        },
        active_tab=f"post:{post_id}",
    )


@community_bp.post("/posts/<post_id>/comments")
@login_required
def add_comment(post_id: str):
    require_csrf()
    post = sb.get_post(post_id)
    if not post:
        abort(404)
    auth_user = get_current_user() or {}
    allowed, message = _ensure_can_participate(auth_user)
    if not allowed:
        flash(str(message or "You cannot comment right now."), "error")
        return redirect(url_for("community.post_detail", post_id=post_id))
    body = _normalize_multiline_text(str(request.form.get("body") or ""))
    files = [file for file in request.files.getlist("images") if file and file.filename]
    if len(files) > 4:
        flash("You can attach up to four images per comment.", "error")
        return redirect(url_for("community.post_detail", post_id=post_id))
    uploaded_urls: list[str] = []
    for file in files:
        try:
            uploaded = sb.upload_post_image(file, auth_user_id=str(auth_user.get("user_id") or ""))
            uploaded_urls.append(str(uploaded.get("public_url") or ""))
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("community.post_detail", post_id=post_id))
    body = _embed_comment_image_urls(body, [url for url in uploaded_urls if url])
    if not body:
        flash("Comments cannot be empty.", "error")
        return redirect(url_for("community.post_detail", post_id=post_id))
    parent_comment_id = str(request.form.get("parent_comment_id") or "").strip() or None
    try:
        sb.create_comment(
            {
                "post_id": post_id,
                "parent_comment_id": parent_comment_id,
                "author_auth_user_id": str(auth_user.get("user_id") or ""),
                "author_username": str(auth_user.get("username") or ""),
                "author_display_name": str(auth_user.get("display_name") or auth_user.get("username") or "Member"),
                "body": body,
            }
        )
    except ValueError as exc:
        flash(str(exc), "error")
    else:
        flash("Comment added.", "success")
    return redirect(url_for("community.post_detail", post_id=post_id))


@community_bp.post("/api/reactions")
@login_required
def reactions_api():
    require_csrf()
    payload = request.get_json(silent=True) or request.form
    auth_user = get_current_user() or {}
    try:
        result = sb.set_reaction(
            auth_user_id=str(auth_user.get("user_id") or ""),
            actor_name=str(auth_user.get("display_name") or auth_user.get("username") or "Member"),
            target_type=str(payload.get("target_type") or ""),
            target_id=str(payload.get("target_id") or ""),
            vote_type=str(payload.get("vote_type") or ""),
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(result)


@community_bp.post("/api/posts/<post_id>/share")
@login_required
def share_post_api(post_id: str):
    require_csrf()
    auth_user = get_current_user() or {}
    post = sb.get_post(post_id)
    if not post:
        return jsonify({"error": "Post not found."}), 404
    sb.track_post_event(post_id, event_type="share", auth_user_id=str(auth_user.get("user_id") or ""))
    return jsonify({"ok": True})


@community_bp.get("/notifications")
@login_required
def notifications_page():
    auth_user = get_current_user() or {}
    notifications = sb.list_notifications(str(auth_user.get("user_id") or ""))
    decorated = []
    for notification in notifications:
        item = dict(notification)
        item["target_url"] = _notification_target_url(item)
        decorated.append(item)
    return render_template("notifications.html", notifications=decorated, active_tab="notifications")


@community_bp.get("/notifications/<notification_id>/open")
@login_required
def open_notification(notification_id: str):
    auth_user = get_current_user() or {}
    notification = sb.get_notification(str(auth_user.get("user_id") or ""), notification_id)
    if not notification:
        return redirect(url_for("community.notifications_page"))
    sb.mark_notifications_read(str(auth_user.get("user_id") or ""), notification_id)
    return redirect(_notification_target_url(notification))


@community_bp.post("/notifications/mark-read")
@login_required
def mark_notifications_read():
    require_csrf()
    auth_user = get_current_user() or {}
    notification_id = str(request.form.get("notification_id") or "").strip() or None
    sb.mark_notifications_read(str(auth_user.get("user_id") or ""), notification_id)
    return redirect(url_for("community.notifications_page"))


@community_bp.get("/chat/<hub_slug>")
@login_required
def hub_chat(hub_slug: str):
    abort(404)


@community_bp.get("/api/chat/<hub_slug>/messages")
@login_required
def chat_messages_api(hub_slug: str):
    return jsonify({"error": "disabled"}), 404


@community_bp.post("/api/chat/<hub_slug>/messages")
@login_required
def create_chat_message_api(hub_slug: str):
    return jsonify({"error": "disabled"}), 404


@community_bp.get("/messages")
@login_required
def messages_page():
    abort(404)


@community_bp.post("/messages/start")
@login_required
def start_conversation():
    abort(404)


@community_bp.get("/api/conversations/<conversation_id>/messages")
@login_required
def direct_messages_api(conversation_id: str):
    return jsonify({"error": "disabled"}), 404


@community_bp.post("/api/conversations/<conversation_id>/messages")
@login_required
def create_direct_message_api(conversation_id: str):
    return jsonify({"error": "disabled"}), 404


@community_bp.get("/admin/community-bans")
@login_required
def community_bans_page():
    auth_user = get_current_user() or {}
    if not _is_admin(auth_user):
        abort(403)
    search_query = str(request.args.get("q") or "").strip() or None
    users = sb.list_user_accounts(limit=300, search=search_query)
    now_utc = datetime.now(timezone.utc)
    decorated_users: list[dict] = []
    for row in users:
        item = dict(row)
        banned_until = _parse_iso_timestamp(str(item.get("community_banned_until") or ""))
        item["ban_active"] = bool(banned_until and banned_until > now_utc)
        item["banned_until_dt"] = banned_until
        decorated_users.append(item)
    return render_template(
        "admin_community_bans.html",
        users=decorated_users,
        search_query=search_query,
        active_tab="admin-community-bans",
    )


@community_bp.post("/admin/community-bans")
@login_required
def set_community_ban_route():
    require_csrf()
    auth_user = get_current_user() or {}
    if not _is_admin(auth_user):
        abort(403)

    target_auth_user_id = str(request.form.get("target_auth_user_id") or "").strip()
    reason = " ".join(str(request.form.get("reason") or "").split()).strip() or None
    ban_days_raw = str(request.form.get("ban_days") or "").strip()
    action = str(request.form.get("action") or "ban").strip().lower()
    if not target_auth_user_id:
        flash("Target user id is required.", "error")
        return redirect(url_for("community.community_bans_page"))

    if action == "clear":
        try:
            sb.set_community_ban(
                target_auth_user_id=target_auth_user_id,
                banned_until=None,
                reason=None,
                banned_by_auth_user_id=str(auth_user.get("user_id") or ""),
            )
        except ValueError as exc:
            flash(str(exc), "error")
        else:
            flash("Community ban removed.", "success")
        return redirect(url_for("community.community_bans_page"))

    try:
        ban_days = int(ban_days_raw or "0")
    except ValueError:
        flash("Ban days must be a number.", "error")
        return redirect(url_for("community.community_bans_page"))
    if ban_days <= 0:
        flash("Ban days must be greater than zero.", "error")
        return redirect(url_for("community.community_bans_page"))

    banned_until = (datetime.now(timezone.utc) + timedelta(days=ban_days)).isoformat()
    try:
        sb.set_community_ban(
            target_auth_user_id=target_auth_user_id,
            banned_until=banned_until,
            reason=reason,
            banned_by_auth_user_id=str(auth_user.get("user_id") or ""),
        )
    except ValueError as exc:
        flash(str(exc), "error")
    else:
        flash("Community ban updated.", "success")
    return redirect(url_for("community.community_bans_page"))


# ── Profile ───────────────────────────────────────────────────────────────────

@community_bp.get("/profile")
@login_required
def profile_page():
    auth_user = get_current_user() or {}
    user_id = str(auth_user.get("user_id") or "")
    tab = str(request.args.get("tab") or "posts").strip()
    if tab not in {"posts", "comments", "settings"}:
        tab = "posts"
    posts = sb.list_posts(author_user_id=user_id, limit=50) if tab == "posts" else []
    comments = sb.list_comments_by_user(user_id) if tab == "comments" else []
    return render_template(
        "profile.html",
        profile_user=auth_user,
        posts=posts,
        comments=comments,
        active_tab_name=tab,
        active_tab="profile",
    )


@community_bp.post("/profile/update")
@login_required
def update_profile():
    require_csrf()
    auth_user = get_current_user() or {}
    user_id = str(auth_user.get("user_id") or "")
    display_name = " ".join(str(request.form.get("display_name") or "").split()).strip()
    new_username = " ".join(str(request.form.get("username") or "").split()).strip().lower()
    if not display_name:
        flash("Display name cannot be empty.", "error")
        return redirect(url_for("community.profile_page", tab="settings"))
    if not new_username:
        flash("Username cannot be empty.", "error")
        return redirect(url_for("community.profile_page", tab="settings"))
    if len(new_username) < 3 or len(new_username) > 30:
        flash("Username must be between 3 and 30 characters.", "error")
        return redirect(url_for("community.profile_page", tab="settings"))
    if not re.fullmatch(r"[a-z0-9_]+", new_username):
        flash("Username may only contain letters, numbers, and underscores.", "error")
        return redirect(url_for("community.profile_page", tab="settings"))
    existing = sb.find_user_account_by_username(new_username)
    if existing and str(existing.get("auth_user_id") or "") != user_id:
        flash("That username is already taken.", "error")
        return redirect(url_for("community.profile_page", tab="settings"))

    profile_image_url = str(auth_user.get("profile_image_url") or "")
    profile_image = request.files.get("profile_image")
    if profile_image and profile_image.filename:
        try:
            uploaded_image = sb.upload_profile_image(profile_image, auth_user_id=user_id)
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("community.profile_page", tab="settings"))
        profile_image_url = str(uploaded_image.get("public_url") or "")

    updated = sb.upsert_user_account({
        "auth_user_id": user_id,
        "username": new_username,
        "display_name": display_name,
        "email": str(auth_user.get("email") or ""),
        "profile_image_url": profile_image_url or None,
        "avatar_url": profile_image_url or None,
        "is_admin": bool(auth_user.get("is_admin") or False),
    })
    if updated:
        login_user({
            "user_id": user_id,
            "email": str(updated.get("email") or ""),
            "username": str(updated.get("username") or ""),
            "display_name": str(updated.get("display_name") or ""),
            "profile_image_url": str(updated.get("profile_image_url") or updated.get("avatar_url") or profile_image_url or ""),
            "is_admin": bool(updated.get("is_admin") or False),
        })
        flash("Profile updated.", "success")
    else:
        flash("Could not update profile.", "error")
    return redirect(url_for("community.profile_page", tab="settings"))

