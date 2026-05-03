insert into public.community_hubs (slug, name, description, sort_order)
values
    ('nhl', 'NHL', 'League-wide community threads, line combinations, roster moves, and nightly game chatter.', 1),
    ('pwhl', 'PWHL', 'Dedicated space for PWHL discussion, game reactions, roster news, and fan conversations.', 2),
    ('hockey-analytics', 'Hockey Analytics', 'Models, xG debates, public data, visualizations, and methodology breakdowns.', 3)
on conflict (slug) do update set
    name = excluded.name,
    description = excluded.description,
    sort_order = excluded.sort_order,
    is_active = true;

insert into public.community_chat_channels (hub_id, slug, name)
select hubs.id, 'general', 'General'
from public.community_hubs hubs
where hubs.slug in ('nhl', 'pwhl', 'hockey-analytics')
on conflict (hub_id, slug) do update set
    name = excluded.name;
