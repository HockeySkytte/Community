alter table if exists public.user_accounts
    add column if not exists community_banned_until timestamptz,
    add column if not exists community_ban_reason text,
    add column if not exists community_banned_by uuid;

create index if not exists user_accounts_community_banned_until_idx
    on public.user_accounts (community_banned_until);
