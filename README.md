# BattleGolf

A tap-timing golf game played on cartoon, faux-isometric holes generated from Pure Golf's own course data (tee, layup, green front/centre/back and elevation grids). The test hole is Abbey Hill hole 13 (par 4, 369 yds).

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
6. **Pass-and-play:** pick 1–4 players and their names on the start screen. Everyone tees off in order, then whoever is furthest from the hole plays next. A "pass the phone" screen appears whenever the turn moves to someone else, and the scorecard ranks everyone at the end. Each player's ball is drawn in their colour.

The lie changes the maximum carry and the side-to-side swing: tee 260 yds, fairway 230, first cut 205, rough 175, trees 90. Off the map costs a penalty stroke.

## Layout

| Path | What it is |
| --- | --- |
| `game/` | The playable game: `index.html` plus generated course images, detail tiles, heat maps and game data (portrait and landscape) |
| `data/` | Hole input data exported from the Pure Golf `holes` table |
| `tools/render_hole_toon.py` | Renders the cartoon hole, the 4× detail tile around the green, the green heat map, and the game data (lie grid, trees, camera transform, green elevation) |
| `tools/build_course.sh` | Rebuilds every asset in `game/` from a hole in `data/` |
| `tools/render_hole.py` | The earlier top-down (non-cartoon) renderer |
| `tools/playtest.py` | Headless Playwright playtest that taps through rounds and screenshots the green |

## Rebuild the course assets

Needs Python 3 with `numpy`, `scipy` and `Pillow`.

```bash
bash tools/build_course.sh                        # uses data/abbey-hill-13.json
HOLE=my-hole bash tools/build_course.sh           # uses data/my-hole.json
```

## Assumptions to check

- **Hole elevation grid:** read as 12 rows from tee to green × 21 columns across the hole, with 10 m between columns.
- **Green elevation grid:** 41 × 41 at 2 m, int16 centimetres, assumed **north-up**. If it's actually aligned with the hole, every green break is rotated.
- **Fairway, trees and rough:** generated, not mapped. There are no bunkers or water, because the data has none yet.
