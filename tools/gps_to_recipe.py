"""Converts a GPS course (its original GPS hole files: data/gps/<course>-NN.json once converted, else data/<course>-NN.json) into a tile recipe for the modular system (compose_hole.py).

    python3 tools/gps_to_recipe.py tilgate-forest                  # writes data/recipes/tilgate-forest-tiles.json
    python3 tools/gps_to_recipe.py tilgate-forest --id tilgate      # choose the new course id

What carries over, per hole:
  * routing: the GPS centre line (the curve from the tee through the layup to the green) is matched by tile lengths
    and turns, fitted so the composed centre line follows it; the heading is kept
  * hazards: the renderer's rule-placed bunkers, ponds and streams (or a hand-drawn map's bunkers and water) become
    bunker / lake / stream modules on the matching tile and spot; the automatic treeline stays on
  * ground: the real elevation along the centre line picks each fairway's slope preset, the tee height and green height
  * green: the real green surface picks the nearest green slope preset
Real hills away from the centre line and the exact green contours are not kept: tiles only have presets for those.
Prints how closely each hole matches (centre line and green position, metres).
"""
import base64, json, math, os, subprocess, sys, tempfile
import numpy as np
from scipy.optimize import minimize

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, f"{ROOT}/tools")
import compose_hole as C

YD = 0.9144


def frame_m(origin):
    lat0, lng0 = origin
    kx, ky = math.cos(math.radians(lat0)) * 111320.0, 110540.0
    return lambda p: np.array([(p[1] - lng0) * kx, (p[0] - lat0) * ky])


def gps_curve(h):
    """the renderer's centre line: a quadratic curve tee -> (through the layup) -> green, metres from the tee"""
    m = frame_m(h["tee"]); T, L, G = m(h["tee"]), m(h["layup"]), m(h["green"])
    if h.get("path"):
        P = np.array([m(q) for q in h["path"]])
    else:
        Cc = 2 * L - (T + G) / 2; t = np.linspace(0, 1, 600)[:, None]
        P = (1 - t) ** 2 * T + 2 * t * (1 - t) * Cc + t ** 2 * G
    arc = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(P, axis=0), axis=1))])
    return P, arc


def resample(P, arc, n=60):
    ts = np.linspace(0, arc[-1], n)
    return np.stack([np.interp(ts, arc, P[:, 0]), np.interp(ts, arc, P[:, 1])], 1)


def heading_at(P, i0, i1):
    d = P[i1] - P[i0]; return math.degrees(math.atan2(d[0], d[1]))


# ---------------- routing ----------------
def fit_route(h, P, arc):
    """tile list + heading whose composed centre line best follows the GPS one"""
    par, total = h["par"], float(arc[-1])
    head = heading_at(P, 0, 8)
    target = resample(P, arc)
    if par == 3:
        lens = [max(total - 40, 60), 40]
    else:
        nf = par - 3; fw = (total - 55 - 40) / nf
        if fw < 70: fw = 70
        lens = [55] + [fw] * nf + [max(total - 55 - fw * nf, 15)]

    def tiles_from(x):
        tl = []
        for i, L in enumerate(lens):
            kind = "tee" if i == 0 else "green" if i == len(lens) - 1 else "fairway"
            t = {"t": kind, "len": round(float(L), 1)}
            a = float(x[i]); c = float(np.clip(x[len(lens) + i], 0.15, 0.85)) if kind == "fairway" else None
            if abs(a) >= 0.5: t["turn"] = round(a, 1)
            if kind == "fairway" and "turn" in t: t["corner"] = round(c, 2)
            tl.append(t)
        return tl

    def path_of(tiles):
        hole = C.Hole({"tiles": tiles, "heading": head}, 1, 0)
        return resample(hole.P, hole.arc)

    def cost(x):
        Q = path_of(tiles_from(x))
        return float(np.mean(np.sum((Q - target) ** 2, 1))) + 0.002 * float(np.sum(np.square(x[:len(lens)])))

    # start from the GPS curve's own heading change over each tile, then refine
    x0 = np.zeros(2 * len(lens)); x0[len(lens):] = 0.5
    s = 0.0; k = total / sum(lens)
    def head_s(sv):
        i = int(np.clip(np.searchsorted(arc, sv), 1, len(arc) - 1)); d = P[i] - P[i - 1]; return math.degrees(math.atan2(d[0], d[1]))
    for i, L in enumerate(lens):
        a_, b_ = s * k, (s + L) * k; s += L
        x0[i] = (head_s(min(b_, total - 1)) - head_s(max(a_, 1)) + 180) % 360 - 180
    simplex = [x0] + [x0 + np.eye(len(x0))[j] * (12 if j < len(lens) else 0.2) for j in range(len(x0))]
    best = minimize(cost, x0, method="Nelder-Mead", options=dict(maxiter=3000, xatol=0.05, fatol=0.01, initial_simplex=simplex))
    tiles = tiles_from(best.x)
    Q = path_of(tiles); dev = np.linalg.norm(Q - target, axis=1)
    return tiles, round(head, 1), float(dev.max()), float(dev[-1])


# ---------------- ground ----------------
def ground_along(h, P):
    """real ground height (m) at points P (metres from the tee), from the hole's elevation grid"""
    m = frame_m(h["tee"]); G = m(h["green"]); D = float(np.linalg.norm(G)); gtotal = D + 20
    half = min(max(math.floor(gtotal / 2 / 18 + 0.5), 1), 12); cols = 2 * half + 1
    g = np.array(h["grid"], float); rows = len(g) // cols; g = g[:rows * cols].reshape(rows, cols)
    a = G / D; r = np.array([a[1], -a[0]])
    along = P @ a / gtotal * (rows - 1); across = P @ r / 18 + half
    from scipy.ndimage import map_coordinates
    return map_coordinates(g, [np.clip(along, 0, rows - 1), np.clip(across, 0, cols - 1)], order=1, mode="nearest")


def fit_ground(h, tiles, P, arc):
    z = ground_along(h, P)
    zs = lambda s: float(np.interp(s, arc, z))
    s = 0.0; starts = []
    for t in tiles: starts.append((s, s + t["len"], t)); s += t["len"]
    scale = arc[-1] / s                              # composed and GPS lengths differ a little
    notes = []
    for a, b, t in starts:
        a, b = a * scale, b * scale
        if t["t"] == "fairway":
            rise = zs(b) - zs(a); mid = zs((a + b) / 2) - (zs(a) + zs(b)) / 2
            if rise > 3: t["slope"] = "uphill"
            elif rise < -3: t["slope"] = "downhill"
            elif mid > 2: t["slope"] = "ridge"
            elif mid < -2: t["slope"] = "valley"
            notes.append(f"{t.get('slope', 'flat')} ({rise:+.1f} m)")
        elif t["t"] == "tee" and h["par"] > 3:
            drop = zs(0) - zs(b + 15)
            if drop > 6: t["elev"] = "elevated"
            elif drop > 2: t["elev"] = "raised"
        elif t["t"] == "tee":
            drop = zs(0) - zs(arc[-1])
            if drop > 6: t["elev"] = "elevated"
            elif drop > 2: t["elev"] = "raised"
    gz = zs(arc[-1]) - zs(max(arc[-1] - 30, 0))
    if gz > 1.5: tiles[-1]["elev"] = "raised"
    elif gz < -1.2: tiles[-1]["elev"] = "sunken"
    return notes


# ---------------- green ----------------
def fit_green(h, P):
    gg = h["green_grid"]; n, step = gg["n"], gg["step"]
    z = np.frombuffer(base64.b64decode(gg["cm"]), "<i2").astype(float).reshape(n, n)
    jj, ii = np.meshgrid(np.arange(n), np.arange(n))
    E, N = (jj - (n - 1) / 2) * step, ((n - 1) / 2 - ii) * step
    u = P[-1] - P[-12]; u /= np.linalg.norm(u); v = np.array([u[1], -u[0]])
    gu, gv = E * u[0] + N * u[1], E * v[0] + N * v[1]; rr = np.hypot(gu, gv)
    on = rr < 13
    zr = z[on] - z[on].mean()
    if zr.std() < 6: return "flat", 0.0                     # under ~0.5 % across the green
    shapes = {"back_to_front": 2.2 * gu, "front_to_back": -1.6 * gu, "left_to_right": -2.2 * gv, "right_to_left": 2.2 * gv,
              "crown": -30 * (rr / 14) ** 2, "bowl": 26 * (rr / 14) ** 2, "two_tier": 32 * np.tanh(gu / 2.6) + 1.0 * gu}
    best, score = None, -2
    for k, f in shapes.items():
        fr = f[on] - f[on].mean(); c = float(np.dot(fr, zr) / (np.linalg.norm(fr) * np.linalg.norm(zr) + 1e-9))
        if c > score: best, score = k, c
    return (best, score) if score > 0.3 else ("flat", score)


# ---------------- hazards ----------------
def features_of(h, path):
    """the bunkers and water the renderer places for this hole (or the drawn ones), as polygons in metres"""
    m = frame_m(h["tee"])
    if h.get("map"):
        fm = h["map"]
    else:
        with tempfile.TemporaryDirectory() as tmp:
            json.dump(h, open(f"{tmp}/h.json", "w"))
            r = subprocess.run([sys.executable, f"{ROOT}/tools/render_hole_toon.py", f"{tmp}/h.json", f"{tmp}/auto.json"],
                               env=dict(os.environ, FEATURES_ONLY="1"), cwd=tmp, capture_output=True, text=True)
            if r.returncode: raise RuntimeError(r.stderr[-500:])
            fm = json.load(open(f"{tmp}/auto.json"))
    return {k: [np.array([m(p) for p in P]) for P in fm.get(k, []) if len(P) >= 3] for k in ("bunker", "water", "wood")}


def area(P): x, y = P[:, 0], P[:, 1]; return 0.5 * abs(np.dot(x, np.roll(y, 1)) - np.dot(y, np.roll(x, 1)))


def tile_spans(tiles, total_gps):
    s, out = 0.0, []
    names = C.Hole({"tiles": tiles, "heading": 0}, 1, 0).spans
    order = [nm for nm in ("tee", "fairway1", "fairway2", "green") if nm in names]
    if len(tiles) == 3: order = ["tee", "fairway", "green"]
    comp_total = sum(t["len"] for t in tiles); k = total_gps / comp_total
    for nm, t in zip(order, tiles):
        out.append((nm, s * k, (s + t["len"]) * k)); s += t["len"]
    return out


def modules_for(h, feats, P, arc, tiles):
    from scipy.spatial import cKDTree
    kd = cKDTree(P); G = P[-1]
    u = P[-1] - P[-12]; u /= np.linalg.norm(u)
    spans = tile_spans(tiles, arc[-1])
    def where(s):
        for nm, a, b in spans:
            if a <= s <= b + 1e-6: return nm, (s - a) / max(b - a, 1)
        return spans[-1][0], 1.0
    def side_of(c):
        d, i = kd.query(c); i = int(np.clip(i, 1, len(P) - 1))
        tg = P[i] - P[i - 1]; return ("right" if (tg[0] * (c - P[i])[1] - tg[1] * (c - P[i])[0]) < 0 else "left"), d, float(arc[i])
    mods = []
    size_of = lambda a, med: "small" if a < med * 0.7 else "large" if a > med * 1.5 else None
    for B in feats["bunker"]:
        c = B.mean(0); dg = np.linalg.norm(c - G)
        if dg < 32:                                          # greenside: by direction from the green
            d = (c - G) / (dg + 1e-9)
            ang = math.degrees(math.atan2(u[0] * d[1] - u[1] * d[0], u @ d))     # 0 = behind the green, + = left
            slots = {0: "back", 45: "back_left", 90: "left", 140: "front_left", 180: "front", -140: "front_right", -90: "right", -45: "back_right"}
            k = min(slots, key=lambda a: min(abs(a - ang), 360 - abs(a - ang)))
            mod = {"m": "bunker", "at": f"green.{slots[k]}"}
        else:
            sd, dist, s = side_of(c); nm, pos = where(s)
            if nm == "green": nm, pos = (spans[-2][0], 0.95) if len(spans) > 2 else ("tee", 0.95)
            mod = {"m": "bunker", "at": f"{nm}.{sd if dist > 6 else 'centre'}", "pos": round(pos, 2)}
        sz = size_of(area(B), 115 if mod["at"].startswith("green") else 220)
        if sz: mod["size"] = sz
        mods.append(mod)
    for Wt in feats["water"]:
        c = Wt.mean(0); ext = np.ptp(Wt, axis=0).max()
        sd, dist, s = side_of(c); nm, pos = where(s)
        if ext > 200:                                        # a stream across the hole
            if nm == "green": nm, pos = (spans[-2][0], 0.95)
            mods.append({"m": "stream", "at": f"{nm}.cross", "pos": round(pos, 2)})
        elif dist < 18:                                      # a pond on the line: carry it
            if nm == "green": nm, pos = (spans[-2][0], 0.9)
            mod = {"m": "lake", "at": f"{nm}.cross", "pos": round(pos, 2)}
            sz = size_of(area(Wt), 1100); mods.append(dict(mod, **({"size": sz} if sz else {})))
        else:                                                # a pond beside the fairway
            if nm == "green": nm, pos = (spans[-2][0], 0.95)
            mod = {"m": "lake", "at": f"{nm}.{sd}", "pos": round(pos, 2)}
            if dist < 40: mod["bite"] = True
            sz = size_of(area(Wt), 1600); mods.append(dict(mod, **({"size": sz} if sz else {})))
    for Wd in feats["wood"]:                                 # drawn woods: a copse or a treeline on that side
        c = Wd.mean(0); sd, dist, s = side_of(c); nm, pos = where(s)
        mods.append({"m": "copse", "at": "green.back"} if nm == "green" and np.linalg.norm(c - G) < 60 else {"m": "treeline", "at": f"{(spans[-2][0] if nm == 'green' and len(spans) > 2 else nm)}.{sd}"})
    return mods


def convert(cid, new_id):
    ours = lambda d: sorted(f for f in os.listdir(d) if f.startswith(cid + "-") and f[len(cid) + 1:-5].isdigit())
    GPS = f"{ROOT}/data/gps"                             # archived originals of courses already converted
    if not (os.path.isdir(GPS) and ours(GPS)): GPS = f"{ROOT}/data"
    files = ours(GPS)
    if not files: raise SystemExit(f"no GPS hole files for {cid} in data/gps/ or data/")
    if "tiles" in json.load(open(f"{GPS}/{files[0]}")): raise SystemExit(f"data/{cid}-NN.json are already composed from tiles; the GPS originals belong in data/gps/")
    names = {}
    try: names = {c["id"]: c for c in json.load(open(f"{ROOT}/game/courses/courses.json"))}
    except OSError: pass
    holes, report = [], []
    theme = "classic"
    for f in files:
        h = json.load(open(f"{GPS}/{f}")); theme = h.get("theme", theme)
        P, arc = gps_curve(h)
        tiles, head, dev_max, dev_green = fit_route(h, P, arc)
        slopes = fit_ground(h, tiles, P, arc)
        gs, gscore = fit_green(h, P)
        if gs != "back_to_front": tiles[-1]["slope"] = gs
        feats = features_of(h, P)
        mods = modules_for(h, feats, P, arc, tiles)
        rec = {"tiles": tiles, "modules": mods, "heading": head, "auto_trees": True}
        if h.get("si"): rec["si"] = h["si"]
        holes.append(rec)
        comp = C.Hole(rec, 1, 0); yds = comp.total / YD
        report.append(dict(n=h["hole"], par=h["par"], card=h["yards_yellow"], gps_yds=round(arc[-1] / YD), tiles_yds=round(yds),
                           dev=round(dev_max, 1), green_off=round(dev_green, 1), green=gs, ground=slopes,
                           bunkers=sum(m["m"] == "bunker" for m in mods), water=sum(m["m"] in ("lake", "stream") for m in mods),
                           drawn=bool(h.get("map"))))
    name = names.get(cid, {}).get("name") or json.load(open(f"{GPS}/{files[0]}")).get("course", cid)
    recipe = {"id": new_id, "name": f"{name} (tiles)", "theme": theme, "holes": holes}
    os.makedirs(f"{ROOT}/data/recipes", exist_ok=True)
    s = json.dumps({k: v for k, v in recipe.items() if k != "holes"}, indent=1)[:-2] + ',\n "holes": [\n'
    s += ",\n\n".join("  " + json.dumps(x) for x in holes) + "\n ]\n}\n"
    open(f"{ROOT}/data/recipes/{new_id}.json", "w").write(s)
    return recipe, report


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a: print(__doc__); sys.exit(1)
    cid = a[0]; new_id = a[a.index("--id") + 1] if "--id" in a else f"{cid}-tiles"
    recipe, rep = convert(cid, new_id)
    print(f"{recipe['name']} -> data/recipes/{new_id}.json")
    for r in rep:
        print(f" {r['n']:2} par {r['par']}  card {r['card']:3}  gps {r['gps_yds']:3}  tiles {r['tiles_yds']:3} yds  "
              f"line off by <= {r['dev']:4.1f} m (green {r['green_off']:4.1f} m)  green {r['green']:13}  "
              f"fairways {', '.join(r['ground']) or '-':28}  {r['bunkers']} bunkers {r['water']} water{'  (drawn map)' if r['drawn'] else ''}")
    json.dump(rep, open(f"{ROOT}/build/convert-{cid}.json", "w"), indent=1)
