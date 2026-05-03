create table if not exists public.community_notifications (
    id uuid primary key default gen_random_uuid(),
    recipient_auth_user_id uuid not null,
    actor_auth_user_id uuid not null,
    actor_name text not null default 'Member',
    notification_type text not null,
    entity_type text not null,
    entity_id uuid not null,
    post_id uuid,
    message text not null,
    is_read boolean not null default false,
    created_at timestamptz not null default timezone('utc', now())
);

create table if not exists public.community_chat_channels (
    id uuid primary key default gen_random_uuid(),
    hub_id uuid not null references public.community_hubs(id) on delete cascade,
    slug text not null,
    name text not null,
    created_at timestamptz not null default timezone('utc', now()),
    unique (hub_id, slug)
);

create table if not exists public.community_chat_messages (
    id uuid primary key default gen_random_uuid(),
    channel_id uuid not null references public.community_chat_channels(id) on delete cascade,
    author_auth_user_id uuid not null,
    author_username text not null default '',
    author_display_name text not null default 'Member',
    body text not null,
    status text not null default 'active' check (status in ('active', 'hidden', 'deleted')),
    created_at timestamptz not null default timezone('utc', now())
);

create table if not exists public.community_conversations (
    id uuid primary key default gen_random_uuid(),
    created_at timestamptz not null default timezone('utc', now()),
    updated_at timestamptz not null default timezone('utc', now())
);

create table if not exists public.community_conversation_members (
    id uuid primary key default gen_random_uuid(),
    conversation_id uuid not null references public.community_conversations(id) on delete cascade,
    auth_user_id uuid not null,
    username text not null default '',
    display_name text not null default 'Member',
    joined_at timestamptz not null default timezone('utc', now()),
    unique (conversation_id, auth_user_id)
);

create table if not exists public.community_direct_messages (
    id uuid primary key default gen_random_uuid(),
    conversation_id uuid not null references public.community_conversations(id) on delete cascade,
    author_auth_user_id uuid not null,
    author_username text not null default '',
    author_display_name text not null default 'Member',
    body text not null,
    status text not null default 'active' check (status in ('active', 'hidden', 'deleted')),
    created_at timestamptz not null default timezone('utc', now())
);

create table if not exists public.community_reports (
    id uuid primary key default gen_random_uuid(),
    reporter_auth_user_id uuid not null,
    target_type text not null check (target_type in ('post', 'comment', 'chat_message', 'direct_message')),
    target_id uuid not null,
    reason text not null,
    status text not null default 'open' check (status in ('open', 'reviewed', 'closed')),
    created_at timestamptz not null default timezone('utc', now())
);

create index if not exists community_notifications_user_created_idx on public.community_notifications (recipient_auth_user_id, created_at desc);
create index if not exists community_chat_messages_channel_created_idx on public.community_chat_messages (channel_id, created_at desc);
create index if not exists community_dm_conversation_created_idx on public.community_direct_messages (conversation_id, created_at desc);
create index if not exists community_conversation_member_user_idx on public.community_conversation_members (auth_user_id, conversation_id);

alter table public.community_notifications enable row level security;
alter table public.community_chat_channels enable row level security;
alter table public.community_chat_messages enable row level security;
alter table public.community_conversations enable row level security;
alter table public.community_conversation_members enable row level security;
alter table public.community_direct_messages enable row level security;
alter table public.community_reports enable row level security;

drop policy if exists community_notifications_own on public.community_notifications;
create policy community_notifications_own on public.community_notifications for select to authenticated using (auth.uid() = recipient_auth_user_id);

drop policy if exists community_chat_channels_read on public.community_chat_channels;
create policy community_chat_channels_read on public.community_chat_channels for select to authenticated using (true);

drop policy if exists community_chat_messages_read on public.community_chat_messages;
create policy community_chat_messages_read on public.community_chat_messages for select to authenticated using (status <> 'deleted');

drop policy if exists community_conversation_members_own on public.community_conversation_members;
create policy community_conversation_members_own on public.community_conversation_members for select to authenticated using (auth.uid() = auth_user_id);

drop policy if exists community_conversations_members_only on public.community_conversations;
create policy community_conversations_members_only on public.community_conversations for select to authenticated using (
    exists (
        select 1
        from public.community_conversation_members members
        where members.conversation_id = community_conversations.id
          and members.auth_user_id = auth.uid()
    )
);

drop policy if exists community_direct_messages_members_only on public.community_direct_messages;
create policy community_direct_messages_members_only on public.community_direct_messages for select to authenticated using (
    exists (
        select 1
        from public.community_conversation_members members
        where members.conversation_id = community_direct_messages.conversation_id
          and members.auth_user_id = auth.uid()
    )
);
