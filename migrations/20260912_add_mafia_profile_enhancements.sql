alter table public.mafia_players
  add column if not exists gender text;

alter table public.mafia_players
  drop constraint if exists mafia_players_gender_check;

alter table public.mafia_players
  add constraint mafia_players_gender_check
  check (gender is null or gender in ('male','female'));

create table if not exists public.mafia_account_transfers (
  id uuid primary key default gen_random_uuid(),
  source_user_id bigint not null,
  target_user_id bigint not null,
  actor_user_id bigint not null,
  group_chat_id bigint null,
  created_at timestamptz not null default now(),
  constraint mafia_account_transfers_source_target_check check (source_user_id <> target_user_id)
);

create index if not exists idx_mafia_account_transfers_source on public.mafia_account_transfers(source_user_id);
create index if not exists idx_mafia_account_transfers_target on public.mafia_account_transfers(target_user_id);
create index if not exists idx_mafia_account_transfers_created_at on public.mafia_account_transfers(created_at desc);
