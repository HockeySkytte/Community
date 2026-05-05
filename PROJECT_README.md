# Hockey Community Platform - Project Documentation

## Table of Contents
1. [Project Overview](#project-overview)
2. [Architecture](#architecture)
3. [Key Features](#key-features)
4. [Project Structure](#project-structure)
5. [Core Components](#core-components)
6. [Database Schema](#database-schema)
7. [API Endpoints](#api-endpoints)
8. [Environment Setup](#environment-setup)
9. [Deployment](#deployment)
10. [Known Issues & Solutions](#known-issues--solutions)
11. [Development Guidelines](#development-guidelines)

---

## Project Overview

**Hockey Community** is a public, fan-driven discussion platform for hockey enthusiasts. The platform enables fans to:
- **Read publicly** without login (view hubs, posts, and comments)
- **Participate with login** (create posts, comment, vote on reactions)
- **Organize by hubs** (NHL, PWHL, Analytics) for focused discussions
- **Share on social media** with rich preview images (OG tags)
- **Track engagement** with post reactions, views, and shares

**Live site**: https://community.hockey-statistics.com/

**Target users**: NHL/PWHL fans, hockey analysts, casual and hardcore fans discussing games, signings, trades, and statistics.

---

## Architecture

### Tech Stack
- **Frontend**: Jinja2 templates, vanilla JavaScript, CSS3 (responsive design)
- **Backend**: Flask 3.1 (Python), app factory pattern
- **Database**: Supabase (PostgreSQL) with shared auth via `user_accounts` table
- **Authentication**: Supabase Auth + custom session handling via `auth_helpers.py`
- **File uploads**: Supabase Storage bucket for images
- **Deployment**: Render (Linux), Gunicorn WSGI server, Cloudflare proxy
- **Analytics**: Google Analytics (GA4) with measurement ID injection
- **CDN/SSL**: Cloudflare (Full Strict SSL)

### High-Level Flow
```
User → Cloudflare → Render (Gunicorn) → Flask App → Supabase (Auth + DB + Storage)
                                             ↓
                                    Google Analytics (async)
```

### Key Design Decisions
1. **Public read, auth-write model**: GET routes for browsing are public; POST/PUT/DELETE require login
2. **No login for browsing**: Reduces friction for discovery; login prompt appears when user tries to post/vote
3. **Rich text editor in browser**: BBCode tokens stored in DB; rendered to HTML on page load
4. **Inline image support**: Images embedded as `[image=URL]` tokens; rendered inline with inline media blocks
5. **Nested comments**: Comments can have `parent_comment_id`; displayed as tree structure
6. **Reactions API**: Separate `/api/reactions` endpoint for like/dislike (view-agnostic)
7. **Post preview image**: Automatically uses first uploaded image as social media thumbnail; user can override

---

## Key Features

### 1. **Hubs (Topic Areas)**
- **Types**: NHL, PWHL, Analytics
- **Data**: Slug, name, description, icon, external site URL
- **Location**: Database table `hubs`; managed server-side
- **UI**: [hub.html](app/templates/hub.html) displays hub feed with sorting (new, top, my posts)

### 2. **Posts**
- **Creation**: Title, body (rich text), optional video URL, optional thumbnail image, media attachments
- **Body format**: BBCode tokens (`[b]`, `[i]`, `[image=URL]`, `[[image]]`)
- **Rendering**: HTML with inline media blocks and video embeds
- **Auto-thumbnail**: First uploaded image becomes thumbnail if no explicit thumbnail provided
- **Preview**: 220-char plain-text excerpt for feed cards and meta descriptions
- **Metadata**: Author, created/updated timestamps, hub slug
- **Interactions**: Score (reactions), comment count, view count, share count
- **Database**: `posts`, `post_media`, `post_reactions`, `post_events` tables

### 3. **Comments**
- **Nesting**: Replies can target parent comment via `parent_comment_id`
- **Rich text**: Same BBCode support as posts
- **Reactions**: Like/dislike on comments (same API)
- **Tree display**: Recursively rendered in template with depth-based indentation
- **Location**: [post_detail.html](app/templates/post_detail.html) renders comment tree
- **Database**: `comments`, `comment_reactions` tables

### 4. **Reactions (Votes)**
- **Types**: Like (upvote), Dislike (downvote)
- **Targets**: Posts and comments
- **API**: `POST /api/reactions` (auth-required)
- **Score calculation**: Like = +1, Dislike = -1; aggregate stored in post/comment record
- **UI**: Vote buttons visible to logged-in users; guests see "Log in to vote" link
- **Tracking**: Reactions tracked in `post_reactions` and `comment_reactions` tables

### 5. **Post Insights**
- **Endpoint**: `GET /posts/<post_id>/insights` (auth-required, author-only)
- **Metrics**: View count, share count, comment count, top reactions
- **UI**: [post_insights.html](app/templates/post_insights.html)
- **Time ranges**: 24h, 7d, 30d, 90d, all-time
- **Chart data**: Cumulative view count over time
- **Database**: `post_events` table tracks view, share, comment creation events

### 6. **Social Media Previews**
- **OG Tags**: Post-specific Open Graph tags in [post_detail.html](app/templates/post_detail.html)
  - `og:title` → Post title
  - `og:description` → Post preview (first 200 chars)
  - `og:image` → Thumbnail URL or app logo fallback
  - `og:url` → Share URL (canonical)
- **Twitter Cards**: `twitter:card`, `twitter:title`, `twitter:description`, `twitter:image`
- **Fallback**: If no thumbnail, uses app logo (`static/logo.png`)
- **Format validation**: Images must be publicly accessible URLs
- **Testing**: Use Facebook Share Debugger or Twitter Card Validator to verify

### 7. **Rich Text Editor**
- **Location**: [community.js](app/static/community.js) - `editorToMarkup()` and related functions
- **Toolbar**: Bold, Italic, Underline, Strikethrough, Link, Clear formatting, Font selection, Size, Color
- **Inline images**: Paste/insert images; renders as `[image=URL]` tokens
- **Image management**: Drag-to-reorder, remove button for each inline image
- **Video embeds**: YouTube, Vimeo, Loom URLs on own line auto-embed
- **Draft auto-save**: Saves to browser localStorage by hub/post type
- **Submit conversion**: `syncEditorToTextarea()` converts editor HTML → BBCode markup

### 8. **Google Analytics**
- **Measurement ID**: Loaded from `GA_MEASUREMENT_ID` config
- **Tracking**: Global gtag script in [base.html](app/templates/base.html)
- **Events**: Page views tracked automatically; custom share events via `sharePost()` in JS
- **Dashboard**: https://analytics.google.com/ (admin only)

### 9. **User Bans**
- **Database**: `community_bans` table
- **Check**: `_ensure_can_participate()` in [community.py](app/routes/community.py)
- **UI**: Flash message showing ban reason and end date
- **Scope**: Prevents posting and commenting during ban period

### 10. **Notifications**
- **Trigger**: Comment reply, post mention, reaction on user's post
- **Database**: `notifications` table with `user_id`, `notification_type`, `related_id`
- **Unread count**: Cached in context and injected into all templates
- **Mark-read**: `POST /notifications/mark-read` (auto-read on click)
- **UI**: Notification bell with count in TopNav; listing page at `/notifications`

---

## Project Structure

```
c:\Apps\Community/
│
├── app/                              # Flask application package
│   ├── __init__.py                   # App factory, blueprint registration, context injection
│   ├── auth_helpers.py               # Authentication decorators, session management
│   ├── config.py                     # Configuration (env vars, constants)
│   ├── supabase_client.py            # Database layer (all Supabase queries)
│   │
│   ├── routes/                       # Blueprint route handlers
│   │   ├── auth.py                   # Login, signup, logout routes
│   │   └── community.py              # All community endpoints (posts, comments, reactions, etc.)
│   │
│   ├── templates/                    # Jinja2 templates
│   │   ├── base.html                 # Site-wide layout (header, nav, GA tracking, favicon)
│   │   ├── home.html                 # Landing page with hub cards and latest feed
│   │   ├── hub.html                  # Hub-specific feed with sorting/search
│   │   ├── create_post.html          # Post creation form (rich editor, image upload, thumbnail)
│   │   ├── edit_post.html            # Post editing form
│   │   ├── post_detail.html          # Single post view with comments, OG meta tags
│   │   ├── post_insights.html        # Post analytics/engagement dashboard
│   │   ├── login.html                # Login page
│   │   ├── signup.html               # Signup page
│   │   ├── profile.html              # User profile page
│   │   ├── notifications.html        # Notifications listing
│   │   ├── messages.html             # Direct messages (optional feature)
│   │   ├── hub_chat.html             # Hub-wide chat (optional feature)
│   │   └── admin_community_bans.html # Admin ban management
│   │
│   └── static/                       # Client-side assets
│       ├── community.js              # Rich editor, reactions, sharing, draft auto-save
│       ├── community.css             # Styling for posts, comments, editor
│       └── logo.png                  # App logo (favicon + OG fallback image)
│
├── tests/                            # Pytest test suite
│   └── test_smoke_app.py             # Smoke tests (health check, home redirect, auth flow)
│
├── supabase/                         # Supabase setup docs (optional)
│   └── migrations/                   # Database migrations (if versioning schema)
│
├── run.py                            # Entry point for local dev (flask run)
├── requirements.txt                  # Python dependencies
├── .env                              # Environment variables (NOT in git)
├── .env.example                      # Template for .env
├── .gitignore                        # Git ignore rules
├── Procfile                          # Render deployment config (optional, uses Start Command)
└── PROJECT_README.md                 # This file
```

### File Organization by Feature

#### **Posts Feature**
- Create/edit: [create_post.html](app/templates/create_post.html), [edit_post.html](app/templates/edit_post.html)
- Display: [post_detail.html](app/templates/post_detail.html), [hub.html](app/templates/hub.html)
- Backend: `create_post()`, `update_post()`, `delete_post()` in [community.py](app/routes/community.py)
- DB layer: `create_post()`, `update_post()`, `get_post()` in [supabase_client.py](app/supabase_client.py)

#### **Comments Feature**
- Display: Comment macro in [post_detail.html](app/templates/post_detail.html)
- Backend: `add_comment()`, `delete_comment()` in [community.py](app/routes/community.py)
- DB layer: `create_comment()`, `list_comments()`, `get_comment()` in [supabase_client.py](app/supabase_client.py)

#### **Reactions Feature**
- UI: Reaction buttons in [post_detail.html](app/templates/post_detail.html), [hub.html](app/templates/hub.html), [home.html](app/templates/home.html)
- Backend: `POST /api/reactions` in [community.py](app/routes/community.py)
- JS handler: `setReaction()` in [community.js](app/static/community.js)
- DB layer: `set_reaction()`, `get_user_reaction()` in [supabase_client.py](app/supabase_client.py)

#### **Rich Text Editor**
- Templates: [create_post.html](app/templates/create_post.html), comment composer in [post_detail.html](app/templates/post_detail.html)
- JS: `editorToMarkup()`, `insertHtmlAtCursor()`, `buildReviewHtml()` in [community.js](app/static/community.js)
- Rendering: `_render_post_body_html()`, `_render_rich_text_html()` in [community.py](app/routes/community.py)

#### **Image Upload & Inline Media**
- UI: File input in [create_post.html](app/templates/create_post.html), inline image management in [community.js](app/static/community.js)
- Backend: `upload_post_image()` in [supabase_client.py](app/supabase_client.py)
- Storage: Supabase Storage bucket `community-media`
- Thumbnail auto-selection: Logic in `create_post()` (if no explicit thumbnail, use first uploaded image)

#### **Post Insights**
- UI: [post_insights.html](app/templates/post_insights.html)
- Backend: `GET /posts/<post_id>/insights` in [community.py](app/routes/community.py)
- DB: `list_post_events()` in [supabase_client.py](app/supabase_client.py)
- Chart data: `_build_cumulative_view_points()` in [community.py](app/routes/community.py)

#### **Social Media Previews**
- OG tags: [post_detail.html](app/templates/post_detail.html) `{% block seo_meta %}`
- Base meta: [base.html](app/templates/base.html)
- Thumbnail: Auto-set on post creation; user can override in form

---

## Core Components

### 1. **Authentication (`auth_helpers.py`)**
```python
@login_required  # Decorator: aborts 401 if not logged in
@require_csrf()  # CSRF token validation for POST/PUT/DELETE
get_current_user()  # Returns session user dict or None
login_user(user_dict)  # Sets session
logout_user()  # Clears session
ensure_csrf_token()  # Creates/retrieves CSRF token
```
- **Session key**: `auth_user` in Flask session
- **CSRF**: Token in hidden form field, validated on POST/PUT/DELETE

### 2. **Database Layer (`supabase_client.py`)**
Wraps Supabase client with helper functions:
- **Posts**: `create_post()`, `get_post()`, `update_post()`, `list_posts()`, `delete_post()`
- **Comments**: `create_comment()`, `get_comment()`, `list_comments()`, `delete_comment()`
- **Reactions**: `set_reaction()`, `get_user_reaction()`, `get_post_reactions()`
- **Media**: `upload_post_image()`, `get_post_media()`, `add_post_media()`
- **Insights**: `track_post_event()`, `list_post_events()`
- **Users**: `get_user()`, `list_users()`
- **Bans**: `get_active_community_ban()`, `create_ban()`, `remove_ban()`

### 3. **Community Routes (`routes/community.py`)**
- **Main routes**: Home, hubs, post creation, post detail, comment creation
- **API routes**: Reactions, post share tracking
- **Helper functions**:
  - `_decorate_post()` → Enriches post with HTML rendering, preview, share URL
  - `_build_comment_tree()` → Recursively nests comments by parent_comment_id
  - `_has_inline_image_tokens()` → Detects `[image=URL]` and `[[image]]` tokens
  - `_render_post_body_html()` → Converts BBCode tokens to HTML
  - `_ensure_can_participate()` → Checks user ban status

### 4. **Rich Text Rendering Pipeline**
```
User input (HTML from contenteditable) 
→ editorToMarkup() (JS)
→ BBCode tokens stored in DB
→ _render_post_body_html() (Python)
→ HTML with inline media blocks
→ Rendered in post_detail.html
```

---

## Database Schema

### Tables

#### **hubs**
- `id` (uuid, PK)
- `slug` (text, unique) - e.g., "nhl", "pwhl", "analytics"
- `name` (text) - e.g., "NHL Discussions"
- `description` (text)
- `icon_url` (text)
- `created_at` (timestamp)

#### **posts**
- `id` (uuid, PK)
- `hub_id` (uuid, FK → hubs)
- `author_auth_user_id` (uuid, FK → user_accounts)
- `author_username` (text) - denormalized for display
- `author_display_name` (text) - denormalized for display
- `title` (text)
- `body` (text) - BBCode tokens
- `video_url` (text)
- `preview_image_url` (text) - URL to thumbnail for social media
- `score` (integer) - aggregate reaction score
- `comment_count` (integer) - denormalized comment count
- `view_count` (integer) - denormalized view count
- `share_count` (integer) - denormalized share count
- `created_at` (timestamp)
- `updated_at` (timestamp)
- `deleted_at` (timestamp, nullable) - soft delete

#### **post_media**
- `id` (uuid, PK)
- `post_id` (uuid, FK → posts)
- `media_url` (text)
- `media_type` (text) - "image", "video"
- `public_url` (text) - Supabase Storage public URL
- `created_at` (timestamp)

#### **comments**
- `id` (uuid, PK)
- `post_id` (uuid, FK → posts)
- `parent_comment_id` (uuid, FK → comments, nullable) - for nesting
- `author_auth_user_id` (uuid, FK → user_accounts)
- `author_username` (text) - denormalized
- `author_display_name` (text) - denormalized
- `body` (text) - BBCode tokens
- `score` (integer) - aggregate reaction score
- `created_at` (timestamp)
- `updated_at` (timestamp)
- `deleted_at` (timestamp, nullable) - soft delete

#### **post_reactions**
- `id` (uuid, PK)
- `post_id` (uuid, FK → posts)
- `user_id` (uuid, FK → user_accounts)
- `vote_type` (text) - "like" or "dislike"
- `created_at` (timestamp)

#### **comment_reactions**
- `id` (uuid, PK)
- `comment_id` (uuid, FK → comments)
- `user_id` (uuid, FK → user_accounts)
- `vote_type` (text) - "like" or "dislike"
- `created_at` (timestamp)

#### **post_events**
- `id` (uuid, PK)
- `post_id` (uuid, FK → posts)
- `event_type` (text) - "view", "share", "comment_created"
- `auth_user_id` (uuid, nullable) - who triggered event
- `created_at` (timestamp)

#### **notifications**
- `id` (uuid, PK)
- `user_id` (uuid, FK → user_accounts)
- `notification_type` (text) - "comment_reply", "mention", "reaction"
- `related_id` (uuid) - post_id, comment_id, etc.
- `message` (text)
- `read_at` (timestamp, nullable)
- `created_at` (timestamp)

#### **community_bans**
- `id` (uuid, PK)
- `user_id` (uuid, FK → user_accounts)
- `reason` (text)
- `until` (timestamp)
- `created_at` (timestamp)

---

## API Endpoints

### **Public (No Auth Required)**

#### Home & Browsing
- `GET /` → Redirect to `/home`
- `GET /home` → Home page with hubs and latest posts
- `GET /hubs/<hub_slug>` → Hub feed with sorting (new, top, my posts) and search
- `GET /hubs/<hub_slug>/posts/new` → New post creation page
- `GET /posts/<post_id>` → Single post view with comment tree

#### Post Insights (Author Only)
- `GET /posts/<post_id>/insights` → Post analytics dashboard (view, share, comment trends)

#### Notifications
- `GET /notifications` → User's notification list
- `GET /notifications/<notification_id>/open` → Mark notification as read (redirect to related resource)

### **Auth Required (Login)**

#### Post Management
- `POST /hubs/<hub_slug>/posts` → Create post
  - Form fields: `title`, `body`, `video_url`, `thumbnail` (file), `images` (files)
  - Response: Redirect to post detail
  - Thumbnail auto-select: If no explicit thumbnail, uses first uploaded image

- `GET /posts/<post_id>/edit` → Edit post page (author only)
- `POST /posts/<post_id>/edit` → Update post (author only)
- `POST /posts/<post_id>/delete` → Soft-delete post (author + admin)

#### Comments
- `POST /posts/<post_id>/comments` → Add comment to post
  - Form fields: `body`, `parent_comment_id` (optional), `images` (files)
  - Response: Redirect to post detail + anchor to comment
- `POST /comments/<comment_id>/delete` → Soft-delete comment (author + admin)

#### Reactions
- `POST /api/reactions` (JSON)
  - Payload: `{ "target_id": "...", "target_type": "post|comment", "vote_type": "like|dislike" }`
  - Response: `{ "score": 42, "user_vote": "like" | "dislike" | null }`
  - Logic: Toggle vote; e.g., like again = remove like

#### Post Events (Tracking)
- `POST /api/posts/<post_id>/share` → Track share event
  - Response: `{ "share_count": 5 }`

#### Notifications
- `POST /notifications/mark-read` → Mark all unread as read
  - Response: Redirect to referring page

#### Chat (Optional Feature)
- `GET /chat/<hub_slug>` → Hub chat page
- `GET /api/chat/<hub_slug>/messages` → Get recent messages (JSON)
- `POST /api/chat/<hub_slug>/messages` → Send chat message (JSON)

### **Auth Routes** (separate blueprint)
- `GET /login` → Login page
- `POST /login` → Process login (email + password)
- `GET /signup` → Signup page
- `POST /signup` → Create account (email + password + username + display name)
- `POST /logout` → Clear session and logout

---

## Environment Setup

### Required Environment Variables

Create `.env` file in project root:

```bash
# Flask / Core
FLASK_DEBUG=0  # 1 for development, 0 for production
SECRET_KEY=your-secret-key-here  # For session signing
APP_BASE_URL=https://community.hockey-statistics.com  # For OG tags and share URLs

# Supabase
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your-anon-key
SUPABASE_SERVICE_KEY=your-service-key  # For admin operations

# Storage
COMMUNITY_MEDIA_BUCKET=community-media
COMMUNITY_IMAGE_MAX_BYTES=10485760  # 10 MB
MAX_CONTENT_LENGTH=33554432  # 32 MB (max request size)

# Feature Limits
POST_PREVIEW_LIMIT=12  # Posts per page on hub feed
CHAT_MESSAGE_LIMIT=120  # Messages to load in chat

# Analytics
GA_MEASUREMENT_ID=G-LQY14MGCDV  # Google Analytics measurement ID

# SSL/Security
SESSION_COOKIE_SECURE=1  # HTTPS only (set to 1 in production)
```

### Local Development Setup

1. **Create virtual environment**:
   ```bash
   python -m venv .venv
   .venv\Scripts\activate  # Windows
   source .venv/bin/activate  # Linux/Mac
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Create `.env` file** with Supabase credentials

4. **Run local server**:
   ```bash
   flask run
   # App will be at http://localhost:5000
   ```

5. **Run tests**:
   ```bash
   pytest tests/
   ```

### Dependencies
- **Flask 3.1** - Web framework
- **python-dotenv** - Environment variable management
- **supabase** - Database, auth, and storage client
- **gunicorn** - WSGI server for production
- **pytest** - Test framework

---

## Deployment

### Render Deployment

The app is deployed to Render with these settings:

**Service**: Web Service (Python)
**Build command**: `pip install -r requirements.txt`
**Start command**: `gunicorn --bind 0.0.0.0:$PORT run:app`
**Environment variables**: All `.env` values set in Render dashboard

### How It Works
1. Push to git repo (GitHub)
2. Render detects push and triggers build
3. Installs requirements and runs gunicorn
4. App listens on `0.0.0.0:$PORT` (Render assigns dynamic port)
5. Cloudflare proxy routes traffic from domain to Render

### Cloudflare Configuration

**DNS**: A record pointing to Render app URL
**SSL**: Full Strict (HTTPS enforced)
**Security**: 
- Disable aggressive rate limiting (can cause 524 errors)
- Exclude `/health` endpoint from challenges
- Consider disabling/excluding privacy rules if causing issues

### Production Considerations

1. **Cold starts**: Render free tier puts apps to sleep after 15 min of inactivity
   - Solution: Use paid "Standard" plan or set up uptime monitor to ping `/health` every 10 min

2. **SSL certificates**: Let Render handle auto-renewal; Cloudflare should not issue duplicate cert

3. **Database backups**: Supabase auto-backups daily (included in free tier)

4. **Error monitoring**: Check Render logs via dashboard for 5xx errors

5. **Performance**: Use Cloudflare page rules to cache static assets (CSS, JS, images)

---

## Known Issues & Solutions

### Issue: Intermittent 524 Errors (Cloudflare)
**Symptom**: Random 524 Gateway Timeout errors
**Root causes**:
1. Render cold start (instance sleeps, first request slow)
2. Cloudflare aggressive security/rate limiting
3. Slow database queries

**Solutions**:
- Disable CF "Under Attack Mode" and aggressive security rules
- Exclude `/health` endpoint from challenges
- Set up monitoring to ping `/health` every 10 minutes (keeps instance warm)
- Review Render logs for slow requests
- Consider upgrading to Render Standard plan (prevents cold starts)

### Issue: Favicon Not Showing on Linux
**Symptom**: No favicon on Linux (Render), works locally on Windows
**Root cause**: Linux filesystem case-sensitive; references to `Logo.png` but file is `logo.png`
**Solution**: 
- Rename file to lowercase `logo.png`
- Update all references to lowercase in code (done in `app/__init__.py`, templates, CSS)
- Cache-bust in JS imports

### Issue: OG:image Not Rendering in Social Media
**Symptom**: Posts shared on social media don't show thumbnail image
**Possible causes**:
1. No thumbnail uploaded; needs to be explicitly set or auto-extracted
2. Image URL not publicly accessible
3. Meta tags not in page before social media crawler visits (some crawlers are fast, some slow)

**Solution** (implemented):
- Auto-select first uploaded image as thumbnail if no explicit thumbnail provided
- Ensure all thumbnails are stored in public Supabase bucket with public URL
- Add cache headers to Cloudflare for OG image URLs

**Testing**:
- Use Facebook Share Debugger: https://developers.facebook.com/tools/debug/sharing/
- Use Twitter Card Validator: https://cards-dev.twitter.com/validator
- Check meta tags in page source (browser Dev Tools → Elements)

### Issue: Edit Post Loses Images
**Symptom**: Editing post removes inline images
**Root cause**: Edit form doesn't pre-populate editor with existing images
**Solution**: Edit form can add new images but doesn't remove old ones (preserve on update if not explicitly deleted)

### Issue: Comments Not Nesting Correctly
**Symptom**: Replies showing at root level, not nested
**Root cause**: `parent_comment_id` not being set in form
**Solution**: Comment form includes hidden field `parent_comment_id`; JavaScript confirms it's set before submit

---

## Development Guidelines

### Adding New Features

1. **Backend**: Add route in `routes/community.py` or new blueprint
2. **DB layer**: Add helper function in `supabase_client.py`
3. **Template**: Create/modify Jinja2 template in `app/templates/`
4. **Frontend**: Add JavaScript/CSS in `app/static/`
5. **Tests**: Add test case in `tests/`
6. **Env config**: Add to `config.py` and `.env.example` if needed

### Code Style

- **Python**: PEP 8, type hints for function signatures
- **JavaScript**: Vanilla JS (no frameworks), prefer data attributes for element targeting
- **CSS**: BEM-like naming (e.g., `.composer-field`, `.section-heading`)
- **Jinja2**: Use template inheritance (`extends` and `block`), avoid complex logic in templates

### Testing

```bash
pytest tests/  # Run all tests
pytest tests/test_smoke_app.py -v  # Run specific test file with verbose output
```

Current test coverage: Smoke tests for health check, home redirect, auth flow.

### Debugging

1. **Local dev**: Set `FLASK_DEBUG=1` to enable reloader and debugger
2. **Render logs**: Check real-time logs in Render dashboard
3. **Database**: Use Supabase dashboard to query/inspect tables
4. **Client-side**: Browser Dev Tools console for JS errors
5. **Network**: Dev Tools Network tab to check API responses

### Common Tasks

#### Add a new hub
1. Insert row into `hubs` table in Supabase dashboard
2. Slugs are used in URLs, so should be short and unique (e.g., "nhl", "pwhl")

#### Migrate a post
1. Update `hub_id` in `posts` table
2. Cascade updates to reactions/comments if needed

#### Ban a user
1. Insert row into `community_bans` with `user_id`, `reason`, `until` date
2. User will see ban message on next attempt to post/comment

#### Clear image cache
1. In Cloudflare dashboard, set page rule to bypass cache for `/static/`
2. Or increase cache-bust token in `community.js` and HTML

---

## Quick Links

- **Live site**: https://community.hockey-statistics.com/
- **Supabase dashboard**: https://app.supabase.com/
- **Render dashboard**: https://dashboard.render.com/
- **Cloudflare dashboard**: https://dash.cloudflare.com/
- **Google Analytics**: https://analytics.google.com/
- **Git repository**: (Your GitHub URL)

---

## Contact & Support

For questions or issues:
- Check this documentation first
- Review recent changes in git log
- Search existing issues in GitHub
- Contact project owner for access/credentials

---

*Last updated: May 5, 2026*
*Project version: 1.0.0 (Deployed to production)*
