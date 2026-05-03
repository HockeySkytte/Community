create extension if not exists pgcrypto;

create table if not exists public.community_hubs (
    id uuid primary key default gen_random_uuid(),
    slug text not null unique,
    name text not null,
    description text not null default '',
    sort_order integer not null default 0,
    is_active boolean not null default true,
    created_at timestamptz not null default timezone('utc', now())
);

create table if not exists public.community_posts (
    id uuid primary key default gen_random_uuid(),
    hub_id uuid not null references public.community_hubs(id) on delete cascade,
    author_auth_user_id uuid not null,
    author_username text not null default '',
    author_display_name text not null default 'Member',
    title text not null,
    body text not null default '',
    video_url text,
    preview_image_url text,
    comment_count integer not null default 0,
    like_count integer not null default 0,
    dislike_count integer not null default 0,
    score integer not null default 0,
    status text not null default 'active' check (status in ('active', 'hidden', 'locked', 'deleted')),
    created_at timestamptz not null default timezone('utc', now()),
    updated_at timestamptz not null default timezone('utc', now()),
    last_activity_at timestamptz not null default timezone('utc', now())
);

create table if not exists public.community_post_media (
    id uuid primary key default gen_random_uuid(),
    post_id uuid not null references public.community_posts(id) on delete cascade,
    media_kind text not null check (media_kind in ('image', 'video')),
    storage_bucket text,
    storage_path text,
    public_url text not null,
    sort_order integer not null default 0,
    created_at timestamptz not null default timezone('utc', now())
);

create table if not exists public.community_comments (
    id uuid primary key default gen_random_uuid(),
    post_id uuid not null references public.community_posts(id) on delete cascade,
    parent_comment_id uuid references public.community_comments(id) on delete cascade,
    author_auth_user_id uuid not null,
    author_username text not null default '',
    author_display_name text not null default 'Member',
    body text not null,
    depth integer not null default 0,
    like_count integer not null default 0,
    dislike_count integer not null default 0,
    score integer not null default 0,
    status text not null default 'active' check (status in ('active', 'hidden', 'deleted')),
    created_at timestamptz not null default timezone('utc', now()),
    updated_at timestamptz not null default timezone('utc', now())
);

create table if not exists public.community_reactions (
    id uuid primary key default gen_random_uuid(),
    auth_user_id uuid not null,
    target_type text not null check (target_type in ('post', 'comment')),
    target_id uuid not null,
    vote_type text not null check (vote_type in ('like', 'dislike')),
    created_at timestamptz not null default timezone('utc', now()),
    updated_at timestamptz not null default timezone('utc', now()),
    unique (auth_user_id, target_type, target_id)
);

create index if not exists community_posts_hub_created_idx on public.community_posts (hub_id, created_at desc);
create index if not exists community_posts_hub_score_idx on public.community_posts (hub_id, score desc, created_at desc);
create index if not exists community_comments_post_created_idx on public.community_comments (post_id, created_at);
create index if not exists community_comments_parent_idx on public.community_comments (parent_comment_id);

alter table public.community_hubs enable row level security;
alter table public.community_posts enable row level security;
alter table public.community_post_media enable row level security;
alter table public.community_comments enable row level security;
alter table public.community_reactions enable row level security;

drop policy if exists community_hubs_read on public.community_hubs;
create policy community_hubs_read on public.community_hubs for select to authenticated using (true);

drop policy if exists community_posts_read on public.community_posts;
create policy community_posts_read on public.community_posts for select to authenticated using (status <> 'deleted');

drop policy if exists community_comments_read on public.community_comments;
create policy community_comments_read on public.community_comments for select to authenticated using (status <> 'deleted');

drop policy if exists community_post_media_read on public.community_post_media;
create policy community_post_media_read on public.community_post_media for select to authenticated using (true);

drop policy if exists community_reactions_read on public.community_reactions;
create policy community_reactions_read on public.community_reactions for select to authenticated using (auth.uid() = auth_user_id);

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
    'community-media',
    'community-media',
    true,
    10485760,
    array['image/png', 'image/jpeg', 'image/webp', 'image/gif']
)
on conflict (id) do update set
    public = excluded.public,
    file_size_limit = excluded.file_size_limit,
    allowed_mime_types = excluded.allowed_mime_types;
