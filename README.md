# BattleGolf

A tap-timing golf game played on cartoon, faux-isometric holes. Holes are built from tiles (a tee, 0–2 fairways and a green) and feature modules (bunkers, water, trees, props) described in a recipe, so courses can be designed in the course editor (see *Tile-built courses*). The courses are **Tilgate Forest** and **Ifield** (18 holes each), three themed courses (see *Themed courses*) and the **Patchwork Park** test course. Tilgate Forest began as a GPS course from Pure Golf's hole data and has been converted to tiles, its routing, hazards, slopes and greens following the original. Ifield and the themed courses are still built from GPS data (each hole's tee, layup and green points and elevation grids, with procedural bunkers, water and trees); their tile recipes are ready to switch to (see *Converted GPS courses*).

## Play

Serve the `game/` folder with any static server and open `index.html`:

```bash
cd game && python3 -m http.server 8765
# open http://localhost:8765
```

1. **Distance:** the target moves out from the ball and back, speeding up the further out it goes. Tap to lock it.
2. **Direction = draw or fade:** the target swings side to side and the dashed line bends with it. Tap in the middle and the ball flies straight; stop it left of centre for a draw (the ball bends left), right for a fade (bends right), up to the club's full spread at the ends. Shots set off along the aim line and bend more as they fly. On the green the swing is a plain direction error instead, since putts don't bend.
3. **Aim:** tap the yellow AIM buttons (or ← →) to nudge your aim before the first tap; hold to keep turning slowly. Shots set off down the aim line. Tee shots on par 4s and 5s start aimed at the middle of the fairway (the centre line about a drive out); everything else starts aimed at the flag.
4. **Putting:** the green shows a wire grid lifted by the green's height (exaggerated, so the shape is easy to see) and coloured by steepness, from blue (under 1 %) through green and yellow to red and magenta (over 10 %); the *Slope %* key beside the buttons gives the bands. White arrows point downhill (they take the steepness colours when the heat map is off), and *Lines* adds 5 cm contours. Putts are simulated with friction and gravity, so they break with the slope.
5. **Gimmes:** a ball resting within 1 m of the cup (inside the white ring) is holed for +1 stroke.
6. **Rounds:** pick a course and play 18 holes, the front or back 9, or a single hole. A card after each hole shows your score and the running total to par; the next hole loads while you look at it.
7. **Hazards:** bunkers are a sand lie (short, wilder shots), and water (ponds and streams) costs a stroke with a drop back along the line the ball came in on.
8. **Pass-and-play:** pick 1–8 players and their names on the start screen. Everyone tees off in order, then whoever is furthest from the hole plays next. A "pass the phone" screen appears whenever the turn moves to someone else, and the scorecard ranks everyone at the end. Each player's ball is drawn in their colour.

9. **Online:** enter your name and tap *Create match* to get a 5-letter code and a link to share; friends join with the code or link (up to 8). The match uses the course and holes picked on the start screen. Everyone plays their own round on their own phone whenever they like. Other players' shots replay on your screen as ghost balls, the scoreboard updates live, and the final scorecard appears once everyone has holed out. Closing the app is fine: opening the link again picks up where you left off. Finished before the others? Tap a name under *Watch* on the scorecard to follow them hole by hole as their shots replay; tap the course to go back to the scores.

10. **Accounts and leaderboards:** tap *Sign in / Register* on the start screen to make an account with an email, a username and a password. Signed in, every finished round is saved to *My scores* (in pass-and-play, Player 1's round is yours). The 🏆 *Leaderboards* show each player's best round **today**, **this week** (Monday to Sunday) and **this month**, per course, for 18 holes, the front 9 and the back 9 (UK time). Anyone can view them; only signed-in players appear. Needs `supabase/migrations/20261120090000_battlegolf_accounts.sql`.

The lie changes the maximum carry and the side-to-side swing: tee 260 yds, fairway 230, first cut 205, rough 175, bunker 120, trees 90. Off the map costs a penalty stroke.

## Formats

With 2 or more players, choose the format on the setup screen:

- **Stroke play:** fewest strokes over the round wins.
- **Match play** (1 v 1): each hole goes to the lower score, and a tie halves it. The match ends as soon as one player is more holes up than there are holes left (for example "won 3&2"). Online, the first two to join play the match.
- **Skins:** each hole is worth a skin. The lowest score on its own takes it, plus any skins carried over; a tie carries the skin to the next hole. Most skins wins.

Online formats need `supabase/migrations/20261119190000_battlegolf_formats.sql`. Online matches of more than 4 players need `supabase/migrations/20261119210000_battlegolf_8_players.sql`.

## Battle mode

Turn on **Battle mode** on the setup screen for a 1 v 1 fight over 9 or 18 holes, with the same rules as Pure Golf's battles:

- The round is split into **three bouts** of equal length (6 holes each over 18, 3 over 9). Both players start every bout on full health: one point per hole of the bout.
- Each hole is scored in **Stableford points** (2 for par, 1 more per stroke under, 0 at double bogey or worse). The difference is the damage the loser takes. Hitting 0 health loses the bout on the spot (a knockout); otherwise the healthier player takes it.
- **Most bouts wins**; total damage dealt breaks a tie.
- **Power-ups** (3 to 8 each) are fixed to holes before the round. **Dealt** gives both players the same kinds, spread evenly over the bouts, each on their own random holes. **Pick your own** lets each player choose kinds and holes, one per hole, before their first shot.
- The 11 power-ups are Double Down, Shield, Heal, Critical Hit, Leech, Sniper, Poison, Block, Last Stand, Counter and Second Wind. Each one is explained in the game.

The rules engine (`battlePlay` in `game/index.html`) is a straight port of Pure Golf's `BattleScoring.play`. It was cross-checked against the Dart code on thousands of random cards.

Online battles are always 1 v 1 and need `supabase/migrations/20261119180000_battlegolf_battles.sql`. That migration deals power-ups in the database and checks picked sets.
## Hosting

The game is live at **https://battlegolf.party** (also https://battlegolf.puregolfai-website.workers.dev), served by Cloudflare as static files from `game/` (Cloudflare Pages, now part of Workers; settings in `wrangler.jsonc`). To publish changes:

```bash
npx wrangler@4 deploy
```

## Online play and the phone app

Online matches use the BattleGolf Supabase project (URL and publishable key in `game/config.js`). Set it up once by running the files in `supabase/migrations/` in order in that project's SQL editor. There are no accounts: each phone keeps a random secret per match, the tables are read-only to the app, and the only writes are the `bg_create_match`, `bg_join_match` and `bg_add_shot` functions. Never put the service_role key in `config.js`.

Player accounts (for saved scores and leaderboards) use Supabase Auth with email and password. In the Supabase dashboard, under Authentication → URL Configuration, set the Site URL to `https://battlegolf.party` and add it as a redirect URL, so confirmation and password-reset links come back to the game. Supabase's built-in email sender only sends a few emails an hour; set up your own SMTP (Authentication → Emails) before many people sign up. Usernames live in `bg_profiles`; saved rounds in `bg_rounds`, readable only by their owner; the leaderboards come from `bg_leaderboard`, which shows usernames and scores, never emails.

The game is also an installable web app (`manifest.webmanifest`, `icons/`, `sw.js`). Once it's served over HTTPS, "Add to Home Screen" on iPhone or "Install app" on Android gives it an icon and full-screen play, and the game itself works offline. Bump `VERSION` in `game/sw.js` whenever game files change so installed copies pick up the new files.

## Layout

| Path | What it is |
| --- | --- |
| `game/` | The playable game (`index.html`) |
| `game/courses/` | `courses.json` (the course list) and one folder per hole: course picture, 4× detail tile around the green, heat map, contours and game data, in portrait and landscape |
| `game/config.js`, `game/sw.js`, `game/manifest.webmanifest`, `game/icons/` | Online-play settings and the installable-app files |
| `supabase/migrations/` | Database setup for online matches |
| `data/recipes/` | Course recipes: each hole's tiles, feature modules and placed props |
| `data/` | Hole files (`<course>-<NN>.json`): composed from a recipe by `compose_hole.py`, or for the courses not yet converted, GPS data exported from Pure Golf's `holes` table; `data/gps/` keeps the original GPS files of converted courses |
| `tools/render_hole_toon.py` | Renders the cartoon hole, the 4× detail tile around the green, the green heat map, and the game data (lie grid, trees, camera transform, green elevation) |
| `tools/reheat.py` | Redraws a built hole's green heat map (the wire grid) from its slope data, in seconds; `build_course.sh` runs it on every build |
| `tools/build_course.sh` | Builds one hole's assets from a file in `data/` |
| `tools/build_round.sh` | Builds every hole of a course into `game/courses/<course>/` and updates `courses.json` |
| `tools/course_editor.py`, `tools/editor/` | Local editor for tile-built courses (see below) |
| `tools/compose_hole.py`, `data/recipes/` | Builds holes from tiles and modules (see *Tile-built courses*) |
| `tools/render_hole.py` | The earlier top-down (non-cartoon) renderer |
| `tools/playtest.py` | Headless Playwright playtest that taps through rounds and screenshots the green |

## Rebuild the course assets

Needs Python 3 with `numpy`, `scipy` and `Pillow`.

```bash
python3 tools/compose_hole.py data/recipes/tilgate-forest.json        # recipe -> data/tilgate-forest-NN.json
bash tools/build_round.sh tilgate-forest "Tilgate Forest"             # all 18 holes, ~3 min each, 4 at a time
```

Adding a course: make it in the course editor (or write a recipe in `data/recipes/`), then compose and build it. Bump `VERSION` in `game/sw.js` afterwards.

## Themed courses

**Lunar Links** (`space`), **Neon Nights** (`neon`) and **Castle Keep** (`medieval`) are 18-hole, par-72 courses (4 par 3s, 10 par 4s, 4 par 5s) whose holes were drawn at random from Pure Golf's `holes` table, one hole per real course; each GPS hole file keeps where its hole came from under `source` (course, hole number and id). Stroke indexes are set by length for par: odd numbers on the front 9, even on the back.

The hole files carry `"theme"`, which `render_hole_toon.py` uses to pick its palette and props (or set `THEME=` when rendering). Play is the same on every theme: only the paint changes.

| Theme | Ground | Fairway, green | Bunkers | Water | Trees and props |
| --- | --- | --- | --- | --- | --- |
| `space` | Grey-violet moon dust with craters | Glowing teal | Pink stardust | A starry void | Crystal spires, glowing pods, moon rocks |
| `neon` | Dark violet on a magenta grid | Indigo with neon outlines | Neon yellow | Electric blue | Neon palms, light orbs, wireframe cubes |
| `medieval` | Olive meadow with worn patches | Muted greens, flagstone tees | Straw and earth | A dark moat | Pictures from `art/nature` and `art/medieval`: pines and oaks, plus towers, ruins, tents, carts, hay and barrels |

`courses.json` records each course's `theme`, and the game sets the page colour round the picture to match. A course marked `"hidden": true` there is left out of the course and leaderboard pickers (its files stay, and an online round already on it still loads); `tools/course_index.py` keeps the flag when a course is rebuilt. For now only **Tilgate Forest** and **Castle Keep** are shown: Ifield, Lunar Links, Neon Nights and Patchwork Park are hidden.

A GPS hole file can carry placed pictures of its own as `"props": [{"kind", "pt": [lat, lng], "scale"?, "flip"?}]`. They claim their ground before the automatic scenery and play by their lie (see *How props play*). Castle Keep uses this on holes 2–18 for a small hay field (two haystacks and a row of bales, which play as hay) in the rough just off the first cut: beside the landing zone on the par 4s and 5s, and beside the green on the par 3s. `tools/gps_to_recipe.py` doesn't carry these over yet, so re-place them in the editor if Castle Keep is switched to tiles. Castle Keep's hole 1 has already been redesigned from its tile recipe in the editor (ruined walls and a market, no hay); the other 17 holes are still built from GPS.

## Tile-built courses

Holes can also be put together from tiles instead of GPS data. A recipe in `data/recipes/<course>.json` lists each hole's **core tiles** and the **feature modules** that sit on them; `tools/compose_hole.py` turns it into ordinary `data/<course>-NN.json` files (made-up GPS points, a centre line, hills, green slopes and a drawn map), and the normal build renders them:

```bash
python3 tools/compose_hole.py data/recipes/patchwork.json          # or add hole numbers: ... patchwork.json 3 7
bash tools/build_round.sh patchwork "Patchwork Park"
```

**Patchwork Park** (`patchwork`, 9 holes) is the test course and uses every tile and module.

### Converted GPS courses

Tilgate Forest, Ifield, Lunar Links, Neon Nights and Castle Keep were GPS courses. `tools/gps_to_recipe.py` converts one to a recipe; it reads the GPS hole files from `data/gps/` (once a course is converted) or `data/`. All five recipes are in `data/recipes/`, but so far only **Tilgate Forest** has been switched over and rebuilt from tiles. To switch another (Ifield, say):

```bash
mkdir -p data/gps && git mv data/ifield-[0-9][0-9].json data/gps/     # keep the GPS originals
python3 tools/compose_hole.py data/recipes/ifield.json                 # tiles -> data/ifield-NN.json
bash tools/build_round.sh ifield "Ifield"                              # ~15 min, 4 holes at a time
```

Until then, the editor lists those courses' recipes, but building a hole there replaces the GPS one. To convert from scratch: `python3 tools/gps_to_recipe.py ifield --id ifield`.

- **Routing:** tile lengths and turns are fitted so the composed centre line follows the GPS one (the curve from the tee through the layup to the green), keeping the hole's heading; most holes are within 2–3 m all the way along, the worst about 13 m.
- **Hazards:** the GPS holes' bunkers, ponds and streams were placed by the renderer's rules, not mapped, so each becomes a module on the matching tile and spot; the automatic treeline stays on.
- **Ground and greens:** the real heights along the centre line choose each fairway's slope preset and the tee and green heights; the real green surface chooses the nearest green slope preset. Real hills away from the line and the exact green contours aren't kept.
- **Yardages** now come from the composed length (the length the game always played) rather than the scorecard, so some differ from the old card by a few yards.

**Core tiles** join end to end, and the number of tiles sets the par: `tee` + `green` is a par 3, `tee` + `fairway` + `green` a par 4, `tee` + 2 `fairway`s + `green` a par 5. The composer warns if a hole's length is unusual for its par (par 3: 110–230 yds, par 4: 290–470, par 5: 460–600).

| Tile | Options |
| --- | --- |
| `tee` | `len` (m; default 55, or 150 on a par 3, where it's the whole carry), `elev`: `level`, `raised`, `elevated` |
| `fairway` | `len` (m) or `size`: `short` 165, `medium` 200, `long` 240; `bend`: `straight`, `left`, `right`, `hard_left`, `hard_right`, `s_left`, `s_right` (or `turn` in degrees, + right, and `corner` 0–1); `width`: `narrow`, `normal`, `wide`; `slope`: `flat`, `uphill`, `downhill`, `ridge`, `valley`; `gap`: `[from, to]` (0–1) leaves rough to carry |
| `green` | `len` (approach, m; default 40), `shape`: `oval`, `long`, `round`, `wide`, `kidney`; `slope`: `flat`, `back_to_front`, `front_to_back`, `left_to_right`, `right_to_left`, `crown`, `bowl`, `two_tier`; `elev`: `level`, `raised`, `sunken`; `angle` (degrees the green is turned) |

**Modules** go `"at": "<tile>.<spot>"`. The tile is `tee`, `fairway` (on a par 5: `fairway1`, `fairway2`) or `green`. `pos` (0–1) is how far along the tile; `size` is `small`, `medium` or `large`; `count` repeats it.

| Module | Spots | Notes |
| --- | --- | --- |
| `bunker` | `left`, `right`, `cross`, `centre`; on the green `front`, `back`, `left`, `right`, `front_left`, `front_right`, `back_left`, `back_right` | fairway bunkers bite the fairway's edge; greenside ones hug the green |
| `lake` | `left`, `right`, `cross`; `green.front`, `green.island` | `bite: true` pushes a side lake into the fairway; `offset` (m) moves a front lake sideways |
| `stream` | `cross`, `left`, `right`; `green.front` | `angle` (degrees) runs a crossing stream on the diagonal |
| `treeline` | `left`, `right` | `from`/`to` (0–1) along the tile, `tight: true` brings it closer |
| `copse` | `left`, `right`, `green.back` | a clump of woods |
| `tree` | `left`, `right` | a single tree on the edge of the cut |
| `props` | `left`, `right` | `kind`: `rock` or `bush` |

A hole can also set `heading` (degrees from north; random otherwise), `si`, `theme`, `seed` (reshuffles the small random details) and `auto_trees: true` (adds the renderer's automatic treeline as well). Stroke indexes are set by length for par when left out.

## Course editor

A local page for making tile-built courses (see *Tile-built courses*): holes are put together from tiles and feature modules, not from GPS.

```bash
python3 tools/course_editor.py
# open http://localhost:8790
```

- Pick a course recipe from `data/recipes/` (or *New course*), set its name and theme, and add, duplicate, delete or reorder holes (up to 18).
- For each hole, pick **par 3, 4 or 5** (that sets the tiles: a tee, 0–2 fairways and a green), then set each tile's options: tee length and height; fairway length, bend, width, slope and a gap of rough; green approach, shape, slope, height and turn.
- **Features** adds bunkers, lakes, streams, treelines, copses, single trees and rocks or bushes, each on a tile and a spot (left, right, cross, front of the green…), with how far along the tile, size and count.
- The middle shows a **plan view** of the hole that updates as you edit: the tee is at the bottom, with fairway, green, bunkers, water, woods, the centre line, where each tile starts and a 50 m bar. Drag to pan and scroll to zoom; *Fit* shows the whole hole. Par, length and the composer's warnings (an odd length for the par, a hazard over the tee or green) show as you go.
- **Props**: pick a set (*Nature*: trees, bushes, rocks, long grass, paths, ponds and streams; *Medieval*: castles, towers, ruined walls, hay, carts, fences, tents, bridges, flags) and a picture, then click the plan to place it. Click a prop to select it; **Shift**-click or **Shift**-drag a box to select several. Drag to move the selection. The selection card shows how a ball plays there and can resize (a multiple selection grows or shrinks as one, spacing included), flip (a multiple selection is mirrored), duplicate, group, ungroup or delete. To remove props: **right-click** one, press **Delete** on the selection, or *Clear all* for the whole hole. *Undo* (**Cmd/Ctrl+Z**) steps back through prop changes on the hole you're on. In the built hole, props are drawn at their ground point with trees cleared from under them. Props are saved in the hole's recipe as `"props": [{"kind", "at": [x, y]}]`, in metres from the tee (x to the right, y straight ahead), so they move with the hole.
- **Prop groups**: props that belong together (a farmyard, a camp, a rock garden) can be grouped (*Group*, or **Cmd/Ctrl+G**). Clicking any one then selects the whole group, so it moves, resizes and is deleted as one; grouped props carry `"g": <number>` in the recipe. *Save as group…* adds the selection to the **Groups** list under the pictures, shared by every course (`art/groups.json`). Pick a group there and click the plan to drop the whole set, already grouped. Starter groups: *Hay field*, *Farmyard*, *Army camp*, *Market* and *Ruined wall* (medieval), and *Rock garden*, *Pond corner*, *Copse* and *Meadow* (nature). The ✕ on a group removes it from the list, but props already placed stay.
- **How props play**: each picture has a `lie` in `props.json`, which is baked into the hole's lie grid:

  | `lie` | Plays as | Props |
  |---|---|---|
  | `hay` | Hay: plays exactly like a bunker, but the game says *In the hay!* and shows *Hay* (lie code 8) | haystack, hay bales |
  | `sand` | Bunker | sand bank |
  | `trees` | Trees (blocks shots, ball stays where it lands) | trees, boulders and big rocks, buildings, walls, fences, carts, wells, barrels, crates, tents, spikes, archery target |
  | `path` | Fairway (and wins over water, so a bridge can be crossed) | paths, cobble and stone tiles, bridges, drawbridge, platform |
  | `rough` | Rough, even on the fairway | long grass, bushes, dirt patch |
  | `water` | Water (only the blue of the picture) | ponds, streams, canal, reed pond, sand shore |
  | none | The ground underneath | flags, small stones, pebbles, grass patch |

  Flat pictures (paths, ponds, long grass) cover their drawn shape. Upright ones (hay, buildings, rocks) cover a circle round their ground point. The tee and green always win.
- *Reshuffle* changes the hole's `seed`: new bunker shapes, fairway edges, green rolls and heading. Stroke index is worked out by length unless you set it.
- **Save** writes the recipe. **Save & build hole** also composes it into `data/<course>-NN.json` and renders it into `game/courses/` (about 3 minutes; one build at a time), then updates `courses.json`; *Save & build every hole* queues the lot. The built picture shows on the right: click it (or *Larger*) for a full-window view with tabs for the whole hole, the portrait picture and the two green close-ups; scroll to zoom, drag to pan, double-click to switch between fit and full size, **Esc** to close. *Play the game* opens it at `/game/`.

**Scenery.** On the `classic` and `medieval` themes, every tree, bush, rock and ornament round a hole is one of these pictures, so the built holes match the editor's style. The renderer fills the woods and the treeline with tree pictures, puts a few landmarks in the rough or in clearings (boulders and small ponds; on `medieval` also towers, ruined walls, tents, carts and hay), then scatters bushes, rocks and long grass. Every picture is checked against the course and against everything already placed:
- Nothing covers the tee, fairway, first cut, green, bunkers or water. Hazards on the course come only from the recipe.
- Props placed in the editor claim their ground first.
- Trees may overlap each other a little, as in a wood. Nothing else overlaps anything.

Each spot's choice is seeded from the hole and its position, so the base picture and the detail tile always agree. Trees, big rocks and buildings still block shots, and small ponds play as water (see *How props play*). The `space` and `neon` themes keep their own drawn scenery until they have prop sets of their own.

Each prop set lives in `art/<set>/`: the cut-out pictures and their sizes in `props/props.json`, cut from the sheet and its black-and-white mask in `source/` by `python3 tools/split_props.py art/<set>` (names, centres and sizes in `source/sheet.json`).

Bump `VERSION` in `game/sw.js` before deploying rebuilt holes.

## Assumptions to check

- **GPS elevation grid:** read the way the Pure Golf app builds it (`generateHoleGrid`): columns 18 m apart either side of the tee→green line, rows evenly spaced from the tee to 20 m past the green.
- **GPS layout is approximate on purpose:** on the GPS courses, fairways follow a curve from the tee through the layup point to the green; greens are a standard rounded oval (26–32 m long) centred on the GPS green point, because the GPS front/back points vary too much; bunkers, water and trees are procedural, not mapped.
- **GPS green grid:** read as north-up. If it's actually aligned with the hole, every green break on the GPS courses (and the slopes converted from them) is rotated.
