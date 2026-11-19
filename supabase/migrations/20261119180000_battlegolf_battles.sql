-- BattleGolf battle mode online. Run once in the Supabase SQL editor of the BattleGolf project,
-- after 20261119150000_battlegolf_rounds.sql.
--
-- A battle is a 1 v 1 match played over three bouts (the same rules as Pure Golf's battles). The match
-- keeps its settings in bg_matches.battle; each player's power-ups, each fixed to a hole of the card,
-- are in bg_players.power_ups. Power-ups are either dealt here (the same kinds to both players, spread
-- evenly over the bouts, each player on their own random holes) or picked by each player before their
-- first shot. They never change after that.

alter table public.bg_matches add column battle jsonb
  check (battle is null or (jsonb_typeof(battle) = 'object' and pg_column_size(battle) < 2000));
alter table public.bg_players add column power_ups jsonb
  check (power_ups is null or (jsonb_typeof(power_ups) = 'object' and pg_column_size(power_ups) < 2000));

create function public.bg_power_up_kinds() returns text[] language sql immutable as $$
  select array['double_down', 'shield', 'heal', 'critical_hit', 'leech', 'sniper', 'poison',
               'block', 'last_stand', 'counter', 'second_wind']
$$;

-- holes on the card of a round spec like 'tilgate-forest:1-18' (1 for a single hole)
create function public.bg_round_holes(p_round text) returns int language sql immutable as $$
  select case
    when split_part(p_round, ':', 2) ~ '^[0-9]+-[0-9]+$'
      then split_part(split_part(p_round, ':', 2), '-', 2)::int - split_part(split_part(p_round, ':', 2), '-', 1)::int + 1
    else 1 end
$$;

-- one player's dealt power-ups: the battle's kinds in a random order, matched to random holes,
-- each bout taking its share (bouts[1..3]) of that bout's holes
create function public.bg_deal(p_battle jsonb, p_holes int) returns jsonb language plpgsql volatile as $$
declare v_per int := p_holes / 3; v_dealt jsonb;
begin
  select coalesce(jsonb_object_agg(kinds.kind, holes.hole), '{}'::jsonb) into v_dealt
  from (
    select kind, row_number() over (order by random()) as n
    from jsonb_array_elements_text(p_battle -> 'kinds') as kind
  ) kinds
  join (
    select hole, row_number() over (order by bout, r) as n
    from (
      select bout, hole, r, row_number() over (partition by bout order by r) as pick
      from (
        select bout, hole, random() as r
        from generate_series(1, 3) as bout
        cross join lateral generate_series((bout - 1) * v_per + 1, bout * v_per) as hole
      ) card
    ) ranked
    where pick <= (p_battle -> 'bouts' ->> (bout - 1))::int
  ) holes using (n);
  return v_dealt;
end $$;

-- the round's settings checked and, for a dealt battle, its kinds and per-bout counts drawn
create function public.bg_battle_settings(p_battle jsonb, p_holes int) returns jsonb language plpgsql volatile as $$
declare
  v_mode text := p_battle ->> 'mode';
  v_count int := (p_battle ->> 'count')::int;
  v_kinds jsonb; v_bouts jsonb;
begin
  if p_holes < 3 or p_holes % 3 <> 0 then raise exception 'battle needs 9 or 18 holes'; end if;
  if v_mode not in ('random', 'pick') then raise exception 'battle mode must be random or pick'; end if;
  if v_count is null or v_count not between 3 and 8 then raise exception 'battle is 3 to 8 power-ups each'; end if;
  if v_count > p_holes then raise exception 'more power-ups than holes'; end if;
  if v_mode = 'pick' then
    return jsonb_build_object('mode', 'pick', 'count', v_count, 'health', p_holes / 3);
  end if;
  select jsonb_agg(k) into v_kinds from (select k from unnest(bg_power_up_kinds()) k order by random() limit v_count) d;
  select jsonb_agg(c order by bout) into v_bouts from (
    select bout, v_count / 3 + case when row_number() over (order by random()) <= v_count % 3 then 1 else 0 end as c
    from generate_series(1, 3) bout
  ) d;
  if exists (select 1 from jsonb_array_elements_text(v_bouts) c where c::int > p_holes / 3) then
    raise exception 'more power-ups than holes in a bout';
  end if;
  return jsonb_build_object('mode', 'random', 'count', v_count, 'health', p_holes / 3, 'kinds', v_kinds, 'bouts', v_bouts);
end $$;

-- new match, optionally a battle: returns its code and the creator's player id (seat 0)
drop function public.bg_create_match(text, uuid, text);
create function public.bg_create_match(p_name text, p_secret uuid, p_round text, p_battle jsonb default null)
returns json language plpgsql security definer set search_path = public as $$
declare
  v_match uuid; v_code text; v_player uuid; v_name text := left(btrim(coalesce(p_name, '')), 16);
  v_round text := coalesce(p_round, 'tilgate-forest:1-18'); v_battle jsonb;
  alphabet constant text := 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
begin
  if v_name = '' then raise exception 'name required'; end if;
  if p_secret is null then raise exception 'secret required'; end if;
  if p_battle is not null then v_battle := bg_battle_settings(p_battle, bg_round_holes(v_round)); end if;
  loop
    v_code := '';
    for i in 1..5 loop
      v_code := v_code || substr(alphabet, 1 + floor(random() * length(alphabet))::int, 1);
    end loop;
    begin
      insert into bg_matches (code, hole, battle) values (v_code, v_round, v_battle) returning id into v_match;
      exit;
    exception when unique_violation then
      -- code already taken: try another
    end;
  end loop;
  insert into bg_players (match_id, seat, name, power_ups)
    values (v_match, 0, v_name, case when v_battle ->> 'mode' = 'random' then bg_deal(v_battle, bg_round_holes(v_round)) end)
    returning id into v_player;
  insert into bg_player_secrets (player_id, secret) values (v_player, p_secret);
  return json_build_object('match_id', v_match, 'code', v_code, 'player_id', v_player, 'seat', 0);
end $$;

-- join by code: the lowest free seat, up to 4 players (2 in a battle); a dealt battle deals to the joiner
create or replace function public.bg_join_match(p_code text, p_name text, p_secret uuid)
returns json language plpgsql security definer set search_path = public as $$
declare
  v_match bg_matches%rowtype; v_seat int; v_player uuid; v_name text := left(btrim(coalesce(p_name, '')), 16);
begin
  if v_name = '' then raise exception 'name required'; end if;
  if p_secret is null then raise exception 'secret required'; end if;
  select * into v_match from bg_matches where code = upper(btrim(p_code)) for update;
  if v_match.id is null then raise exception 'match not found'; end if;
  select s into v_seat from generate_series(0, case when v_match.battle is null then 3 else 1 end) s
    where not exists (select 1 from bg_players p where p.match_id = v_match.id and p.seat = s)
    order by s limit 1;
  if v_seat is null then raise exception 'match is full'; end if;
  insert into bg_players (match_id, seat, name, power_ups)
    values (v_match.id, v_seat, v_name,
            case when v_match.battle ->> 'mode' = 'random' then bg_deal(v_match.battle, bg_round_holes(v_match.hole)) end)
    returning id into v_player;
  insert into bg_player_secrets (player_id, secret) values (v_player, p_secret);
  return json_build_object('match_id', v_match.id, 'code', v_match.code, 'player_id', v_player, 'seat', v_seat);
end $$;

-- a player picks their power-ups (pick battles only): the right number, real kinds, each on its own
-- hole of the card, sent before their first shot and never changed after
create function public.bg_set_power_ups(p_player uuid, p_secret uuid, p_power_ups jsonb)
returns void language plpgsql security definer set search_path = public as $$
declare v_p bg_players%rowtype; v_match bg_matches%rowtype; v_holes int; v_count int;
begin
  select p.* into v_p from bg_players p join bg_player_secrets s on s.player_id = p.id
    where p.id = p_player and s.secret = p_secret for update of p;
  if v_p.id is null then raise exception 'not your ball'; end if;
  select * into v_match from bg_matches where id = v_p.match_id;
  if v_match.battle ->> 'mode' is distinct from 'pick' then raise exception 'this battle deals its power-ups'; end if;
  if v_p.power_ups is not null then raise exception 'power-ups already picked'; end if;
  if exists (select 1 from bg_shots where player_id = p_player) then raise exception 'already started'; end if;
  if jsonb_typeof(p_power_ups) is distinct from 'object' then raise exception 'power-ups must be kind and hole'; end if;
  v_holes := bg_round_holes(v_match.hole);
  select count(*) into v_count from jsonb_object_keys(p_power_ups);
  if v_count <> (v_match.battle ->> 'count')::int then raise exception 'wrong number of power-ups'; end if;
  if exists (select 1 from jsonb_each(p_power_ups) as e(kind, hole)
             where not (e.kind = any (bg_power_up_kinds())) or jsonb_typeof(e.hole) <> 'number'
                or e.hole::text !~ '^[0-9]+$' or (e.hole::text)::int not between 1 and v_holes) then
    raise exception 'unknown power-up, or a hole beyond the card';
  end if;
  if (select count(distinct e.hole::text) from jsonb_each(p_power_ups) as e(kind, hole)) <> v_count then
    raise exception 'two power-ups cannot share a hole';
  end if;
  update bg_players set power_ups = p_power_ups where id = p_player;
end $$;

revoke execute on function public.bg_create_match(text, uuid, text, jsonb), public.bg_set_power_ups(uuid, uuid, jsonb),
  public.bg_deal(jsonb, int), public.bg_battle_settings(jsonb, int) from public;
grant execute on function public.bg_create_match(text, uuid, text, jsonb), public.bg_set_power_ups(uuid, uuid, jsonb)
  to anon, authenticated;

-- phones hear when the other player picks their power-ups
alter table public.bg_players replica identity full;
do $$ begin
  if not exists (select 1 from pg_publication_tables where pubname = 'supabase_realtime' and tablename = 'bg_players') then
    alter publication supabase_realtime add table public.bg_players;
  end if;
end $$;
