#!/usr/bin/env python3
"""Turn the pin-flag sprite sheet (SVG + JSON) into the game's flag asset.

    python3 tools/flag_sprites.py ~/Downloads/flag_spritesheet.svg ~/Downloads/flag_spritesheet.json

Writes game/sprites/flag.svg and game/sprites/flag.json. The game draws the cup itself (it grows while putting so
the hole stays easy to see), so each cell's baked hole is stripped here. The flag cloth is hundreds of tiny shaded
polygons per frame; their shared stroke settings move into one style rule and coordinates drop to one decimal,
which roughly halves the file without any visible change at the sizes the game draws it.
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

head, *cells = re.split(r'(?=<g transform="translate\(\d+ \d+\)">)', svg)
cells[-1] = cells[-1].replace("</svg>", "")
HOLE = re.compile(r'<ellipse cx="100" cy="168" rx="15" ry="7.5" fill="#1B2433"/><ellipse cx="100" cy="169" rx="11" ry="5" fill="#0b1018"/>')
POLY = re.compile(r'<polygon points="([^"]+)" fill="(#[0-9a-fA-F]+)" stroke="\2" stroke-width="0.7" stroke-linejoin="round"/>')


def pts(s):
    return " ".join(",".join(f"{float(v):.1f}".rstrip("0").rstrip(".") for v in p.split(",")) for p in s.split())


kept = []
for c in cells:
    c, n = HOLE.subn("", c, count=1)
    assert n == 1, "no hole in a cell"
    c = POLY.sub(lambda m: f'<polygon points="{pts(m.group(1))}" fill="{m.group(2)}" stroke="{m.group(2)}"/>', c)
    kept.append(c)
style = "<style>polygon{stroke-width:.7;stroke-linejoin:round}</style>"
(out / "flag.svg").write_text(head + style + "".join(kept) + "</svg>\n")

rows = sorted(meta["animations"].items(), key=lambda kv: kv[1]["row"])
info = {
    "cell": [cw, ch],
    "anchor": meta["anchor_hole"],   # the foot of the pole, where it stands in the cup
    "top": 55.5,                     # the pole's cap, for scaling the drawn height
    "frames": len(rows[0][1]["frames"]),
    "fps": meta.get("fps_suggested", 12),
    "rows": [name for name, _ in rows],
}
(out / "flag.json").write_text(json.dumps(info, separators=(",", ":")) + "\n")
print(f"wrote {out/'flag.svg'} ({(out/'flag.svg').stat().st_size // 1024} KB) and flag.json, {len(rows)} rows x {info['frames']}")
