create table if not exists public.mafia_profile_settings (
  user_id bigint primary key references public.mafia_players(id) on delete cascade,
  visibility text not null default 'public' check (visibility in ('public','basic','private')),
  show_gender boolean not null default true,
  show_nickname boolean not null default true,
  show_stats boolean not null default true,
  show_history boolean not null default false,
  show_roles boolean not null default false,
  show_group_stats boolean not null default false,
  updated_at timestamptz not null default now()
);
create index if not exists mafia_profile_settings_visibility_idx on public.mafia_profile_settings(visibility);
insert into public.mafia_profile_settings(user_id)
select id from public.mafia_players
on conflict (user_id) do nothing;
update public.mafia_scenarios
set config = (config - 'sides') || jsonb_build_object('sides', (
  select coalesce(jsonb_object_agg(k,v), '{}'::jsonb)
  from jsonb_each(coalesce(config->'sides','{}'::jsonb)) e(k,v)
  where k <> 'نوفیس'
))
where name = 'کلاسیک 12';
update public.mafia_scenarios
set config = jsonb_set(coalesce(config,'{}'::jsonb), '{sides,نوفیس}', '"مستقل"'::jsonb, true)
where name = 'کلاسیک 13' and roles @> '["نوفیس"]'::jsonb;
