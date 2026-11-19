-- BattleGolf accounts and leaderboards. Run once in the Supabase SQL editor of the BattleGolf project,
-- after 20261119190000_battlegolf_formats.sql.
--
-- Players can register with an email, a username and a password (Supabase Auth). Signed-in players' finished
-- rounds are saved to bg_rounds, which only its owner can read. The daily, weekly and monthly leaderboards
-- come from bg_leaderboard, which shows usernames and scores only, never emails.
-- Days, weeks (Monday to Sunday) and months follow UK time.

create table public.bg_profiles (
  id         uuid primary key references auth.users (id) on delete cascade,
  username   text not null check (username ~ '^[A-Za-z0-9_]{3,16}$'),
  created_at timestamptz not null default now()
);
create unique index bg_profiles_username_idx on public.bg_profiles (lower(username));

create table public.bg_rounds (
  id        uuid primary key,                       -- made by the phone, so a retried save can't count twice
  user_id   uuid not null references public.bg_profiles (id) on delete cascade,
  course    text not null check (course ~ '^[a-z0-9-]{1,40}$'),
  holes     text not null check (holes ~ '^[0-9]{1,2}(-[0-9]{1,2})?$'),   -- "1-18", "1-9", "10-18" or "7"
  kind      text not null check (kind in ('18', 'front9', 'back9', 'hole', 'other')),
  cards     smallint[] not null,                    -- strokes per hole
  pars      smallint[] not null,
  strokes   smallint not null,
  par       smallint not null,
  to_par    smallint generated always as (strokes - par) stored,
  mode      text not null check (mode in ('solo', 'local', 'online', 'battle')),
  played_at timestamptz not null default now()
);
create index bg_rounds_board_idx on public.bg_rounds (course, kind, played_at);
create index bg_rounds_user_idx on public.bg_rounds (user_id, played_at desc);

alter table public.bg_profiles enable row level security;
alter table public.bg_rounds   enable row level security;
create policy "players read their own profile" on public.bg_profiles for select to authenticated using (id = auth.uid());
create policy "players read their own rounds"  on public.bg_rounds   for select to authenticated using (user_id = auth.uid());
revoke insert, update, delete, truncate on public.bg_profiles, public.bg_rounds from anon, authenticated;

-- is a username free? (asked before signing up, so the player gets a clear message)
create function public.bg_username_free(p_username text)
returns boolean language sql stable security definer set search_path = public as $$
  select btrim(coalesce(p_username, '')) ~ '^[A-Za-z0-9_]{3,16}$'
     and not exists (select 1 from bg_profiles where lower(username) = lower(btrim(p_username)));
$$;

-- every new account gets a profile with the username it signed up with
create function public.bg_new_user()
returns trigger language plpgsql security definer set search_path = public as $$
begin
  insert into public.bg_profiles (id, username) values (new.id, btrim(new.raw_user_meta_data ->> 'username'));
  return new;
end $$;
create trigger bg_on_auth_user_created after insert on auth.users for each row execute function public.bg_new_user();

-- save a finished round for the signed-in player
create function public.bg_save_round(p_id uuid, p_course text, p_holes text, p_cards int[], p_pars int[], p_mode text)
returns void language plpgsql security definer set search_path = public as $$
declare
  v_user uuid := auth.uid(); n int := coalesce(array_length(p_cards, 1), 0);
  a int; b int; v_kind text;
begin
  if v_user is null then raise exception 'sign in to save rounds'; end if;
  if p_id is null then raise exception 'round id required'; end if;
  if p_holes !~ '^[0-9]{1,2}(-[0-9]{1,2})?$' then raise exception 'bad holes'; end if;
  a := split_part(p_holes, '-', 1)::int; b := coalesce(nullif(split_part(p_holes, '-', 2), '')::int, a);
  if a < 1 or b > 18 or b < a or n <> b - a + 1 or n <> coalesce(array_length(p_pars, 1), 0) then raise exception 'bad holes'; end if;
  if exists (select 1 from unnest(p_cards) s where s is null or s < 1 or s > 20) then raise exception 'bad strokes'; end if;
  if exists (select 1 from unnest(p_pars) s where s is null or s < 3 or s > 5) then raise exception 'bad pars'; end if;
  if (select count(*) from bg_rounds where user_id = v_user and played_at > now() - interval '1 day') >= 60 then
    raise exception 'too many rounds today';
  end if;
  v_kind := case when a = 1 and b = 18 then '18' when a = 1 and b = 9 then 'front9' when a = 10 and b = 18 then 'back9'
                 when n = 1 then 'hole' else 'other' end;
  insert into bg_rounds (id, user_id, course, holes, kind, cards, pars, strokes, par, mode)
  values (p_id, v_user, p_course, p_holes, v_kind, p_cards::smallint[], p_pars::smallint[],
          (select sum(s) from unnest(p_cards) s), (select sum(s) from unnest(p_pars) s), p_mode)
  on conflict (id) do nothing;
end $$;

-- each player's best round this day / week / month on a course, best first
create function public.bg_leaderboard(p_period text, p_course text, p_kind text, p_limit int default 50)
returns table (rank bigint, username text, to_par int, strokes int, played_at timestamptz, rounds bigint, me boolean)
language sql stable security definer set search_path = public as $$
  with since as (
    select (date_trunc(case p_period when 'week' then 'week' when 'month' then 'month' else 'day' end,
                       now() at time zone 'Europe/London') at time zone 'Europe/London') as t
  ), mine as (
    select r.*, count(*) over (partition by r.user_id) as n,
           row_number() over (partition by r.user_id order by r.to_par, r.strokes, r.played_at) as k
    from bg_rounds r, since
    where r.course = p_course and r.kind = p_kind and r.played_at >= since.t
  )
  select rank() over (order by m.to_par, m.strokes), p.username, m.to_par::int, m.strokes::int, m.played_at, m.n,
         coalesce(m.user_id = auth.uid(), false)
  from mine m join bg_profiles p on p.id = m.user_id
  where m.k = 1
  order by m.to_par, m.strokes, m.played_at
  limit least(greatest(coalesce(p_limit, 50), 1), 100);
$$;

revoke execute on function public.bg_new_user() from public, anon, authenticated;
grant execute on function public.bg_username_free(text), public.bg_leaderboard(text, text, text, int) to anon, authenticated;
revoke execute on function public.bg_save_round(uuid, text, text, int[], int[], text) from public, anon;
grant execute on function public.bg_save_round(uuid, text, text, int[], int[], text) to authenticated;
