# BattleGolf

A tap-timing golf game played on cartoon, faux-isometric holes built from real courses. Each hole's shape and distances come from Pure Golf's own hole data (GPS tee, layup and green points, plus elevation grids); the details are procedural: standard-size greens, bunkers, ponds, streams and treelines, placed by simple rules seeded per hole so a hole always comes out the same. The courses are **Tilgate Forest** and **Ifield** (18 holes each), plus three themed courses made from holes picked at random from Pure Golf's database (see *Themed courses*).

## Play

Serve the `game/` folder with any static server and open `index.html`:

```bash
cd game && python3 -m http.server 8765
# open http://localhost:8765
```

1. **Distance:** the target moves out from the ball and back, speeding up the further out it goes. Tap to lock it.
2. **Direction:** the target swings side to side. Tap when it's on the line.
3. **Aim:** tap the yellow AIM buttons (or ← →) to nudge your aim before the first tap; hold to keep turning slowly. Tee shots follow the fairway centre line, so they curve with the dogleg; on par 3s they aim straight at the flag.
4. **Putting:** the green shows a wire grid lifted by the green's height (exaggerated, so the shape is easy to see) and coloured by steepness, from blue (under 1 %) through green and yellow to red and magenta (over 10 %); the *Slope %* key beside the buttons gives the bands. White arrows point downhill (they take the steepness colours when the heat map is off), and *Lines* adds 5 cm contours. Putts are simulated with friction and gravity, so they break with the slope.
5. **Gimmes:** a ball resting within 1 m of the cup is holed for +1 stroke; within 2 m, +2.
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
| `data/` | Hole input data exported from the Pure Golf `holes` table, one file per hole (`<course>-<NN>.json`) |
| `tools/render_hole_toon.py` | Renders the cartoon hole, the 4× detail tile around the green, the green heat map, and the game data (lie grid, trees, camera transform, green elevation) |
| `tools/reheat.py` | Redraws a built hole's green heat map (the wire grid) from its slope data, in seconds; `build_course.sh` runs it on every build |
| `tools/build_course.sh` | Builds one hole's assets from a file in `data/` |
| `tools/build_round.sh` | Builds every hole of a course into `game/courses/<course>/` and updates `courses.json` |
| `tools/course_editor.py`, `tools/editor/` | Local course editor (see below) |
| `tools/compose_hole.py`, `data/recipes/` | Builds holes from tiles and modules (see *Tile-built courses*) |
| `tools/render_hole.py` | The earlier top-down (non-cartoon) renderer |
| `tools/playtest.py` | Headless Playwright playtest that taps through rounds and screenshots the green |

## Rebuild the course assets

Needs Python 3 with `numpy`, `scipy` and `Pillow`.

```bash
bash tools/build_round.sh tilgate-forest "Tilgate Forest"      # all 18 holes, ~3 min each, 4 at a time
```

Adding a course: export its holes from Pure Golf into `data/<course>-01.json` … (same fields as the existing files), then build it. Bump `VERSION` in `game/sw.js` afterwards.

## Themed courses

**Lunar Links** (`space`), **Neon Nights** (`neon`) and **Castle Keep** (`medieval`) are 18-hole, par-72 courses (4 par 3s, 10 par 4s, 4 par 5s) whose holes were drawn at random from Pure Golf's `holes` table, one hole per real course, from holes with complete GPS, layup, green and elevation data, not flagged for review, and whose GPS length matches the card. Each data file keeps where its hole came from under `source` (course, hole number and id). Stroke indexes are set by length for par: odd numbers on the front 9, even on the back.

The hole files carry `"theme"`, which `render_hole_toon.py` uses to pick its palette and props (or set `THEME=` when rendering). Play is the same on every theme: only the paint changes.

| Theme | Ground | Fairway, green | Bunkers | Water | Trees and props |
| --- | --- | --- | --- | --- | --- |
| `space` | Grey-violet moon dust with craters | Glowing teal | Pink stardust | A starry void | Crystal spires, glowing pods, moon rocks |
| `neon` | Dark violet on a magenta grid | Indigo with neon outlines | Neon yellow | Electric blue | Neon palms, light orbs, wireframe cubes |
| `medieval` | Olive meadow with worn patches | Muted greens, flagstone tees | Straw and earth | A dark moat | Pines and oaks, hay bales, stone turrets |

`courses.json` records each course's `theme`, and the game sets the page colour round the picture to match.

## Tile-built courses

Holes can also be put together from tiles instead of GPS data. A recipe in `data/recipes/<course>.json` lists each hole's **core tiles** and the **feature modules** that sit on them; `tools/compose_hole.py` turns it into ordinary `data/<course>-NN.json` files (made-up GPS points, a centre line, hills, green slopes and a drawn map), and the normal build renders them:

```bash
python3 tools/compose_hole.py data/recipes/patchwork.json          # or add hole numbers: ... patchwork.json 3 7
bash tools/build_round.sh patchwork "Patchwork Park"
```

**Patchwork Park** (`patchwork`, 9 holes) is the test course and uses every tile and module.

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

A local page for adjusting holes on a satellite map, then rebuilding them:

```bash
python3 tools/course_editor.py
# open http://localhost:8790
```

- Pick a course and hole, then drag the **T**ee, **L**ayup and **G**reen markers. The dashed line is the centre line the fairway is built along (it always passes through the layup point), with a rough fairway corridor and green drawn round it.
- Set par, stroke index and the three yardages. *Use for yellow* copies the length measured along the line.
- **Save & rebuild** writes `data/<course>-NN.json` and rebuilds that hole into `game/courses/` (about 3 minutes; one build at a time), then updates `courses.json`. The picture on the right refreshes when it's done, and *Play the game* opens it at `/game/`.
- The first save of a hole keeps the original data in `build/editor-backups/<hole>.orig.json`; *Restore original* puts it back.
- The elevation grid is laid along the original tee→green line (the orange box). Moving the tee or green more than about 15 m stretches the hills and green slopes, and the editor warns you.
- **Features:** by default the fairway, bunkers, water and treeline are placed by the renderer's rules (they aren't read from the photo, so a rule-made stream can land on a cart path). To set them yourself, choose *Start from automatic layout* (loads the rule-made shapes so you can fix them) or *Start empty*, then draw fairway, green, bunker, water and woods shapes and place single trees. *Reshape*, *Move* and *Delete* edit what's drawn. Once a hole has a drawn map, only the drawn bunkers and water are used; a drawn fairway replaces the generated one (the first cut is a band round it), a drawn green replaces the standard oval, and woods are filled with trees. *Automatic treeline as well* keeps the rule-made treeline beside the fairway. The map is saved as `map` in the hole's data file; *Go back to automatic features* removes it.

Bump `VERSION` in `game/sw.js` before deploying rebuilt holes.

## Assumptions to check

- **Hole elevation grid:** read the way the Pure Golf app builds it (`generateHoleGrid`): columns 18 m apart either side of the tee→green line, rows evenly spaced from the tee to 20 m past the green.
- **Layout is approximate on purpose:** fairways follow a curve from the tee through the layup point to the green; greens are a standard rounded oval (26–32 m long) centred on the GPS green point, because the GPS front/back points vary too much; bunkers, water and trees are procedural, not mapped.
- **Green grid:** read as north-up. If it's actually aligned with the hole, every green break is rotated.
