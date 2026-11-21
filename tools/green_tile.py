"""Renders a sharp tile of just the green (and a few metres round it) for a built hole, so it stays crisp when the
game zooms right in for putting. The tile is drawn at GREEN_K (default 12) times the base picture, against the
detail tile's 4x, and the green's heat map and contour lines are re-rendered at the same resolution.

    python3 tools/green_tile.py data/tilgate-forest-01.json game/courses/tilgate-forest/01/
    python3 tools/green_tile.py hole.json .          # build_course.sh, in the build folder

Writes green_land.jpg / green_portrait.jpg and green_<o>_heat.png / green_<o>_contours.png into the hole folder and
adds "gtile" (and the new "heat" entry) to game_data.json / game_data_portrait.json. Run tools/reheat.py afterwards
to redraw the heat map in the game's style."""
import json, math, os, subprocess, sys, tempfile
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
K = float(os.environ.get("GREEN_K", "12"))
PAD_M = 6.0          # metres of fringe round the green's outline


def green_tile(hole_json, hole_dir):
    hole_json = os.path.abspath(hole_json); hole_dir = os.path.abspath(hole_dir)
    for o, data_name, portrait in (("land", "game_data.json", "0"), ("portrait", "game_data_portrait.json", "1")):
        dp = os.path.join(hole_dir, data_name)
        d = json.load(open(dp))
        A = d["A"]; ppm = math.sqrt(abs(A[0][0] * A[1][1] - A[0][1] * A[1][0]))
        hx, hy, hw, hh = (d["heat"][k] for k in ("x", "y", "w", "h"))   # the green's box (from the detail render)
        pad = PAD_M * ppm; W, H = d["img"]
        x0, y0 = max(0, hx - pad), max(0, hy - pad)
        w, h = min(hw + 2 * pad, W - x0), min(hh + 2 * pad, H - y0)
        with tempfile.TemporaryDirectory() as tmp:
            out_png = os.path.join(tmp, f"green_{o}.png"); out_json = os.path.join(tmp, f"green_{o}.json")
            env = dict(os.environ, GAME="1", PORTRAIT=portrait, DETAIL=f"{x0:.2f},{y0:.2f},{w:.2f},{h:.2f}",
                       DETAIL_K=str(K), SS="1")
            subprocess.run([sys.executable, os.path.join(ROOT, "tools", "render_hole_toon.py"), hole_json, out_png, out_json],
                           env=env, check=True, cwd=tmp, stdout=subprocess.DEVNULL)
            det = json.load(open(out_json))
            Image.open(out_png).convert("RGB").save(os.path.join(hole_dir, f"green_{o}.jpg"), quality=88)
            for f in (det["heat"]["file"], det["heat"]["contours"]):
                os.replace(os.path.join(tmp, f), os.path.join(hole_dir, f))
        tile = det["tile"]; tile["file"] = f"green_{o}.jpg"
        d["gtile"] = tile; d["heat"] = det["heat"]
        json.dump(d, open(dp, "w"))
        # a stale outline backup (from the old, lower-res heat image) would be the wrong size: drop it
        games = os.path.join(ROOT, "game", "courses")
        if hole_dir.startswith(games + os.sep):
            keep = os.path.join(ROOT, "build", "heat-backup", os.path.relpath(hole_dir, games), det["heat"]["file"])
            if os.path.exists(keep): os.remove(keep)
        print(f"{hole_dir} {o}: green tile {Image.open(os.path.join(hole_dir, tile['file'])).size}")


if __name__ == "__main__":
    green_tile(sys.argv[1], sys.argv[2])
