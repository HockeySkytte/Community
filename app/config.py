from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


load_dotenv(Path(__file__).resolve().parents[1] / ".env")


class Config:
    DEBUG = os.environ.get("FLASK_DEBUG", "0") == "1"
    SECRET_KEY = os.environ.get("SECRET_KEY") or "community-dev-secret"
    APP_BASE_URL = os.environ.get("APP_BASE_URL") or "http://localhost:5000"
    SUPABASE_URL = os.environ.get("SUPABASE_URL") or ""
    SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY") or ""
    SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY") or ""
    COMMUNITY_MEDIA_BUCKET = os.environ.get("COMMUNITY_MEDIA_BUCKET") or "community-media"
    COMMUNITY_IMAGE_MAX_BYTES = int(os.environ.get("COMMUNITY_IMAGE_MAX_BYTES") or 10 * 1024 * 1024)
    MAX_CONTENT_LENGTH = int(os.environ.get("MAX_CONTENT_LENGTH") or 32 * 1024 * 1024)
    POST_PREVIEW_LIMIT = int(os.environ.get("POST_PREVIEW_LIMIT") or 12)
    CHAT_MESSAGE_LIMIT = int(os.environ.get("CHAT_MESSAGE_LIMIT") or 120)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "0") == "1"
    GA_MEASUREMENT_ID = os.environ.get("GA_MEASUREMENT_ID") or ""
