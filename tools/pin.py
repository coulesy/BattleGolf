"""Choose where the flag goes on a green: somewhere a ball can actually stop near the hole.

The GPS green point can sit on a steep bank; in the game a ball can't come to rest on anything steeper than
about 8.6 %, so a pin there can't be got close to. This picks a spot well inside the green whose slope, and the
slope of the ground around it, is gentle, preferring spots near the middle.

Used by build_course.sh after each build, and on its own to re-pin already built holes:
    python3 tools/pin.py game/courses/*/*/
"""
import base64, json, math, sys
import numpy as np
from scipy.ndimage import binary_erosion


def height_fn(d, centre):
    """Same sampling as the game's heightAt(): green grid (cm, north-up, `step` m cells) centred on `centre`."""
    gg = d["green_grid"]; n, step = gg["n"], gg["step"]
    cm = np.asarray(gg["cm"], float).reshape(n, n)
    c, s = math.cos(-d["north_rot"]), math.sin(-d["north_rot"])
    def h(x, y):
        xg, yg = np.asarray(x) - centre[0], np.asarray(y) - centre[1]
        E, N = c * xg - s * yg, s * xg + c * yg
        gi = np.clip((n - 1) / 2 - N / step, 0, n - 1.001); gj = np.clip((n - 1) / 2 + E / step, 0, n - 1.001)
        i, j = gi.astype(int), gj.astype(int); fi, fj = gi - i, gj - j
        v = lambda a, b: cm[a, b]
        return ((v(i, j) * (1 - fj) + v(i, j + 1) * fj) * (1 - fi) + (v(i + 1, j) * (1 - fj) + v(i + 1, j + 1) * fj) * fi) / 100
    return h


def choose_pin(d):
    """Returns (pin [x, y], its slope, worst slope within 2.5 m) in hole-frame metres."""
    centre = d.get("gcen", d["pin"])
    h = height_fn(d, centre)
    lie = np.frombuffer(base64.b64decode(d["lie"]), np.uint8).reshape(d["ny"], d["nx"])
    inner = binary_erosion(lie == 3, iterations=2)          # at least ~4 m in from the green's edge
    if not inner.any(): inner = lie == 3
    js, is_ = np.nonzero(inner)
    xs = d["gx0"] + (is_ + 0.5) * d["cell"]; ys = d["gy0"] + (js + 0.5) * d["cell"]
    def slope(x, y, e=0.3):
        return np.hypot((h(x + e, y) - h(x - e, y)) / (2 * e), (h(x, y + e) - h(x, y - e)) / (2 * e))
    s0 = slope(xs, ys)
    ring = [slope(xs + r * math.cos(a), ys + r * math.sin(a)) for r in (1.2, 2.5) for a in np.linspace(0, 2 * math.pi, 8, endpoint=False)]
    worst = np.max(ring, axis=0)
    off = np.hypot(xs - centre[0], ys - centre[1])
    # gentle under the hole and round it; mildly prefer the middle of the green
    score = s0 * 2 + worst + 0.002 * off + 0.5 * np.clip(worst - 0.05, 0, None)
    k = int(np.argmin(score))
    return [round(float(xs[k]), 2), round(float(ys[k]), 2)], float(s0[k]), float(worst[k])


def repin(hole_dir):
    """Re-pins one built hole; landscape and portrait get the same pin (online phones may differ)."""
    paths = [f"{hole_dir}/game_data.json", f"{hole_dir}/game_data_portrait.json"]
    ds = [json.load(open(p)) for p in paths]
    for d in ds: d.setdefault("gcen", d["pin"])          # green grid stays centred on the GPS green point
    old = ds[0]["pin"]
    new, s, w = choose_pin(ds[0])
    for d, p in zip(ds, paths):
        d["pin"] = new; json.dump(d, open(p, "w"))
    return old, new, s, w


if __name__ == "__main__":
    for hd in sys.argv[1:]:
        old, new, s, w = repin(hd.rstrip("/"))
        print(f"{hd}: moved {math.hypot(new[0] - old[0], new[1] - old[1]):.1f} m · slope {s * 100:.1f}% · worst nearby {w * 100:.1f}%")
