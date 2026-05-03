create extension if not exists pgcrypto;

create table if not exists public.community_post_events (
    id uuid primary key default gen_random_uuid(),
    post_id uuid not null references public.community_posts(id) on delete cascade,
    actor_auth_user_id uuid,
    event_type text not null check (event_type in ('view', 'share')),
    created_at timestamptz not null default timezone('utc', now())
);

create index if not exists community_post_events_post_created_idx on public.community_post_events (post_id, created_at);
create index if not exists community_post_events_post_type_created_idx on public.community_post_events (post_id, event_type, created_at);

alter table public.community_post_events enable row level security;

drop policy if exists community_post_events_read on public.community_post_events;
create policy community_post_events_read on public.community_post_events for select to authenticated using (true);
