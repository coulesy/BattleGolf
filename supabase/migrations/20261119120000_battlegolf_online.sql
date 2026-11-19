-- BattleGolf online matches (play your own round, compare scores).
-- Run once in the Supabase SQL editor of the BattleGolf project.
--
-- No accounts: each player's phone makes a random secret when it creates or joins a match.
-- Anyone with the app can read matches (that is how everyone watches the round), but the only
-- way to write is through the three functions below, and adding a shot needs that player's secret.

create table public.bg_matches (
  id         uuid primary key default gen_random_uuid(),
  code       text not null unique check (code ~ '^[A-Z2-9]{5}$'),
  hole       text not null default 'abbey-hill-13',
  created_at timestamptz not null default now()
);

create table public.bg_players (
  id         uuid primary key default gen_random_uuid(),
  match_id   uuid not null references public.bg_matches (id) on delete cascade,
  seat       smallint not null check (seat between 0 and 3),
  name       text not null check (char_length(name) between 1 and 16),
  created_at timestamptz not null default now(),
  unique (match_id, seat)
);
create index bg_players_match_idx on public.bg_players (match_id);

-- kept apart from bg_players so it can never be read or sent out over realtime
create table public.bg_player_secrets (
  player_id uuid primary key references public.bg_players (id) on delete cascade,
  secret    uuid not null
);

create table public.bg_shots (
  id         bigint generated always as identity primary key,
  match_id   uuid not null references public.bg_matches (id) on delete cascade,
  player_id  uuid not null references public.bg_players (id) on delete cascade,
  n          smallint not null check (n between 1 and 99),   -- the player's shot number
  data       jsonb not null check (pg_column_size(data) < 4000),
  created_at timestamptz not null default now(),
  unique (player_id, n)
);
create index bg_shots_match_idx on public.bg_shots (match_id);

-- read-only to the app; writes go through the functions
alter table public.bg_matches        enable row level security;
alter table public.bg_players        enable row level security;
alter table public.bg_player_secrets enable row level security;
alter table public.bg_shots          enable row level security;

create policy "anyone can read matches" on public.bg_matches for select to anon, authenticated using (true);
create policy "anyone can read players" on public.bg_players for select to anon, authenticated using (true);
create policy "anyone can read shots"   on public.bg_shots   for select to anon, authenticated using (true);

revoke all on public.bg_player_secrets from anon, authenticated;
revoke insert, update, delete, truncate on public.bg_matches, public.bg_players, public.bg_shots from anon, authenticated;

-- new match: returns its code and the creator's player id (seat 0)
create function public.bg_create_match(p_name text, p_secret uuid)
returns json language plpgsql security definer set search_path = public as $$
declare
  v_match uuid; v_code text; v_player uuid; v_name text := left(btrim(coalesce(p_name, '')), 16);
  alphabet constant text := 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
begin
  if v_name = '' then raise exception 'name required'; end if;
  if p_secret is null then raise exception 'secret required'; end if;
  loop
    v_code := '';
    for i in 1..5 loop
      v_code := v_code || substr(alphabet, 1 + floor(random() * length(alphabet))::int, 1);
    end loop;
    begin
      insert into bg_matches (code) values (v_code) returning id into v_match;
      exit;
    exception when unique_violation then
      -- code already taken: try another
    end;
  end loop;
  insert into bg_players (match_id, seat, name) values (v_match, 0, v_name) returning id into v_player;
  insert into bg_player_secrets (player_id, secret) values (v_player, p_secret);
  return json_build_object('match_id', v_match, 'code', v_code, 'player_id', v_player, 'seat', 0);
end $$;

-- join by code: takes the lowest free seat, up to 4 players
create function public.bg_join_match(p_code text, p_name text, p_secret uuid)
returns json language plpgsql security definer set search_path = public as $$
declare
  v_match uuid; v_seat int; v_player uuid; v_name text := left(btrim(coalesce(p_name, '')), 16);
begin
  if v_name = '' then raise exception 'name required'; end if;
  if p_secret is null then raise exception 'secret required'; end if;
  select id into v_match from bg_matches where code = upper(btrim(p_code)) for update;
  if v_match is null then raise exception 'match not found'; end if;
  select s into v_seat from generate_series(0, 3) s
    where not exists (select 1 from bg_players p where p.match_id = v_match and p.seat = s)
    order by s limit 1;
  if v_seat is null then raise exception 'match is full'; end if;
  insert into bg_players (match_id, seat, name) values (v_match, v_seat, v_name) returning id into v_player;
  insert into bg_player_secrets (player_id, secret) values (v_player, p_secret);
  return json_build_object('match_id', v_match, 'code', upper(btrim(p_code)), 'player_id', v_player, 'seat', v_seat);
end $$;

-- record one of your shots (needs your secret); sending the same shot twice is harmless
create function public.bg_add_shot(p_player uuid, p_secret uuid, p_n int, p_data jsonb)
returns void language plpgsql security definer set search_path = public as $$
declare v_match uuid;
begin
  select p.match_id into v_match
    from bg_players p join bg_player_secrets s on s.player_id = p.id
    where p.id = p_player and s.secret = p_secret;
  if v_match is null then raise exception 'not your ball'; end if;
  insert into bg_shots (match_id, player_id, n, data) values (v_match, p_player, p_n, p_data)
    on conflict (player_id, n) do nothing;
end $$;

revoke execute on function public.bg_create_match(text, uuid), public.bg_join_match(text, text, uuid),
  public.bg_add_shot(uuid, uuid, int, jsonb) from public;
grant execute on function public.bg_create_match(text, uuid), public.bg_join_match(text, text, uuid),
  public.bg_add_shot(uuid, uuid, int, jsonb) to anon, authenticated;

-- live updates: phones hear about new players and shots as they happen
alter publication supabase_realtime add table public.bg_players, public.bg_shots;
