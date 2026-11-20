"""Adds/updates a course in game/courses/courses.json from its data/<course>-NN.json files."""
import glob, json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
course, name = sys.argv[1], sys.argv[2]
holes = []; theme = None
for f in sorted(glob.glob(f"{ROOT}/data/{course}-[0-9]*.json")):
    h = json.load(open(f)); n = f.rsplit("-", 1)[1][:-5]; theme = h.get("theme", theme)
    if os.path.exists(f"{ROOT}/game/courses/{course}/{n}/game_data.json"):
        holes.append(dict(n=h["hole"], dir=n, par=h["par"], yards=h["yards_yellow"], si=h.get("si")))
idx_path = f"{ROOT}/game/courses/courses.json"
idx = json.load(open(idx_path)) if os.path.exists(idx_path) else []
entry = dict(id=course, name=name, holes=holes, **({"theme": theme} if theme else {}))
at = next((i for i, c in enumerate(idx) if c["id"] == course), None)      # a rebuilt course keeps its place
if at is None: idx.append(entry)
else: idx[at] = entry
json.dump(idx, open(idx_path, "w"), indent=1)
print(f"{name}: {len(holes)} holes in {idx_path}")
