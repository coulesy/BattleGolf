-- BattleGolf: up to 8 players in an online match (was 4). Run once in the Supabase SQL editor of the BattleGolf
-- project, after 20261119190000_battlegolf_formats.sql. Battles and match play stay 1 v 1.

alter table public.bg_players drop constraint bg_players_seat_check;
alter table public.bg_players add constraint bg_players_seat_check check (seat between 0 and 7);

-- join by code: the lowest free seat, up to 8 players (2 in a battle or match play)
create or replace function public.bg_join_match(p_code text, p_name text, p_secret uuid)
returns json language plpgsql security definer set search_path = public as $$
declare
  v_match bg_matches%rowtype; v_seat int; v_player uuid; v_name text := left(btrim(coalesce(p_name, '')), 16);
begin
  if v_name = '' then raise exception 'name required'; end if;
  if p_secret is null then raise exception 'secret required'; end if;
  select * into v_match from bg_matches where code = upper(btrim(p_code)) for update;
  if v_match.id is null then raise exception 'match not found'; end if;
  select s into v_seat from generate_series(0, case when v_match.battle is not null or v_match.format = 'match' then 1 else 7 end) s
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
