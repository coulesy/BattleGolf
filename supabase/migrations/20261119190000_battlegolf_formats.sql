-- BattleGolf formats online: stroke play, match play or skins. Run once in the Supabase SQL editor of the
-- BattleGolf project, after 20261119180000_battlegolf_battles.sql.
--
-- The format is kept on the match; the game works out the standings from everyone's scores. Match play is
-- 1 v 1, so a match play match takes two players, like a battle.

alter table public.bg_matches add column format text not null default 'stroke'
  check (format in ('stroke', 'match', 'skins'));

drop function public.bg_create_match(text, uuid, text, jsonb);
create function public.bg_create_match(p_name text, p_secret uuid, p_round text, p_battle jsonb default null,
                                       p_format text default 'stroke')
returns json language plpgsql security definer set search_path = public as $$
declare
  v_match uuid; v_code text; v_player uuid; v_name text := left(btrim(coalesce(p_name, '')), 16);
  v_round text := coalesce(p_round, 'tilgate-forest:1-18'); v_battle jsonb;
  v_format text := coalesce(p_format, 'stroke');
  alphabet constant text := 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
begin
  if v_name = '' then raise exception 'name required'; end if;
  if p_secret is null then raise exception 'secret required'; end if;
  if v_format not in ('stroke', 'match', 'skins') then raise exception 'format must be stroke, match or skins'; end if;
  if p_battle is not null then v_battle := bg_battle_settings(p_battle, bg_round_holes(v_round)); v_format := 'stroke'; end if;
  loop
    v_code := '';
    for i in 1..5 loop
      v_code := v_code || substr(alphabet, 1 + floor(random() * length(alphabet))::int, 1);
    end loop;
    begin
      insert into bg_matches (code, hole, battle, format) values (v_code, v_round, v_battle, v_format) returning id into v_match;
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

-- join by code: the lowest free seat, up to 4 players (2 in a battle or match play)
create or replace function public.bg_join_match(p_code text, p_name text, p_secret uuid)
returns json language plpgsql security definer set search_path = public as $$
declare
  v_match bg_matches%rowtype; v_seat int; v_player uuid; v_name text := left(btrim(coalesce(p_name, '')), 16);
begin
  if v_name = '' then raise exception 'name required'; end if;
  if p_secret is null then raise exception 'secret required'; end if;
  select * into v_match from bg_matches where code = upper(btrim(p_code)) for update;
  if v_match.id is null then raise exception 'match not found'; end if;
  select s into v_seat from generate_series(0, case when v_match.battle is not null or v_match.format = 'match' then 1 else 3 end) s
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

revoke execute on function public.bg_create_match(text, uuid, text, jsonb, text) from public;
grant execute on function public.bg_create_match(text, uuid, text, jsonb, text) to anon, authenticated;
