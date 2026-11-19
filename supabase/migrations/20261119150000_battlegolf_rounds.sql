-- BattleGolf full rounds online. Run once in the Supabase SQL editor of the BattleGolf project,
-- after 20261119120000_battlegolf_online.sql.
--
-- A match now remembers its course and holes in bg_matches.hole, e.g. 'tilgate-forest:1-18',
-- 'tilgate-forest:10-18' or 'abbey-hill:13' (older matches keep 'abbey-hill-13', which the game still reads).
-- Shot numbers run per hole: n = hole index in the round * 100 + shot number on that hole.

alter table public.bg_matches
  add constraint bg_matches_hole_format check (hole ~ '^[a-z0-9-]{1,40}(:[0-9]{1,2}(-[0-9]{1,2})?)?$');

alter table public.bg_shots drop constraint bg_shots_n_check;
alter table public.bg_shots add constraint bg_shots_n_check check (n between 1 and 1799);

-- new match for a given round: returns its code and the creator's player id (seat 0)
create function public.bg_create_match(p_name text, p_secret uuid, p_round text)
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
      insert into bg_matches (code, hole) values (v_code, coalesce(p_round, 'abbey-hill:13')) returning id into v_match;
      exit;
    exception when unique_violation then
      -- code already taken: try another
    end;
  end loop;
  insert into bg_players (match_id, seat, name) values (v_match, 0, v_name) returning id into v_player;
  insert into bg_player_secrets (player_id, secret) values (v_player, p_secret);
  return json_build_object('match_id', v_match, 'code', v_code, 'player_id', v_player, 'seat', 0);
end $$;

revoke execute on function public.bg_create_match(text, uuid, text) from public;
grant execute on function public.bg_create_match(text, uuid, text) to anon, authenticated;
