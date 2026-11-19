# BattleGolf

A tap-timing golf game played on cartoon, faux-isometric holes built from real courses. Each hole's shape and distances come from Pure Golf's own hole data (GPS tee, layup and green points, plus elevation grids); the details are procedural: standard-size greens, bunkers, ponds, streams and treelines, placed by simple rules seeded per hole so a hole always comes out the same. The course is **Tilgate Forest** (18 holes).

## Play

Serve the `game/` folder with any static server and open `index.html`:

```bash
cd game && python3 -m http.server 8765
# open http://localhost:8765
```

1. **Distance:** the target moves out from the ball and back, speeding up the further out it goes. Tap to lock it.
2. **Direction:** the target swings side to side. Tap when it's on the line.
3. **Aim:** tap the yellow AIM buttons (or ← →) to nudge your aim before the first tap; hold to keep turning slowly. Tee shots follow the fairway centre line, so they curve with the dogleg.
4. **Putting:** the green shows a slope heat map (blue low → red high, 5 cm contours) with downhill arrows. Putts are simulated with friction and gravity, so they break with the slope.
5. **Gimmes:** a ball resting within 1 m of the cup is holed for +1 stroke; within 2 m, +2.
6. **Rounds:** pick a course and play 18 holes, the front or back 9, or a single hole. A card after each hole shows your score and the running total to par; the next hole loads while you look at it.
7. **Hazards:** bunkers are a sand lie (short, wilder shots), and water (ponds and streams) costs a stroke with a drop back along the line the ball came in on.
8. **Pass-and-play:** pick 1–4 players and their names on the start screen. Everyone tees off in order, then whoever is furthest from the hole plays next. A "pass the phone" screen appears whenever the turn moves to someone else, and the scorecard ranks everyone at the end. Each player's ball is drawn in their colour.

9. **Online:** enter your name and tap *Create match* to get a 5-letter code and a link to share; friends join with the code or link (up to 4). The match uses the course and holes picked on the start screen. Everyone plays their own round on their own phone whenever they like. Other players' shots replay on your screen as ghost balls, the scoreboard updates live, and the final scorecard appears once everyone has holed out. Closing the app is fine: opening the link again picks up where you left off.

The lie changes the maximum carry and the side-to-side swing: tee 260 yds, fairway 230, first cut 205, rough 175, bunker 120, trees 90. Off the map costs a penalty stroke.

## Formats

With 2 or more players, choose the format on the setup screen:

- **Stroke play:** fewest strokes over the round wins.
- **Match play** (1 v 1): each hole goes to the lower score, and a tie halves it. The match ends as soon as one player is more holes up than there are holes left (for example "won 3&2"). Online, the first two to join play the match.
- **Skins:** each hole is worth a skin. The lowest score on its own takes it, plus any skins carried over; a tie carries the skin to the next hole. Most skins wins.

Online formats need `supabase/migrations/20261119190000_battlegolf_formats.sql`.

## Battle mode

Turn on **Battle mode** on the setup screen for a 1 v 1 fight over 9 or 18 holes, with the same rules as Pure Golf's battles:

- The round is split into **three bouts** of equal length (6 holes each over 18, 3 over 9). Both players start every bout on full health: one point per hole of the bout.
- Each hole is scored in **Stableford points** (2 for par, 1 more per stroke under, 0 at double bogey or worse). The difference is the damage the loser takes. Hitting 0 health loses the bout on the spot (a knockout); otherwise the healthier player takes it.
- **Most bouts wins**; total damage dealt breaks a tie.
- **Power-ups** (3 to 8 each) are fixed to holes before the round. **Dealt** gives both players the same kinds, spread evenly over the bouts, each on their own random holes. **Pick your own** lets each player choose kinds and holes, one per hole, before their first shot.
- The 11 power-ups are Double Down, Shield, Heal, Critical Hit, Leech, Sniper, Poison, Block, Last Stand, Counter and Second Wind. Each one is explained in the game.

The rules engine (`battlePlay` in `game/index.html`) is a straight port of Pure Golf's `BattleScoring.play`. It was cross-checked against the Dart code on thousands of random cards.

Online battles are always 1 v 1 and need `supabase/migrations/20261119180000_battlegolf_battles.sql`. That migration deals power-ups in the database and checks picked sets.

## Online play and the phone app

Online matches use the BattleGolf Supabase project (URL and publishable key in `game/config.js`). Set it up once by running the files in `supabase/migrations/` in order in that project's SQL editor. There are no accounts: each phone keeps a random secret per match, the tables are read-only to the app, and the only writes are the `bg_create_match`, `bg_join_match` and `bg_add_shot` functions. Never put the service_role key in `config.js`.

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
| `tools/build_course.sh` | Builds one hole's assets from a file in `data/` |
| `tools/build_round.sh` | Builds every hole of a course into `game/courses/<course>/` and updates `courses.json` |
| `tools/render_hole.py` | The earlier top-down (non-cartoon) renderer |
| `tools/playtest.py` | Headless Playwright playtest that taps through rounds and screenshots the green |

## Rebuild the course assets

Needs Python 3 with `numpy`, `scipy` and `Pillow`.

```bash
bash tools/build_round.sh tilgate-forest "Tilgate Forest"      # all 18 holes, ~3 min each, 4 at a time
```

Adding a course: export its holes from Pure Golf into `data/<course>-01.json` … (same fields as the existing files), then build it. Bump `VERSION` in `game/sw.js` afterwards.

## Assumptions to check

- **Hole elevation grid:** read the way the Pure Golf app builds it (`generateHoleGrid`): columns 18 m apart either side of the tee→green line, rows evenly spaced from the tee to 20 m past the green.
- **Layout is approximate on purpose:** fairways follow a curve from the tee through the layup point to the green; greens are a standard rounded oval (26–32 m long) centred on the GPS green point, because the GPS front/back points vary too much; bunkers, water and trees are procedural, not mapped.
- **Green grid:** read as north-up. If it's actually aligned with the hole, every green break is rotated.
