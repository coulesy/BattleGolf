#!/usr/bin/env python3
"""Turn the golf-ball sprite sheet (SVG + JSON) into the game's ball asset.

    python3 tools/ball_sprites.py ~/Downloads/golfball_spritesheet.svg ~/Downloads/golfball_spritesheet.json

Writes game/sprites/ball.svg and game/sprites/ball.json. The game draws its own shadow (it has to slide away from the
ball and shrink as the ball climbs), so each cell's baked ground shadow is stripped here, and the ball's centre in
each cell is recorded so the air frames, whose bounce height is baked in, can be pinned to the real flight height.
"""
import json
import re
import sys
from pathlib import Path

svg_path, json_path = Path(sys.argv[1]), Path(sys.argv[2])
out = Path(__file__).resolve().parent.parent / "game" / "sprites"
svg = svg_path.read_text()
meta = json.loads(json_path.read_text())
cw, ch = meta["cell"]

# every cell is a top-level <g transform="translate(x y)"> group
head, *cells = re.split(r'(?=<g transform="translate\(\d+ \d+\)">)', svg)
cells[-1] = cells[-1].replace("</svg>", "")
SHADOW = re.compile(r'<ellipse cx="80" cy="138" rx="[\d.]+" ry="[\d.]+" fill="#1B2433" opacity="[\d.]+"/>')
centres = {}
kept = []
for c in cells:
    x, y = map(int, re.match(r'<g transform="translate\((\d+) (\d+)\)">', c).groups())
    c, n = SHADOW.subn("", c, count=1)
    assert n == 1, f"no shadow in cell {x},{y}"
    # no squash and stretch in the air: the ball stays round and only the speed lines show it moving. The landing
    # frames (0: settling, 6: the thump) keep their squash.
    if x // cw not in (0, 6):
        c = re.sub(r'scale\([\d.]+ [\d.]+\)', "scale(1.000 1.000)", c)
        c = re.sub(r'(<ellipse cx="[\d.]+" cy="[\d.]+" )rx="[\d.]+" ry="[\d.]+"( transform="rotate\([^"]*\)" fill="none" stroke="#1B2433" stroke-width="3.2"/>)',
                   r'\1rx="30.00" ry="30.00"\2', c)
    by = float(re.search(r'<g transform="translate\(80\.00 ([\d.]+)\)', c).group(1))
    centres[(x // cw, y // ch)] = round(by, 2)
    kept.append(c)
(out).mkdir(parents=True, exist_ok=True)
(out / "ball.svg").write_text(head + "".join(kept) + "</svg>\n")

rows = sorted(meta["animations"].items(), key=lambda kv: kv[1]["row"])
cols = len(rows[0][1]["frames"])
info = {
    "cell": [cw, ch],
    "ballR": 30,                     # the ball's radius in a cell, unsquashed
    "cx": 80,
    "rows": [name for name, _ in rows],
    "cy": [[centres[(i, r)] for i in range(cols)] for r in range(len(rows))],   # ball centre per row, per frame
}
(out / "ball.json").write_text(json.dumps(info, separators=(",", ":")) + "\n")
print(f"wrote {out/'ball.svg'} ({(out/'ball.svg').stat().st_size // 1024} KB) and ball.json, {len(rows)} rows x {cols}")
