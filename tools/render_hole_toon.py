"""Cartoon / faux-isometric render of one hole from Pure Golf point data.
Same inputs as render_hole.py (tee, layup, green front/centre/back, elevation grids)."""
import json, base64, sys, math
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps
from scipy.ndimage import gaussian_filter, map_coordinates, binary_erosion, distance_transform_edt
from scipy.spatial import cKDTree

src, out = sys.argv[1], sys.argv[2]
H = json.load(open(src))
rng = np.random.default_rng(7)

# ---------------- themes: same holes and rules, different paint and props ----------------
# THEME=<name> or "theme" in the hole file. Each entry: three hill bands (shadow, mid, lit) for the ground,
# two stripes for mown grass, and the outline colours. Props are drawn per theme further down.
import os as _os
THEME = _os.environ.get("THEME") or H.get("theme", "classic")
PALETTES = {
    "classic": dict(rough=("#4f9e2a", "#62b434", "#74c63e"), cut=("#3f8a24", "#4b9a2b", "#56a831"),
                    wood=("#3a7a22", "#438727", "#4c912b"), fair=("#8fd64a", "#7cc83c"), green=("#b2ec66", "#a5e25c"),
                    tee=("#9ee056", "#8ad24a"), sand=("#e2c46e", "#efd486", "#f7e3a0"), water=("#7ad2f5", "#45aee6"),
                    ink="#2d5f1a", l_fair="#3c7e22", l_green="#4f9a2b", l_sand="#b48a3c", l_water="#2a6aa0",
                    props=(34, 70, 24), shadow=(30, 70, 20), label=(30, 55, 25)),
    # moon base: grey-violet regolith, glowing teal landing strips, pink stardust bunkers, black-hole "water"
    "space": dict(rough=("#3e3a56", "#4d486a", "#5e5880"), cut=("#332f4a", "#3d3858", "#474166"),
                  wood=("#2c2842", "#34304c", "#3c3756"), fair=("#3cc4d6", "#2fadbf"), green=("#9af5e6", "#86e8d8"),
                  tee=("#c9a2ff", "#b48cf0"), sand=("#c25fb4", "#d77ac9", "#eb9be0"), water=("#1a1638", "#0a0920"),
                  ink="#161328", l_fair="#a6f6ff", l_green="#e6fffb", l_sand="#ffc6f4", l_water="#8a7dff",
                  props=(22, 19, 40), shadow=(10, 8, 24), label=(22, 19, 40)),
    # synthwave night: dark violet ground on a neon grid, glowing outlines
    "neon": dict(rough=("#140b2e", "#1b103c", "#23164a"), cut=("#1f1045", "#271553", "#301b62"),
                 wood=("#170c33", "#1c103d", "#221446"), fair=("#3a1f8c", "#311a78"), green=("#16c98b", "#12b47c"),
                 tee=("#ff4fbf", "#e63aa8"), sand=("#e8a21c", "#f6bd2e", "#ffd94e"), water=("#7fe9ff", "#00a8f0"),
                 ink="#ff2fa8", l_fair="#00f0ff", l_green="#8dffc8", l_sand="#fff07a", l_water="#c6f8ff",
                 props=(10, 4, 26), shadow=(0, 0, 10), label=(60, 10, 70)),
    # castle grounds: olive meadow, straw-and-earth bunkers, a dark moat, flagstone tees
    "medieval": dict(rough=("#55652b", "#657834", "#74893c"), cut=("#475624", "#51622a", "#5b6e30"),
                     wood=("#3f4c20", "#465524", "#4e5e28"), fair=("#9bb04f", "#8ca245"), green=("#bcd166", "#afc55a"),
                     tee=("#bdb299", "#aaa086"), sand=("#9c7442", "#b08850", "#c49c64"), water=("#4c838e", "#2c5c68"),
                     ink="#33341a", l_fair="#5d6f2c", l_green="#6e8a32", l_sand="#6e4e26", l_water="#1c3d46",
                     props=(40, 36, 20), shadow=(30, 34, 14), label=(50, 40, 20)),
}
PAL = PALETTES.get(THEME, PALETTES["classic"])

# ---------------- geometry in "hole frame": tee at origin, green straight up ----------------
lat0, lng0 = H["tee"]
kx, ky = math.cos(math.radians(lat0)) * 111320.0, 110540.0
def to_m(p): return np.array([(p[1] - lng0) * kx, (p[0] - lat0) * ky])
T, L, G = to_m(H["tee"]), to_m(H["layup"]), to_m(H["green"])
GF, GB = to_m(H["green_front"]), to_m(H["green_back"])
axis = (G - T) / np.linalg.norm(G - T)
ang = math.atan2(axis[0], axis[1])
R = np.array([[math.cos(ang), -math.sin(ang)], [math.sin(ang), math.cos(ang)]])
T, L, G, GF, GB = (R @ p for p in (T, L, G, GF, GB))
north_rot = ang
D = np.linalg.norm(G - T)

# ---------------- camera: hole runs bottom-left -> top-right, tilted ----------------
import os
SS = int(os.environ["SS"]) if os.environ.get("SS") else 0.25 if os.environ.get("FEATURES_ONLY") else 2      # the layout export needs no picture, so draw it tiny
PORTRAIT = os.environ.get("PORTRAIT") == "1"
OUT_W, OUT_H = (900, 1600) if PORTRAIT else (1600, 900)
# DETAIL="x,y,w,h" (base-image px) + DETAIL_K renders a sharper tile of part of the same picture
K = float(os.environ.get("DETAIL_K", "1")); DETAIL = os.environ.get("DETAIL")
U = SS * K
W, Hh = int(OUT_W * U), int(OUT_H * U)
if DETAIL:
    dx_, dy_, dw_, dh_ = (float(v) for v in DETAIL.split(","))
    OFFX, OFFY, CW, CH = int(dx_ * U), int(dy_ * U), int(dw_ * U), int(dh_ * U)
else:
    OFFX, OFFY, CW, CH = 0, 0, W, Hh
VIEW = math.radians(66 if PORTRAIT else 38)          # screen angle of tee->green
TILT = 0.72                      # vertical squash = camera tilt
th = VIEW - math.pi / 2
cR = np.array([[math.cos(th), -math.sin(th)], [math.sin(th), math.cos(th)]])
mid = (T + G) / 2
span = D + 70
s = min((W * 0.92) / (span * math.cos(VIEW) + 60), (Hh * 0.86) / (span * math.sin(VIEW) * TILT + 60))
def to_abs(p):
    q = cR @ (np.asarray(p) - mid)
    return np.array([W / 2 + q[0] * s, Hh / 2 + 25 * U - q[1] * s * TILT])
def to_screen(p): return to_abs(p) - np.array([OFFX, OFFY])
def from_abs(px, py):
    qx = (px - W / 2) / s; qy = -(py - Hh / 2 - 25 * U) / (s * TILT)
    inv = cR.T
    return inv[0, 0] * qx + inv[0, 1] * qy + mid[0], inv[1, 0] * qx + inv[1, 1] * qy + mid[1]
def from_screen(px, py): return from_abs(px + OFFX, py + OFFY)

pxg, pyg = np.meshgrid(np.arange(CW) + 0.5, np.arange(CH) + 0.5)
X, Y = from_screen(pxg, pyg)
mpp = 1 / s  # metres per pixel (approx)

# world-space fields (resolution independent, so detail tiles match the base picture exactly)
cx0, cy0 = from_abs(np.array([0, W, 0, W]), np.array([0, 0, Hh, Hh]))
bx = (cx0.min() - 20, cx0.max() + 20); by = (cy0.min() - 20, cy0.max() + 20)
WC = 0.5
wnx, wny = int((bx[1] - bx[0]) / WC) + 2, int((by[1] - by[0]) / WC) + 2
def world_sample(arr, x, y, order=1):
    return map_coordinates(arr, [(np.asarray(y) - by[0]) / WC, (np.asarray(x) - bx[0]) / WC], order=order, mode="nearest")
_r = np.random.default_rng(1); NBW = np.zeros((wny, wnx))
for sc, am in zip([16, 7], [1, .5]):
    n_ = gaussian_filter(_r.standard_normal((wny, wnx)), sc / WC); NBW += am * n_ / (n_.std() + 1e-9)
nbw = lambda x, y: world_sample(NBW, x, y)
nb = nbw(X, Y)

# ---------------- real course features (OpenStreetMap), rasterised in world space ----------------
# OSM=data/osm/<course>.json. Everything here is world-space, so detail tiles line up with the base picture.
OSMF = json.load(open(os.environ["OSM"])) if os.environ.get("OSM") else None
# A hand-drawn map from the course editor ("map" in the hole file) is used the same way as OSM features, except
# that a drawn fairway replaces the generated one and the automatic treeline can stay on ("auto_trees").
# FEATURES_ONLY=1 ignores it and writes the procedural layout (fairway, bunkers, water) as lat/lng polygons instead.
FEATURES_ONLY = bool(os.environ.get("FEATURES_ONLY"))
MAP = None if FEATURES_ONLY else H.get("map")
if MAP is not None:
    OSMF = dict(features=[dict(kind=k, pts=P) for k in ("fairway", "green", "bunker", "water", "wood")
                          for P in MAP.get(k, []) if len(P) >= 3], trees=MAP.get("trees", []))
AUTO_TREES = MAP is None or MAP.get("auto_trees", True)
MAP_FAIRWAY = MAP is not None and any(len(P) >= 3 for P in MAP.get("fairway", []))
def frame(pts): return np.array([R @ to_m(p) for p in pts])
def world_mask(polys, width=None, round_ends=True):
    m = Image.new("L", (wnx, wny), 0); dr = ImageDraw.Draw(m)
    for P in polys:
        q = [((x - bx[0]) / WC, (y - by[0]) / WC) for x, y in P]
        if width:
            dr.line(q, fill=255, width=max(1, int(width / WC)), joint="curve")
            if round_ends:
                r_ = width / WC / 2
                for x_, y_ in (q[0], q[-1]): dr.ellipse([x_ - r_, y_ - r_, x_ + r_, y_ + r_], fill=255)
        elif len(q) >= 3: dr.polygon(q, fill=255)
    return np.asarray(m, float) / 255
def in_world(Wm, p): return float(world_sample(Wm, [p[0]], [p[1]])[0]) > 0.5
def polyline_cut(P, a, b):
    """part of polyline P between arc lengths a and b"""
    seg = np.linalg.norm(np.diff(P, axis=0), axis=1); cum = np.concatenate([[0], np.cumsum(seg)])
    ts = np.linspace(max(a, 0), min(b, cum[-1]), 60)
    return np.stack([np.interp(ts, cum, P[:, 0]), np.interp(ts, cum, P[:, 1])], 1)
OSM_ON = OSMF is not None
if OSM_ON:
    feats = {}
    for f in OSMF["features"]:
        feats.setdefault(f["kind"], []).append(f)
    poly = lambda k: [frame(f["pts"]) for f in feats.get(k, [])]
    greens_all = poly("green")
    own_green = None
    if greens_all:
        dists = [np.linalg.norm(P.mean(0) - G) for P in greens_all]
        if min(dists) < 15: own_green = greens_all[int(np.argmin(dists))]
    W_green_own = world_mask([own_green]) if own_green is not None else None
    W_green_oth = world_mask([P for P in greens_all if P is not own_green])
    W_tee = world_mask(poly("tee"))
    W_fair_osm = world_mask(poly("fairway"))
    W_bunker = world_mask(poly("bunker"))
    W_water = world_mask(poly("water"))
    W_wood = world_mask(poly("wood"))
    # other holes: OSM has their playing lines but (mostly) no fairway shapes, so give them a generated one
    nf, nc = [], []
    for f in feats.get("hole", []):
        if str(f.get("ref")) == str(H["hole"]): continue
        P = frame(f["pts"]); Ln = np.linalg.norm(np.diff(P, axis=0), axis=1).sum()
        if Ln < 200: continue                                   # par 3: tee, rough and green only
        nf.append(polyline_cut(P, 75, Ln - 22)); nc.append(polyline_cut(P, 62, Ln - 8))
    W_nfair = gaussian_filter(world_mask(nf, 28), 2 / WC) + 0.06 * NBW
    W_ncut = gaussian_filter(world_mask(nc, 46), 2 / WC) + 0.06 * NBW
    W_nfair = (W_nfair > 0.5) & (W_wood < 0.5); W_ncut = (W_ncut > 0.5) & (W_wood < 0.5)
    W_play = np.maximum.reduce([W_tee, W_fair_osm, W_bunker, W_water, W_green_oth, W_nfair.astype(float), W_ncut.astype(float)]
                               + ([W_green_own] if W_green_own is not None else []))
    # blurred a little before thresholding so drawn edges are smooth at any zoom, not stepped on the 0.5 m grid
    S_ = lambda Wm: world_sample(gaussian_filter(np.asarray(Wm, float), 0.8 / WC), X, Y) > 0.5
    wood, water, bunker = S_(W_wood), S_(W_water), S_(W_bunker)
    ogreen, otee = S_(W_green_oth), S_(W_tee)
    ofair = S_(W_fair_osm) | S_(W_nfair); ocut = S_(W_ncut)

# ---------------- centreline + shapes ----------------
C = 2 * L - (T + G) / 2
t = np.linspace(0, 1, 3000)[:, None]
curve = (1 - t) ** 2 * T + 2 * t * (1 - t) * C + t ** 2 * G
if H.get("path"):        # tile-built holes (compose_hole.py) give their own centre line, so S-bends work
    _P = frame(H["path"]); _c = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(_P, axis=0), axis=1))])
    _ts = np.linspace(0, _c[-1], 3000)
    curve = np.stack([np.interp(_ts, _c, _P[:, 0]), np.interp(_ts, _c, _P[:, 1])], 1)
arc = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(curve, axis=0), axis=1))])
total = arc[-1]
dist, idx = cKDTree(curve).query(np.stack([X.ravel(), Y.ravel()], 1))
dist, sarc = dist.reshape(X.shape), arc[idx].reshape(X.shape)

# Standard-size green: a rounded oval centred on the GPS green point, long axis along the approach.
# (The GPS front/back points vary too much to use for the size; only the centre and direction are kept.)
_gr = np.random.default_rng((sum(map(ord, H.get("course", ""))) * 131 + H["hole"] * 7919 + 1) % 2**32)
_j = int(np.searchsorted(arc, total - 30)); ga = (G - curve[min(_j, len(curve) - 1)]); ga = ga / (np.linalg.norm(ga) + 1e-9)
gc = G.copy()
a_ax = _gr.uniform(13, 16); b_ax = _gr.uniform(10, 12.5)
green_len = 2 * a_ax
_gph = _gr.uniform(0, 6.3, 2)
def green_r(du, dv):
    gu_ = du * ga[0] + dv * ga[1]; gv_ = -du * ga[1] + dv * ga[0]; th_ = np.arctan2(gv_, gu_)
    return gu_, gv_, np.sqrt((gu_ / a_ax) ** 2 + (gv_ / b_ax) ** 2) - (0.05 * np.sin(2 * th_ + _gph[0]) + 0.03 * np.sin(3 * th_ + _gph[1]))
du, dv = X - gc[0], Y - gc[1]
gu, gv, gr = green_r(du, dv)
green = gr < 1.0
if OSM_ON and W_green_own is not None:
    GD = distance_transform_edt(W_green_own < 0.5) * WC          # metres outside the real green (coarse, far out)
    # Near the green, its edge comes from the drawn outline itself: corners rounded off (Chaikin), drawn on a 5 cm
    # grid and turned into a signed distance (metres, + outside). Sampled smoothly, that gives a clean, even edge
    # however far the game zooms in; the 0.5 m world grid alone left it lumpy.
    _P = np.asarray(own_green, float)
    if np.allclose(_P[0], _P[-1]): _P = _P[:-1]
    for _ in range(4):
        _Q = np.roll(_P, -1, 0); _P = np.stack([0.75 * _P + 0.25 * _Q, 0.25 * _P + 0.75 * _Q], 1).reshape(-1, 2)
    FC = 0.05; _lo = _P.min(0) - 14; _hi = _P.max(0) + 14
    _fn = ((_hi - _lo) / FC).astype(int) + 1
    _m = Image.new("L", (int(_fn[0]), int(_fn[1])), 0)
    ImageDraw.Draw(_m).polygon([tuple(q) for q in ((_P - _lo) / FC)], fill=255)
    _in = np.asarray(_m) > 127
    GSDF = (distance_transform_edt(~_in) - distance_transform_edt(_in)) * FC
    def gsd(x, y):
        x, y = np.asarray(x, float), np.asarray(y, float)
        fine = map_coordinates(GSDF, [(y - _lo[1]) / FC, (x - _lo[0]) / FC], order=1, mode="nearest")
        near = (x > _lo[0]) & (x < _hi[0]) & (y > _lo[1]) & (y < _hi[1])
        return np.where(near, fine, np.maximum(world_sample(GD, x, y), 14))
    GSD = gsd(X, Y)
    # right at the edge, the exact distance to the (densely resampled) outline, so the line has no 5 cm ripple
    _seg = np.linalg.norm(np.diff(np.vstack([_P, _P[:1]]), axis=0), axis=1)
    _cum = np.concatenate([[0], np.cumsum(_seg)]); _Pc = np.vstack([_P, _P[:1]])
    _ts = np.arange(0, _cum[-1], 0.01)
    _dense = np.stack([np.interp(_ts, _cum, _Pc[:, 0]), np.interp(_ts, _cum, _Pc[:, 1])], 1)
    _band = np.abs(GSD) < 0.6
    if _band.any():
        _q = np.stack([X[_band], Y[_band]], 1)
        _d, _i = cKDTree(_dense).query(_q)
        # inside or out from the outline's own direction (its outward normal at the nearest point), not the grid
        _tan = np.roll(_dense, -1, 0) - np.roll(_dense, 1, 0)
        _area = np.sum(_Pc[:-1, 0] * _Pc[1:, 1] - _Pc[1:, 0] * _Pc[:-1, 1])
        _nrm = np.stack([_tan[:, 1], -_tan[:, 0]], 1) * (1 if _area > 0 else -1)
        _out = np.sum((_q - _dense[_i]) * _nrm[_i], 1) > 0
        GSD[_band] = np.where(_out, _d, -_d)
    green = GSD < 0
    gdist = np.maximum(GSD, 0)
else:
    gdist = (gr - 1.0) * a_ax                                     # roughly metres outside the generated green
    GSD = gdist

fw_start = 80.0
half_w = 15 + 4 * np.exp(-((sarc - 230) / 60) ** 2) - 4 * np.clip((sarc - (total - 60)) / 50, 0, 1) + 2.0 * nb
fairway = (dist < half_w * np.clip((sarc - fw_start) / 8, 0, 1)) & (sarc < total - 2)
if D < 200: fairway &= sarc > total - 45                         # par 3: just a short approach
fairway |= gdist < 2.5
cut = (dist < (half_w + 10) * np.clip((sarc - fw_start + 10) / 10, 0, 1)) | (gdist < 9)
cut &= sarc > fw_start - 12
tu, tv = X - T[0], Y - (T[1] - 4)
teebox = (np.abs(tu) < 6) & (np.abs(tv) < 9)
teepad = (np.abs(tu) < 10) & (np.abs(tv) < 13)
if OSM_ON:
    hazard = water | bunker
    fairway &= ~wood & ~hazard; cut &= ~wood
    ofair &= ~hazard; ocut &= ~hazard & ~wood
    cut |= ocut
else:
    # ---- procedural hazards: standard bunkers, a pond or a stream, placed from the hole's own shape ----
    # Seeded by course + hole number, so a hole always comes out the same.
    hr = np.random.default_rng((sum(map(ord, H.get("course", ""))) * 131 + H["hole"] * 7919) % 2**32)
    def at_arc(sa):                      # point and unit normal (to the right) on the centre line
        j = int(np.clip(np.searchsorted(arc, sa), 1, len(arc) - 1))
        tg = curve[j] - curve[j - 1]; tg = tg / (np.linalg.norm(tg) + 1e-9)
        return curve[j], np.array([tg[1], -tg[0]])
    def blob(cx_, cy_, ra, rb, rot, wob=0.14):
        ph = hr.uniform(0, 6.3, 2); th_ = np.linspace(0, 2 * np.pi, 48, endpoint=False)
        rr_ = 1 + wob * np.sin(2 * th_ + ph[0]) + wob * 0.6 * np.sin(3 * th_ + ph[1])
        x_, y_ = ra * rr_ * np.cos(th_), rb * rr_ * np.sin(th_)
        c_, s_ = math.cos(rot), math.sin(rot)
        return np.stack([cx_ + c_ * x_ - s_ * y_, cy_ + s_ * x_ + c_ * y_], 1)
    bunkers, ponds, streams = [], [], []
    par = H["par"]
    # greenside: 1-3 bunkers hugging the green (front-left, front-right, sides, back)
    p_in, _ = at_arc(total - 30); appr = (G - p_in) / (np.linalg.norm(G - p_in) + 1e-9)
    gR = max(a_ax, b_ax) + 3.5
    for ang in hr.choice([150, -150, 95, -95, 25], size=int(hr.integers(1, 4)), replace=False):
        a_ = math.radians(ang); d_ = np.array([appr[0] * math.cos(a_) - appr[1] * math.sin(a_), appr[0] * math.sin(a_) + appr[1] * math.cos(a_)])
        # the green's real edge in this direction, then a 3 m strip of fringe before the sand starts
        edge = next(t_ for t_ in np.arange(4, 40, 0.25) if green_r(d_[0] * t_, d_[1] * t_)[2] >= 1.0)
        rb_ = hr.uniform(3, 4.2)
        c_ = gc + d_ * (edge + 3.0 + rb_ * 1.25)
        bunkers.append(blob(c_[0], c_[1], hr.uniform(5, 7.5), rb_, math.atan2(d_[1], d_[0]) + math.pi / 2))
    # fairway bunkers in the landing zone (par 4/5)
    if par >= 4 and total > 260:
        side = hr.choice([-1, 1])
        for k in range(int(hr.integers(1, 3))):
            sa = min(225 + 28 * k, total - 100) + hr.uniform(-10, 10)
            pt, nrm = at_arc(sa); c_ = pt + nrm * side * (13 + hr.uniform(0, 4))
            tgt = np.array([-nrm[1], nrm[0]])
            bunkers.append(blob(c_[0], c_[1], hr.uniform(8, 11), hr.uniform(3.5, 5), math.atan2(tgt[1], tgt[0])))
            side = -side
    # water: par 3s may carry over a pond; longer holes get a pond beside the fairway or a stream across it
    roll = hr.random()
    if par == 3 and roll < 0.5:
        pt, nrm = at_arc(max(total - gR - 20, total * 0.45)); tgt = np.array([-nrm[1], nrm[0]])
        ponds.append(blob(pt[0], pt[1], 30, 11, math.atan2(nrm[1], nrm[0]), 0.1))
    elif par >= 4 and roll < 0.35:
        sa = hr.uniform(0.38, 0.6) * total if total > 300 else total - gR - 35
        pt, nrm = at_arc(sa); tgt = np.array([-nrm[1], nrm[0]])
        ts_ = np.linspace(-140, 140, 90); wig = 7 * np.sin(ts_ / 23 + hr.uniform(0, 6)) + 4 * np.sin(ts_ / 9 + hr.uniform(0, 6))
        streams.append(pt + np.outer(ts_, nrm) + np.outer(wig, tgt))
    elif par >= 4 and roll < 0.7:
        side = hr.choice([-1, 1]); sa = hr.uniform(0.5, 0.8) * total
        pt, nrm = at_arc(sa); c_ = pt + nrm * side * (36 + hr.uniform(0, 8))
        tgt = np.array([-nrm[1], nrm[0]])
        ponds.append(blob(c_[0], c_[1], hr.uniform(26, 40), hr.uniform(13, 18), math.atan2(tgt[1], tgt[0]), 0.12))
    if FEATURES_ONLY:
        def to_ll(P):                                   # hole frame -> [lat, lng]
            P = np.asarray(P, float) @ R
            return [[round(lat0 + y_ / ky, 8), round(lng0 + x_ / kx, 8)] for x_, y_ in P]
        def ribbon(S, w):                               # a polyline widened into a polygon
            S = np.asarray(S, float); tg = np.gradient(S, axis=0); tg /= np.linalg.norm(tg, axis=1, keepdims=True) + 1e-9
            nrm_ = np.stack([tg[:, 1], -tg[:, 0]], 1) * w / 2
            return np.concatenate([S + nrm_, (S - nrm_)[::-1]])
        # fairway outline: the generated fairway's half-width either side of the centre line
        fa = np.arange(fw_start if D >= 200 else total - 45, total - 2, 8.0)
        lft, rgt = [], []
        for sa in fa:
            pt, nrm = at_arc(sa); n_ = float(nbw([pt[0]], [pt[1]])[0])
            hw_ = 15 + 4 * math.exp(-((sa - 230) / 60) ** 2) - 4 * min(max((sa - (total - 60)) / 50, 0), 1) + 2.0 * n_
            lft.append(pt - nrm * hw_); rgt.append(pt + nrm * hw_)
        auto = dict(fairway=[to_ll(rgt + lft[::-1])] if len(fa) > 1 else [], green=[],
                    bunker=[to_ll(P) for P in bunkers],
                    water=[to_ll(P) for P in ponds] + [to_ll(ribbon(S, 6)) for S in streams],
                    wood=[], trees=[], auto_trees=True)
        json.dump(auto, open(out, "w")); print("features", {k: len(v) for k, v in auto.items() if isinstance(v, list)}); sys.exit()
    W_bunker = world_mask(bunkers)
    W_water = np.maximum(world_mask(ponds), world_mask(streams, 6, round_ends=False))
    W_play = np.maximum(W_bunker, gaussian_filter(W_water, 3 / WC) > 0.05)
    # blurred a little before thresholding so sand and water edges are smooth, not stair-stepped
    S_ = lambda Wm: world_sample(gaussian_filter(np.asarray(Wm, float), 0.8 / WC), X, Y) > 0.5
    water = S_(W_water) & ~green & ~teepad
    bunker = S_(W_bunker) & ~green & ~teepad & ~water
    wood = ogreen = otee = ofair = np.zeros_like(green)
    fairway &= ~water & ~bunker

# ---------------- smooth fairway + first cut ----------------
# Built in world space and blurred before thresholding, so ends are rounded, the edges flow, and hazards
# leave a soft grass margin instead of sharp notches. The blurred field is sampled per pixel and only then
# thresholded, so edges stay smooth at any zoom (and detail tiles match the base picture).
WXw, WYw = np.meshgrid(bx[0] + np.arange(wnx) * WC, by[0] + np.arange(wny) * WC)
_wd, _wi = cKDTree(curve).query(np.stack([WXw.ravel(), WYw.ravel()], 1))
WDst, WSarc = _wd.reshape(WXw.shape), arc[_wi].reshape(WXw.shape)
Whw = 15 + 4 * np.exp(-((WSarc - 230) / 60) ** 2) - 4 * np.clip((WSarc - (total - 60)) / 50, 0, 1) + 2.0 * NBW
if OSM_ON and W_green_own is not None:
    WGd = np.maximum(gsd(WXw, WYw), 0)
else:
    WGd = (green_r(WXw - gc[0], WYw - gc[1])[2] - 1.0) * a_ax
Wfr = (WDst < Whw) & (WSarc > fw_start) & (WSarc < total - 2)
if D < 200: Wfr &= WSarc > total - 45
Wfr |= WGd < 2.5
Wcr = ((WDst < Whw + 10) & (WSarc > fw_start - 12)) | (WGd < 9)
if MAP_FAIRWAY:          # the drawn fairway replaces the generated one; the first cut is a 9 m band round it
    Wfr = (W_fair_osm > 0.5) | (WGd < 2.5)
    Wcr = (distance_transform_edt(W_fair_osm < 0.5) * WC < 9) | (WGd < 9)
    ofair = np.zeros_like(ofair)
Whaz = np.maximum(W_bunker, W_water)
if OSM_ON: Whaz = np.maximum(Whaz, W_wood)
near_haz = distance_transform_edt(Whaz < 0.5) * WC < 2.5          # keep a grass margin round hazards
Wfr &= ~near_haz
# the first cut wraps round bunkers by the fairway or green, so its outline never runs through the sand
Wcr |= (distance_transform_edt(W_bunker < 0.5) * WC < 3.0) & ((WDst < Whw + 30) | (WGd < 25))
FairF = gaussian_filter(Wfr.astype(float), 3.0 / WC)
CutF = gaussian_filter(Wcr.astype(float), 4.0 / WC)
# the blur would fill small gaps back in, so the grass margin round each hazard is cut out again afterwards
HazF = gaussian_filter((distance_transform_edt(Whaz < 0.5) * WC < 2.5).astype(float), 0.6 / WC)
fairway = (world_sample(FairF, X, Y) > 0.5) & (world_sample(HazF, X, Y) < 0.5)
cut = world_sample(CutF, X, Y) > 0.5
if OSM_ON:
    cut &= ~wood; cut |= ocut; cut &= ~water
else:
    cut &= ~water

# ---------------- elevation -> toon hill shading ----------------
# Same layout as the Pure Golf app's generateHoleGrid: rows every total/(rows-1) metres from the tee to 20 m
# past the green, columns 18 m apart either side of the tee->green line (positive = right of the line).
GSTEP, gtotal = float(H.get("grid_step", 18.0)), D + 20.0
garr = np.array(H["grid"], float)
if "grid_half" in H: half = int(H["grid_half"])       # composed holes say how the grid is laid out
else:
    half = min(max(math.floor(gtotal / 2 / GSTEP + 0.5), 1), 12)
    for h_ in (half, half - 1, half + 1):            # distances differ slightly from the app's: try neighbours
        if h_ >= 1 and len(garr) % (2 * h_ + 1) == 0 and len(garr) // (2 * h_ + 1) >= 3: half = h_; break
gcols = 2 * half + 1; grows = len(garr) // gcols
grid = garr[:grows * gcols].reshape(grows, gcols)
WXg, WYg = np.meshgrid(bx[0] + np.arange(wnx) * WC, by[0] + np.arange(wny) * WC)
ZW = map_coordinates(grid, [np.clip((WYg - T[1]) / (gtotal / (grows - 1)), 0, grows - 1),
                            np.clip((WXg - T[0]) / GSTEP + half, 0, gcols - 1)], order=1)
ZW = gaussian_filter(ZW, (14 if GSTEP > 10 else 2.5) / WC) + 0.35 * NBW   # a fine grid keeps its mounds and tiers
if GSTEP > 10:
    # holes from GPS data only have a coarse 18 m grid, so they get the composer's rolling mounds and hollows here,
    # along their centre line (same sizes as compose_hole.MOUNDS["rolling"]), clear of the tee and the green
    _mr = np.random.default_rng((sum(map(ord, H.get("course", ""))) * 31 + H["hole"] * 7 + 5) % 2**32)
    _tan = np.gradient(curve, axis=0); _tan /= np.linalg.norm(_tan, axis=1, keepdims=True) + 1e-9
    for _ in range(int(round(6 * max(total - 100, 0) / 100))):
        _s = _mr.uniform(80, total - 20); _k = int(np.searchsorted(arc, _s)); _k = min(_k, len(curve) - 1)
        _c = curve[_k] + np.array([_tan[_k, 1], -_tan[_k, 0]]) * _mr.uniform(-26, 26)
        _r, _h = _mr.uniform(5, 12), 1.3 * _mr.uniform(0.5, 1.0) * (1 if _mr.random() < 0.7 else -0.8)
        if np.linalg.norm(_c - G) < 20 or np.linalg.norm(_c - T) < 15: continue
        ZW += _h * np.exp(-((WXg - _c[0]) ** 2 + (WYg - _c[1]) ** 2) / (2 * _r * _r))
gyw, gxw = np.gradient(ZW * 6, WC)
lx, ly = cR.T @ np.array([-0.7, 0.7])          # light from top-left of the *screen*
HSW = gaussian_filter((gxw * lx + gyw * ly) / np.sqrt(1 + gxw ** 2 + gyw ** 2), 3 / WC)
hs = world_sample(HSW, X, Y)
band = np.digitize(hs, [-0.12, 0.10])          # 0 shadow, 1 mid, 2 lit

# ---------------- paint flat colours ----------------
def c(h): return np.array([int(h[i:i + 2], 16) for i in (1, 3, 5)], float)
def bands3(k): return np.stack([c(v) for v in PAL[k]])
def stripes(k, m): return np.where(m[..., None], c(PAL[k][0]), c(PAL[k][1]))
rough = bands3("rough")
img = rough[band].copy()
cutc = bands3("cut")
woodc = bands3("wood")        # forest floor
img[wood] = woodc[band][wood]
img[cut] = cutc[band][cut]
plain = ~(cut | wood)          # open ground beyond the first cut
# theme ground detail, in world metres so detail tiles line up with the base picture
if THEME == "space":
    # craters scattered over the regolith: a dark bowl with a lit rim on the top-left
    cr_rng = np.random.default_rng((sum(map(ord, H.get("course", ""))) * 31 + H["hole"]) % 2**32)
    for _ in range(70):
        cx_, cy_ = cr_rng.uniform(bx[0], bx[1]), cr_rng.uniform(by[0], by[1]); r_ = cr_rng.uniform(3, 11)
        dd = np.hypot(X - cx_, Y - cy_) / r_
        if not (dd < 1.2).any(): continue
        sh = (X - cx_) * -0.7 + (Y - cy_) * 0.7          # positive towards the light
        bowl = plain & (dd < 1.0); rim = plain & (dd >= 1.0) & (dd < 1.18)
        img[bowl] = img[bowl] * np.where((sh[bowl] < 0)[:, None], 0.92, 0.72)
        img[rim] = np.minimum(img[rim] * 1.25 + 12, 255)
elif THEME == "neon":
    # a glowing perspective grid over the dark ground
    gl = (np.abs(((X + 6) % 12) - 6) < 0.32) | (np.abs(((Y + 6) % 12) - 6) < 0.32)
    m_ = gl & ~wood
    img[m_] = img[m_] * 0.45 + c("#ff2fa8") * 0.55
elif THEME == "medieval":
    # worn earth patches in the meadow
    pt_ = plain & (nb > 1.35)
    img[pt_] = img[pt_] * 0.82 + c("#8a6a3a") * 0.18
stripe = (np.floor(sarc / 9) % 2).astype(bool)
fwc = stripes("fair", stripe)
allfair = fairway | ofair
img[allfair] = fwc[allfair]
# fairways take the hill shading too (darker on slopes away from the light, lighter facing it), so mounds and tiers show
img[allfair] = img[allfair] * np.array([0.86, 1.0, 1.09])[band][allfair][:, None]
# green surface: one of a few mowing patterns, picked per hole in the editor (the green tile's "style").
# All are worked out in metres on the green, so they stay crisp in the 12x green tile.
GREEN_STYLES = ("stripes", "checker", "diamond", "rings", "crosscut", "plain")
gstyle = H.get("green_style", "stripes")
if gstyle not in GREEN_STYLES: gstyle = "stripes"
g_lt, g_dk = c(PAL["green"][0]), c(PAL["green"][1])
if gstyle == "checker":
    gcol = stripes("green", ((np.floor(gu / 3) + np.floor(gv / 3)) % 2).astype(bool))
elif gstyle == "diamond":
    ga_, gb_ = (gu + gv) / math.sqrt(2), (gu - gv) / math.sqrt(2)
    gcol = stripes("green", ((np.floor(ga_ / 2.8) + np.floor(gb_ / 2.8)) % 2).astype(bool))
elif gstyle == "rings":
    gcol = stripes("green", (np.floor(np.hypot(gu, gv) / 2.2) % 2).astype(bool))
elif gstyle == "crosscut":       # stripes both ways: three tones where they cross
    n_ = (np.floor(gu / 2.5) % 2) + (np.floor(gv / 2.5) % 2)
    tones = np.stack([g_lt, (g_lt + g_dk) / 2, g_dk * 0.985])
    gcol = tones[n_.astype(int)]
elif gstyle == "plain":
    gcol = np.broadcast_to(g_lt, gu.shape + (3,)).copy()
else:
    gcol = stripes("green", (np.floor(gu / 2.5) % 2).astype(bool))
if gstyle in ("rings", "plain"):  # a darker collar just inside the edge frames the putting surface
    from scipy.ndimage import distance_transform_edt as _edt
    for gm_ in (green, ogreen):
        if gm_.any():
            col_ = gm_ & (_edt(gm_) < 1.1 / mpp)
            gcol[col_] = g_dk * 0.94
# height shading on the green, from its slope grid (the same numbers putts roll on): the high ground lighter, the
# low ground darker. Measured in metres, not stretched to fit, so a gentle green gets a faint wash and a severe one
# strong contrast: GREEN_SHADE_M either side of the green's middle height gets the full light or shade.
# Drawn as flat layers, one per 0.2 m step, not a smooth gradient.
GREEN_SHADE_M = 0.6
GREEN_LAYERS = 3              # layers each side of the middle: 0.2 m apiece
if H.get("green_grid") and green.any():
    _gg = H["green_grid"]; _n, _st = _gg["n"], _gg["step"]
    _cm = np.frombuffer(base64.b64decode(_gg["cm"]), dtype="<i2").reshape(_n, _n).astype(float)
    _c, _s = math.cos(-north_rot), math.sin(-north_rot)
    _ys, _xs = np.nonzero(green)
    _y0, _y1, _x0, _x1 = _ys.min(), _ys.max() + 1, _xs.min(), _xs.max() + 1
    _Xg, _Yg = X[_y0:_y1, _x0:_x1] - G[0], Y[_y0:_y1, _x0:_x1] - G[1]
    _E, _N = _c * _Xg - _s * _Yg, _s * _Xg + _c * _Yg
    _hz = map_coordinates(_cm, [(_n - 1) / 2 - _N / _st, (_n - 1) / 2 + _E / _st], order=3, mode="nearest") / 100.0
    _gm = green[_y0:_y1, _x0:_x1]
    # in sharp layers, toon style: one layer per GREEN_LAYERS of the scale (0.2 m), so a steeper green shows more of them
    _k = np.clip(np.round((_hz - np.median(_hz[_gm])) / GREEN_SHADE_M * GREEN_LAYERS) / GREEN_LAYERS, -1, 1)[..., None]
    _sub = gcol[_y0:_y1, _x0:_x1]
    _sub[:] = np.where(_k > 0, _sub + (255 - _sub) * _k * 0.42, _sub * (1 + _k * 0.30))
# richer greens: push the colours away from grey (saturation up by GREEN_SAT)
GREEN_SAT = 1.45
_gl = gcol.mean(-1, keepdims=True); gcol = np.clip(_gl + (gcol - _gl) * GREEN_SAT, 0, 255)
img[ogreen] = gcol[ogreen]
img[green] = gcol[green]
tstripe = (np.floor(tv / 3) % 2).astype(bool)
tcol = stripes("tee", tstripe)
if THEME == "medieval":            # flagstones rather than stripes
    tcol = np.where(((np.floor(tu / 2.2) + np.floor(tv / 1.6)) % 2).astype(bool)[..., None], c(PAL["tee"][0]), c(PAL["tee"][1]))
img[otee & ~green] = tcol[otee & ~green]
img[teepad] = cutc[1]
img[teebox] = tcol[teebox]
# sand: lighter towards the lit side; water: soft noise ripples (space: a starry void)
sandc = bands3("sand")
img[bunker] = sandc[band][bunker]
if THEME == "space":
    star_n = np.random.default_rng(5).random((wny, wnx))
    stars = world_sample(star_n, X, Y, order=0) > 0.985
    swirl = (np.sin(np.hypot(X, Y) * 0.25 + 2 * nb) > 0.6)
    waterc = np.where(swirl[..., None], c(PAL["water"][0]), c(PAL["water"][1]))
    waterc[stars] = c("#f4f0ff")
else:
    rip = (np.sin((X * 0.7 + Y * 0.35) + 3 * nb) > 0.75)
    waterc = np.where(rip[..., None], c(PAL["water"][0]), c(PAL["water"][1]))
img[water] = waterc[water]

# outlines: edge of each region in a darker ink (neon: bright lines with a soft glow)
ink = c(PAL["ink"])
GLOW = THEME in ("neon", "space")
glow = np.zeros_like(img) if GLOW else None
def outline(mask, width_px, colr=ink, alpha=1.0):
    # a detail tile is a window onto the full picture: regions that run off its edge carry on,
    # so the tile border must not count as a region edge (that drew a hard line across the fairway)
    e = mask & ~binary_erosion(mask, iterations=int(round(width_px)), border_value=1 if DETAIL else 0)
    img[e] = img[e] * (1 - alpha) + colr * alpha
    if GLOW: glow[e] = np.maximum(glow[e], colr)
outline(cut, 4 * U, alpha=0.95)
outline(allfair, 3 * U, c(PAL["l_fair"]), 0.85)
# the green's own edge: a thin line of even width, anti-aliased, from the signed distance to its outline
_pxm = mpp                                        # metres per pixel
_w = max(1.0 * U, 1.5) * _pxm                     # line width: U px, half what it was
_cov = np.clip(np.minimum(GSD + _w, -GSD) / _pxm + 0.5, 0, 1)[..., None]
img[:] = img * (1 - _cov * 0.9) + c(PAL["l_green"]) * _cov * 0.9
# and a bright rim just inside it, like a highlight on the lip of the green
_hw = max(0.8 * U, 1.2) * _pxm
_hc = np.clip(np.minimum(GSD + _w + _hw, -(GSD + _w)) / _pxm + 0.5, 0, 1)[..., None] * green[..., None]
img[:] = img * (1 - _hc * 0.55) + 255 * _hc * 0.55
if GLOW:
    _e = _cov[..., 0] > 0.5; glow[_e] = np.maximum(glow[_e], c(PAL["l_green"]))
outline(ogreen, 2 * U, c(PAL["l_green"]), 0.9)
outline(otee, 2 * U, c(PAL["l_fair"]), 0.8)
outline(bunker, 3 * U, c(PAL["l_sand"]), 0.95)
outline(water, 3 * U, c(PAL["l_water"]), 0.95)
outline(teepad, 2 * U, alpha=0.8)
outline(teebox, 2 * U, c(PAL["l_fair"]), 0.8)
if GLOW:
    k_ = (4.0 if THEME == "neon" else 2.5) * U
    gb = np.stack([gaussian_filter(glow[..., i], k_) for i in range(3)], -1)
    img = np.minimum(img + gb * (0.9 if THEME == "neon" else 0.45), 255)
# soft ink along hill-band boundaries in the rough (cartoon contours)
bedge = (np.abs(np.diff(band, axis=0, prepend=band[:1])) + np.abs(np.diff(band, axis=1, prepend=band[:, :1]))) > 0
bedge = gaussian_filter(bedge.astype(float), 1.2 * U) > 0.2
fedge = bedge & allfair & ~green                 # on the fairway too, but lighter
bedge &= ~cut & ~bunker & ~water & ~ogreen & ~ofair
img[bedge] = img[bedge] * (1.35 if THEME == "neon" else 0.86)
img[fedge] = img[fedge] * (1.2 if THEME == "neon" else 0.92)

base = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).filter(ImageFilter.SMOOTH)
cv = ImageDraw.Draw(base, "RGBA")

# ---------------- props: trees, bushes, rocks, tufts ----------------
_kd = cKDTree(curve)
def zone_at(p):          # (tree-zone value, clump noise) at a world point, or None off the picture
    q = to_abs(p)
    if not (0 <= q[0] < W and 0 <= q[1] < Hh): return None, None
    d_, i_ = _kd.query(p); sa = arc[i_]; n_ = float(nbw([p[0]], [p[1]])[0])
    hw = 15 + 4 * math.exp(-((sa - 230) / 60) ** 2) - 4 * min(max((sa - (total - 60)) / 50, 0), 1) + 2.0 * n_
    return d_ - hw - 13 - 3 * n_, n_          # 0 = just past the first cut
props = []
if OSM_ON:
    # real trees: OSM single trees and tree rows, plus woods filled with trees about 7.5 m apart
    def clear_of_play(p):
        d_, i_ = _kd.query(p); sa = arc[i_]
        if MAP is None and d_ < 29 and fw_start - 15 < sa < total + 5: return False      # this hole's fairway and first cut
        if np.hypot(*(p - T)) < 14 or np.hypot(*(p - G)) < a_ax + (4 if MAP is not None else 12): return False
        return not in_world(W_play, p)
    singles = [frame([t_])[0] for t_ in OSMF["trees"]]
    for f in feats.get("tree_row", []):
        P = frame(f["pts"]); Ln = np.linalg.norm(np.diff(P, axis=0), axis=1).sum()
        singles += list(polyline_cut(P, 0, Ln)[::max(1, int(60 * 7 / max(Ln, 1)))])
    rw = np.random.default_rng(11)
    fill = rw.uniform([bx[0], by[0]], [bx[1], by[1]], (int((bx[1] - bx[0]) * (by[1] - by[0]) / 14), 2))
    fill = fill[world_sample(W_wood, fill[:, 0], fill[:, 1]) > 0.5]
    cells = {}                                  # spatial hash for the spacing check
    def too_close(p, gap):
        cx_, cy_ = int(p[0] // 8), int(p[1] // 8)
        return any(np.hypot(*(p - o)) < gap for i in (-1, 0, 1) for j in (-1, 0, 1) for o in cells.get((cx_ + i, cy_ + j), ()))
    for gap, pts_ in ((3.0, singles), (7.5, fill)):
        for p in pts_:
            q = to_abs(p)
            if not (-40 * U <= q[0] < W + 40 * U and -40 * U <= q[1] < Hh + 40 * U): continue
            if too_close(p, gap) or not clear_of_play(p): continue
            cells.setdefault((int(p[0] // 8), int(p[1] // 8)), []).append(p); props.append(("tree", p))
for p in rng.uniform([bx[0], by[0]], [bx[1], by[1]], (2600, 2)):
    z, clump = zone_at(p)
    if z is None: continue
    nearG = np.hypot(*(p - gc)) < a_ax + 16; nearT = np.hypot(*(p - T)) < 18
    if nearG or nearT: continue
    if in_world(W_play, p) or (OSM_ON and in_world(W_wood, p)): continue
    if MAP_FAIRWAY and world_sample(CutF, [p[0]], [p[1]])[0] > 0.3: continue      # keep off a drawn fairway's cut
    if z > 0 and (not OSM_ON or (MAP is not None and AUTO_TREES)) and rng.random() < (0.35 + 0.6 * min(z / 12, 1)) * (clump > -0.6):   # tight treeline
        props.append(("tree", p))
    elif z > -3 and rng.random() < 0.05:
        props.append(("bush", p))
    elif z > -3.5 and rng.random() < 0.05:
        props.append(("rock", p))
    elif z > -4 and rng.random() < 0.09:
        props.append(("tuft", p))
# pictures that can be placed from the course editor: art/<set>/props/props.json + one PNG each
import glob as _glob
SPRITES = {}
for _mf in sorted(_glob.glob(_os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "art", "*", "props", "props.json"))):
    for _k, _v in json.load(open(_mf)).items(): SPRITES.setdefault(_k, dict(_v, path=_os.path.join(_os.path.dirname(_mf), _v["file"])))
placed = []
# placed props (bushes, rocks, pictures) from a drawn or tile-built map, or "props" in a GPS hole file
# ([{"kind", "pt": [lat, lng], "scale"?, "flip"?}]), so GPS courses can be dressed without a map
for pr in (MAP.get("props", []) if MAP is not None else []) + H.get("props", []):
    if pr.get("kind") in ("bush", "rock", "tuft"): props.append((pr["kind"], frame([pr["pt"]])[0]))
    elif pr.get("kind") in SPRITES: placed.append(pr); props.append((f"@{len(placed) - 1}", frame([pr["pt"]])[0]))
# ---- scenery from the prop pictures in art/ (classic and medieval looks) ----
# Every tree, bush, rock and ornament is one of the pictures in art/*/props, so the style matches the editor.
# Placement is checked in a fixed-size copy of the picture ("ref" space, the same for the base picture and
# every detail tile), against the course and against everything already placed:
#   - nothing may cover the tee, fairway, first cut, green, bunkers or water
#   - trees may overlap other trees a little (a wood), nothing else may overlap anything
SPRITE_SCENERY = THEME in ("classic", "medieval") and "oak" in SPRITES
if SPRITE_SCENERY:
    _seed = (sum(map(ord, H.get("course", ""))) * 131 + H["hole"] * 7919 + 77) % 2**32
    srng = np.random.default_rng(_seed)
    FEAT_SPOTS = srng.uniform([bx[0], by[0]], [bx[1], by[1]], (200, 2))
    FILL_SPOTS = srng.uniform([bx[0], by[0]], [bx[1], by[1]], (1400, 2))
    # each spot gets its own dice from its position, so the base picture and the detail tiles agree exactly
    def prng(p, salt): return np.random.default_rng((int(round(p[0] * 37)) * 1000003 + int(round(p[1] * 37)) * 7919 + salt * 104729 + _seed) % 2**32)
    have = lambda L: [it for it in L if it[0] in SPRITES]
    if THEME == "medieval":
        TREE_POOL = have([("pine", 3), ("pine_tall", 3), ("pine_small", 2), ("tree_cone", 2), ("oak", 2), ("tree_round", 1), ("tree_bushy", 1)])
    else:
        TREE_POOL = have([("oak", 3), ("oak_wide", 2), ("tree_round", 3), ("tree_bushy", 2), ("tree_bushy_b", 2),
                          ("pine", 1), ("pine_tall", 1), ("pine_small", 1), ("tree_cone", 1)])
    SMALL_POOL = have([("bush", 4), ("bush_flowers", 3), ("bush_lavender", 2), ("long_grass_a", 3), ("long_grass_b", 3),
                       ("stone", 2), ("stones", 2), ("pebbles", 1), ("rock_mossy_a", 1), ("rock_mossy_b", 1),
                       ("rock_pile", 1), ("rock_cluster", 1), ("rock_tall", 1)])
    FEATURE_POOL = have([("boulder", 3), ("rock_slab", 2), ("pond_grass", 2), ("reed_pond", 2), ("pond_stone", 1)])
    if THEME == "medieval":
        SMALL_POOL += have([("barrel", 2), ("barrel_b", 1), ("crate", 2), ("crate_open", 1), ("barrels", 1), ("crates", 1),
                            ("wheelbarrow", 1), ("haystack", 2), ("flag_red", 0.3), ("flag_blue", 0.3), ("flag_yellow", 0.3)])
        FEATURE_POOL += have([("hay_bales", 3), ("cart", 3), ("well", 2), ("tent", 2), ("tent_small", 2), ("tent_blue", 2),
                              ("archery_target", 2), ("tower_tall", 2), ("tower_square", 1), ("keep_small", 1),
                              ("ruin_wall_a", 1), ("ruin_wall_c", 1), ("ruin_wall_e", 1), ("ruin_wall_g", 1),
                              ("fence", 2), ("fence_gate", 1), ("stone_wall_short", 1)])
    SCALE = {"long_grass_a": 0.5, "long_grass_b": 0.5}
    def pick(pool, r):
        w = np.array([q for _, q in pool], float); return pool[int(r.choice(len(pool), p=w / w.sum()))][0]

    # ref space: abs picture px / U * RS, padded so props hanging over the edge are checked too
    RS, PAD = 0.5, 80
    RW, RH = int(OUT_W * RS) + 2 * PAD, int(OUT_H * RS) + 2 * PAD
    def ref_of(p): q = to_abs(p) / U * RS + PAD; return float(q[0]), float(q[1])
    _ry, _rx = np.mgrid[0:RH, 0:RW] + 0.5
    RX, RY = from_abs((_rx - PAD) / RS * U, (_ry - PAD) / RS * U)
    # the course, in world space: first cut (which holds fairway and green), green surround, tee, sand, water
    nogo_w = (CutF > 0.3) | (WGd < 9) | (W_bunker > 0.5) | (W_water > 0.5)
    nogo_w |= (np.abs(WXw - T[0]) < 11) & (np.abs(WYw - (T[1] - 4)) < 14)
    if OSM_ON:
        nogo_w |= (W_play > 0.5) | (W_green_oth > 0.5)
    nogo_w = distance_transform_edt(~nogo_w) * WC < 1.5            # a little grass between props and the course
    NOGO = world_sample(nogo_w.astype(float), RX, RY, order=0) > 0.5
    OCC = np.zeros((RH, RW), np.int8)                                # 1 = tree, 2 = anything else
    ref_ppm = s / U * RS                                             # ref px per metre
    _ref_cache = {}
    def ref_mask(kind, scale, flip):
        sp = SPRITES[kind]; key = (kind, round(scale, 3), flip)
        if key not in _ref_cache:
            f = sp["m"] * scale * ref_ppm / sp["w"]
            im = Image.open(sp["path"]).convert("RGBA").getchannel("A")
            if flip: im = ImageOps.mirror(im)
            im = im.resize((max(1, round(sp["w"] * f)), max(1, round(sp["h"] * f))), Image.BILINEAR)
            ax = (sp["w"] - sp["anchor"][0] if flip else sp["anchor"][0]) * f
            _ref_cache[key] = (np.asarray(im) > 110, ax, sp["anchor"][1] * f)
        return _ref_cache[key]
    def footprint(pr, p):
        m_, ax, ay = ref_mask(pr["kind"], float(pr.get("scale", 1)), bool(pr.get("flip")))
        rx, ry = ref_of(p); x0, y0 = round(rx - ax), round(ry - ay)
        h_, w_ = m_.shape
        cx0, cy0, cx1, cy1 = max(x0, 0), max(y0, 0), min(x0 + w_, RW), min(y0 + h_, RH)
        if cx1 <= cx0 or cy1 <= cy0: return None
        return m_[cy0 - y0:cy1 - y0, cx0 - x0:cx1 - x0], (slice(cy0, cy1), slice(cx0, cx1))
    def try_place(pr, p, tree, force=False):
        fp = footprint(pr, p)
        if fp is None: return False
        m_, sl = fp; area = max(int(m_.sum()), 1)
        if not force:
            if (m_ & NOGO[sl]).sum() > 0.01 * area: return False
            o = OCC[sl][m_]
            if tree:
                if (o == 2).sum() > 0.02 * area or (o == 1).sum() > 0.45 * area: return False
            elif (o > 0).sum() > 0.02 * area: return False
        OCC[sl][m_] = 1 if tree else 2
        return True

    auto = []          # (prop dict, world point)
    # 1. the pictures placed in the editor claim their ground first
    for pr in placed:
        try_place(pr, frame([pr["pt"]])[0], SPRITES[pr["kind"]]["solid"] and pr["kind"] in dict(TREE_POOL), force=True)
    # 2. the odd landmark in the rough or a clearing: boulders, ponds (and in Castle Keep, tents, carts, towers...)
    n_feat = 14 if THEME == "medieval" else 5
    for p in FEAT_SPOTS[:n_feat * 12]:
        if len(auto) >= n_feat: break
        if np.hypot(*(p - T)) < 25 or np.hypot(*(p - gc)) < a_ax + 20: continue
        r_ = prng(p, 1)
        pr = dict(kind=pick(FEATURE_POOL, r_), scale=float(r_.uniform(0.85, 1.1)), flip=bool(r_.random() < 0.5))
        if try_place(pr, p, False): auto.append((pr, p))
    # 3. trees: the woods and the treeline worked out above, each a picture that fits its spot (smaller if need be)
    trees_by_size = sorted(dict(TREE_POOL), key=lambda k: SPRITES[k]["m"])
    for kind, p in props:
        if kind != "tree": continue
        r_ = prng(p, 2); first = pick(TREE_POOL, r_); sc = float(r_.uniform(0.85, 1.1)); fl = bool(r_.random() < 0.5)
        for k_ in [first] + [k for k in trees_by_size if SPRITES[k]["m"] < SPRITES[first]["m"]][:2][::-1]:
            pr = dict(kind=k_, scale=sc, flip=fl)
            if try_place(pr, p, True): auto.append((pr, p)); break
    # 4. small things to fill the rough: the bushes, rocks and tufts from above, plus a scatter of extra spots
    small = [p for kind, p in props if kind in ("bush", "rock", "tuft")]
    for p in FILL_SPOTS:
        z, _ = zone_at(p)
        if z is not None and z > -12: small.append(p)
    for p in small:
        r_ = prng(p, 3); k_ = pick(SMALL_POOL, r_)
        pr = dict(kind=k_, scale=float(SCALE.get(k_, 1) * r_.uniform(0.8, 1.1)), flip=bool(r_.random() < 0.5))
        if try_place(pr, p, False): auto.append((pr, p))
    props = [it for it in props if it[0][0] == "@"]
    for pr, p in auto:
        placed.append(pr); props.append((f"@{len(placed) - 1}", p))
elif placed:              # keep the automatic trees, bushes and rocks off placed pictures
    _clear = [(frame([pr["pt"]])[0], 0.5 * SPRITES[pr["kind"]]["m"] * float(pr.get("scale", 1))) for pr in placed]
    props = [it for it in props if it[0][0] == "@" or all(np.hypot(*(it[1] - c_)) > r_ for c_, r_ in _clear)]
props.sort(key=lambda it: to_screen(it[1])[1])
trees_out = []

INK = tuple(PAL["props"]) + (255,)
SHADOW = tuple(PAL["shadow"])
def blob(x, y, r, fillc, w=None):
    w = w or max(2, int(r * 0.12))
    cv.ellipse([x - r - w, y - r - w, x + r + w, y + r + w], fill=INK)
    cv.ellipse([x - r, y - r, x + r, y + r], fill=fillc)
def shade(col, k): return tuple(int(min(255, v * k)) for v in col[:3]) + (255,)

def themed_prop(kind, x, y, r_tree):
    """Space, neon and medieval props. Returns False for the classic look (drawn below)."""
    lw = lambda r, k=0.09: max(2, int(r * k))
    if THEME == "space":
        if kind == "tree":            # a cluster of crystal spires
            r = r_tree; g = [(90, 230, 240), (200, 120, 255), (120, 255, 200), (255, 130, 220)][int(rng.integers(4))]
            cv.ellipse([x - r * 1.1, y - r * 0.15, x + r * 1.4, y + r * 0.5], fill=SHADOW + (130,))
            for ox, hgt, wd in ((-0.45, 1.3, 0.32), (0.45, 1.1, 0.3), (0.0, 2.0, 0.42)):
                bx_, top = x + ox * r, y - hgt * r * 1.3
                pts = [(bx_ - wd * r, y), (bx_ - wd * r * 0.7, y - hgt * r * 0.9), (bx_, top), (bx_ + wd * r * 0.7, y - hgt * r * 0.9), (bx_ + wd * r, y)]
                cv.polygon(pts, fill=shade(g, 0.75), outline=INK, width=lw(r))
                cv.polygon([pts[1], pts[2], (bx_, y)], fill=shade(g, 1.15))
            cv.ellipse([x - r * 0.15, y - r * 2.45, x + r * 0.15, y - r * 2.15], fill=(255, 255, 255, 230))
        elif kind == "bush":          # a small glowing pod
            r = rng.uniform(2.5, 3.5) / mpp
            cv.ellipse([x - r * 1.4, y - r * 1.4, x + r * 1.4, y + r * 1.0], fill=(140, 255, 230, 50))
            cv.ellipse([x - r, y - r, x + r, y + r * 0.6], fill=(110, 230, 210, 255), outline=INK, width=lw(r, 0.14))
            cv.ellipse([x - r * 0.5, y - r * 0.8, x, y - r * 0.3], fill=(220, 255, 250, 255))
        elif kind == "rock":          # moon rocks
            r = rng.uniform(1.4, 2.4) / mpp * 0.8
            for dx, rr in ((0, 1.0), (r * 1.1, 0.6)):
                cv.ellipse([x + dx - r * rr, y - r * rr * 0.7, x + dx + r * rr, y + r * rr * 0.6], fill=(132, 126, 156, 255), outline=INK, width=lw(r, 0.15))
                cv.ellipse([x + dx - r * rr * 0.6, y - r * rr * 0.55, x + dx + r * rr * 0.2, y - r * rr * 0.1], fill=(196, 190, 220, 255))
        elif kind == "tuft":          # a twinkle
            r = rng.uniform(1.0, 1.8) / mpp
            col = (255, 250, 220, 255)
            cv.polygon([(x, y - r), (x + r * 0.22, y - r * 0.22), (x + r, y), (x + r * 0.22, y + r * 0.22), (x, y + r), (x - r * 0.22, y + r * 0.22), (x - r, y), (x - r * 0.22, y - r * 0.22)], fill=col)
        return True
    if THEME == "neon":
        if kind == "tree":            # a neon palm: dark trunk, glowing fronds
            r = r_tree; g = [(255, 47, 168), (0, 240, 255), (180, 90, 255), (255, 230, 80)][int(rng.integers(4))]
            cv.ellipse([x - r * 1.3, y - r * 0.35, x + r * 1.3, y + r * 0.35], fill=g + (60,))
            top = (x + r * 0.25, y - r * 1.9)
            cv.line([(x, y), (x + r * 0.12, y - r * 1.0), top], fill=(30, 18, 60, 255), width=lw(r, 0.22), joint="curve")
            cv.line([(x, y), (x + r * 0.12, y - r * 1.0), top], fill=g + (255,), width=lw(r, 0.06), joint="curve")
            for a in (-2.7, -2.1, -1.2, -0.45, 0.35):
                ex, ey = top[0] + math.cos(a) * r * 1.05, top[1] + math.sin(a) * r * 0.75 + r * 0.35
                mx_, my_ = (top[0] + ex) / 2, min(top[1], ey) - r * 0.25
                cv.line([top, (mx_, my_), (ex, ey)], fill=g + (90,), width=lw(r, 0.3), joint="curve")
                cv.line([top, (mx_, my_), (ex, ey)], fill=shade(g, 1.25), width=lw(r, 0.1), joint="curve")
            cv.ellipse([top[0] - r * 0.14, top[1] - r * 0.14, top[0] + r * 0.14, top[1] + r * 0.14], fill=(255, 255, 255, 255))
        elif kind == "bush":          # a glowing orb on a short post
            r = rng.uniform(1.6, 2.2) / mpp; g = (0, 240, 255) if rng.random() < 0.5 else (255, 47, 168)
            cv.line([x, y, x, y - r * 2], fill=(60, 40, 110, 255), width=lw(r, 0.3))
            cv.ellipse([x - r * 1.5, y - r * 3.5, x + r * 1.5, y - r * 0.5], fill=g + (55,))
            cv.ellipse([x - r * 0.7, y - r * 2.7, x + r * 0.7, y - r * 1.3], fill=shade(g, 1.2), outline=(255, 255, 255, 255), width=lw(r, 0.08))
        elif kind == "rock":          # a wireframe cube
            r = rng.uniform(1.2, 1.8) / mpp; g = (180, 90, 255)
            f_ = [(x - r, y - r * 0.4), (x, y), (x + r, y - r * 0.4), (x, y - r * 0.8)]
            cv.polygon([(px_, py_ - r * 1.1) for px_, py_ in f_], fill=(40, 20, 90, 255), outline=g + (255,), width=lw(r, 0.1))
            cv.polygon([f_[0], f_[1], (f_[1][0], f_[1][1] - r * 1.1), (f_[0][0], f_[0][1] - r * 1.1)], fill=(28, 14, 66, 255), outline=g + (255,), width=lw(r, 0.1))
            cv.polygon([f_[1], f_[2], (f_[2][0], f_[2][1] - r * 1.1), (f_[1][0], f_[1][1] - r * 1.1)], fill=(52, 26, 110, 255), outline=g + (255,), width=lw(r, 0.1))
        elif kind == "tuft":          # a spark
            r = rng.uniform(0.6, 1.0) / mpp
            cv.ellipse([x - r * 1.8, y - r * 1.8, x + r * 1.8, y + r * 1.8], fill=(255, 47, 168, 60))
            cv.ellipse([x - r * 0.5, y - r * 0.5, x + r * 0.5, y + r * 0.5], fill=(255, 220, 245, 255))
        return True
    if THEME == "medieval":
        if kind == "tree":            # dark pines and the odd round oak
            r = r_tree
            cv.ellipse([x - r * 1.1, y - r * 0.15, x + r * 1.4, y + r * 0.5], fill=SHADOW + (120,))
            if rng.random() < 0.7:
                g = [(52, 92, 44), (44, 80, 40), (60, 102, 50)][int(rng.integers(3))]
                cv.rectangle([x - r * 0.12, y - r * 0.5, x + r * 0.12, y + r * 0.1], fill=(92, 62, 36, 255), outline=INK, width=lw(r, 0.07))
                for k_, (yy, ww) in enumerate(((0.35, 0.95), (-0.35, 0.75), (-1.0, 0.55))):
                    tri = [(x - r * ww, y - r * 0.2 + yy * r - r * 0.25), (x, y - r * 1.45 + yy * r - r * 0.25), (x + r * ww, y - r * 0.2 + yy * r - r * 0.25)]
                    cv.polygon(tri, fill=shade(g, 0.9 + 0.08 * k_), outline=INK, width=lw(r))
                    cv.polygon([tri[0], tri[1], ((tri[0][0] + tri[2][0]) / 2, tri[0][1])], fill=shade(g, 1.05 + 0.08 * k_))
            else:
                g = (88, 118, 48)
                cv.rounded_rectangle([x - r * 0.2, y - r * 0.7, x + r * 0.2, y + r * 0.15], radius=int(r * 0.12), fill=(96, 66, 38, 255), outline=INK, width=lw(r, 0.08))
                top = y - r * 1.25
                for ox, oy, rr in ((-0.5, 0.15, 0.6), (0.5, 0.15, 0.6), (0, -0.3, 0.7)):
                    q = r * rr; w = lw(r, 0.1)
                    cv.ellipse([x + ox * r - q - w, top + oy * r - q - w, x + ox * r + q + w, top + oy * r + q + w], fill=INK)
                for ox, oy, rr in ((-0.5, 0.15, 0.6), (0.5, 0.15, 0.6), (0, -0.3, 0.7)):
                    q = r * rr
                    cv.ellipse([x + ox * r - q, top + oy * r - q, x + ox * r + q, top + oy * r + q], fill=shade(g, 0.9))
        elif kind == "bush":          # a hay bale, or now and then a little stone turret with a pennant
            if rng.random() < 0.25:
                r = rng.uniform(5.5, 7.0) / mpp; stone = (150, 144, 128)
                cv.ellipse([x - r * 1.2, y - r * 0.3, x + r * 1.5, y + r * 0.4], fill=SHADOW + (110,))
                cv.rectangle([x - r * 0.6, y - r * 2.2, x + r * 0.6, y], fill=shade(stone, 0.95), outline=INK, width=lw(r, 0.08))
                for k_ in range(3):
                    mx_ = x - r * 0.6 + k_ * r * 0.48
                    cv.rectangle([mx_, y - r * 2.55, mx_ + r * 0.3, y - r * 2.2], fill=shade(stone, 1.05), outline=INK, width=lw(r, 0.06))
                cv.rectangle([x - r * 0.15, y - r * 0.6, x + r * 0.15, y], fill=(60, 40, 24, 255))
                cv.rectangle([x - r * 0.12, y - r * 1.7, x + r * 0.12, y - r * 1.35], fill=(40, 34, 30, 255))
                cv.line([x, y - r * 2.55, x, y - r * 3.4], fill=INK, width=lw(r, 0.07))
                cv.polygon([(x, y - r * 3.4), (x + r * 0.8, y - r * 3.2), (x, y - r * 3.0)], fill=(200, 40, 40, 255), outline=INK)
            else:
                r = rng.uniform(1.6, 2.2) / mpp; straw = (214, 180, 90)
                cv.ellipse([x - r * 1.2, y - r * 0.2, x + r * 1.5, y + r * 0.45], fill=SHADOW + (100,))
                cv.rounded_rectangle([x - r, y - r * 1.1, x + r, y + r * 0.1], radius=int(r * 0.3), fill=shade(straw, 0.95), outline=INK, width=lw(r, 0.12))
                cv.line([x - r, y - r * 0.5, x + r, y - r * 0.5], fill=(150, 110, 50, 255), width=lw(r, 0.08))
        elif kind == "rock":          # tumbled stone blocks
            r = rng.uniform(1.0, 1.6) / mpp
            for dx, dy in ((0, 0), (r * 1.2, r * 0.2), (r * 0.55, -r * 0.7)):
                cv.rectangle([x + dx - r * 0.6, y + dy - r * 0.5, x + dx + r * 0.6, y + dy + r * 0.3], fill=(158, 152, 136, 255), outline=INK, width=lw(r, 0.12))
                cv.rectangle([x + dx - r * 0.6, y + dy - r * 0.5, x + dx + r * 0.6, y + dy - r * 0.3], fill=(196, 190, 172, 255))
        return False if kind == "tuft" else True
    return False

_sprite_cache = {}
# How a ball plays on a placed picture ("lie" in props.json; a solid one with none plays as trees). Each is baked
# into the lie grid: flat pictures (ponds, paths, bridges, long grass) by their drawn shape, upright ones (hay,
# buildings, rocks) by a circle round their ground point.
SPRITE_LIE = {"water": 7, "hay": 8, "sand": 6, "trees": 5, "path": 2, "rough": 0}   # 8: hay plays like a bunker
sprite_lie = []          # ("mask", code, mask, x, y) in base-picture px, or ("circle", code, x, y, r) in metres
flags_out = []           # waving flags for the game (see draw_sprite)
def sprite_lie_of(sp): return sp.get("lie") or ("trees" if sp["solid"] else None)
def draw_sprite(pr, p, x, y):
    sp = SPRITES[pr["kind"]]; mw = sp["m"] * float(pr.get("scale", 1)); lie_ = sprite_lie_of(sp)
    if lie_ == "trees":      # blocks shots like a tree (baked into the lie grid below)
        trees_out.append([round(float(p[0]), 2), round(float(p[1]), 2), round(0.35 * mw / 0.75, 2)])
    elif lie_ and not sp.get("flat") and lie_ not in ("water", "path", "rough"):
        sprite_lie.append(("circle", SPRITE_LIE[lie_], float(p[0]), float(p[1]), 0.4 * mw))
    f = mw / mpp / sp["w"]
    # flags the game waves over the painted ones: hoist corner, length and height in base-picture px,
    # how far down the hoist the tip sits, colour, and which way the cloth points (-1 when flipped)
    fl_ = bool(pr.get("flip")); ax0 = (sp["w"] - sp["anchor"][0] if fl_ else sp["anchor"][0]) * f
    for hx, hy, L, h, tip, col in sp.get("flags", []):
        fx = x - ax0 + (sp["w"] - hx if fl_ else hx) * f; fy = y + (hy - sp["anchor"][1]) * f
        flags_out.append([round((fx + OFFX) / U, 1), round((fy + OFFY) / U, 1), round(L * f / U, 2), round(h * f / U, 2), tip, col, -1 if fl_ else 1])
    if f * sp["w"] < 2: return
    key = (pr["kind"], round(f, 4), bool(pr.get("flip")))
    if key not in _sprite_cache:
        im = Image.open(sp["path"]).convert("RGBA")
        if pr.get("flip"): im = ImageOps.mirror(im)
        _sprite_cache[key] = im.resize((max(1, round(sp["w"] * f)), max(1, round(sp["h"] * f))), Image.LANCZOS)
    im = _sprite_cache[key]
    ax = (sp["w"] - sp["anchor"][0] if pr.get("flip") else sp["anchor"][0]) * f; ay = sp["anchor"][1] * f
    if not pr["kind"].startswith(("tile_", "path_", "grass_patch", "dirt_patch")) and sp.get("lie") != "water":
        r = mw / mpp / 2
        cv.ellipse([x - r * 0.8, y - r * 0.3, x + r * 1.15, y + r * 0.42], fill=SHADOW + (110,))
    base.paste(im, (round(x - ax), round(y - ay)), im)
    if lie_ == "water":     # only the blue of a pond picture is water, not its banks
        a_ = np.asarray(im).astype(int)
        blue = (a_[..., 3] > 128) & (a_[..., 2] > a_[..., 0] + 25) & (a_[..., 2] > a_[..., 1] + 5)
        sprite_lie.append(("mask", 7, blue, round(x - ax) + OFFX, round(y - ay) + OFFY))
    elif lie_ in ("path", "rough") or (lie_ and sp.get("flat") and lie_ != "trees"):
        sprite_lie.append(("mask", SPRITE_LIE[lie_], np.asarray(im)[..., 3] > 128, round(x - ax) + OFFX, round(y - ay) + OFFY))

for kind, p in props:
    x, y = to_screen(p)
    if kind[0] == "@":
        draw_sprite(placed[int(kind[1:])], p, x, y); continue
    if THEME != "classic":
        r_tree = rng.uniform(6, 9.5) / mpp * 0.85
        if kind == "tree":
            trees_out.append([round(float(p[0]), 2), round(float(p[1]), 2), round(float(r_tree * mpp * 0.9), 2)])
        if themed_prop(kind, x, y, r_tree): continue
    if kind == "tree":
        r = rng.uniform(6, 9.5) / mpp * 0.85
        trees_out.append([round(float(p[0]), 2), round(float(p[1]), 2), round(float(r * mpp * 0.9), 2)])
        g = rng.choice([(78, 160, 52), (64, 146, 44), (92, 172, 60), (58, 128, 40)])
        cv.ellipse([x - r * 1.1, y - r * 0.15, x + r * 1.4, y + r * 0.55], fill=(30, 70, 20, 110))  # shadow
        tw, th_ = r * 0.22, r * 0.7
        cv.rounded_rectangle([x - tw, y - th_, x + tw, y + r * 0.15], radius=int(tw * 0.6), fill=(110, 72, 40, 255), outline=INK, width=max(2, int(r * 0.08)))
        top = y - th_ - r * 0.55
        lobes = [(-0.55, 0.15, 0.62), (0.55, 0.15, 0.62), (0, -0.35, 0.72), (-0.2, 0.25, 0.6), (0.25, 0.3, 0.55)]
        for ox, oy, rr in lobes:   # ink pass
            q = r * rr; w = max(2, int(r * 0.1))
            cv.ellipse([x + ox * r - q - w, top + oy * r - q - w, x + ox * r + q + w, top + oy * r + q + w], fill=INK)
        for ox, oy, rr in lobes:   # fill pass (no inner outlines -> clean silhouette)
            q = r * rr
            cv.ellipse([x + ox * r - q, top + oy * r - q, x + ox * r + q, top + oy * r + q], fill=shade(g, 0.86))
        for ox, oy, rr in lobes[:3]:  # lit tops
            q = r * rr * 0.7
            cv.ellipse([x + ox * r - q * 1.05, top + oy * r - q * 1.15, x + ox * r + q * 0.8, top + oy * r + q * 0.55], fill=shade(g, 1.08))
        hq = r * 0.16
        cv.ellipse([x - r * 0.35 - hq, top - r * 0.55 - hq, x - r * 0.35 + hq * 1.5, top - r * 0.55 + hq], fill=shade(g, 1.3))
    elif kind == "bush":
        r = rng.uniform(3.5, 5) / mpp * 0.8
        g = (52, 120, 46)
        cv.ellipse([x - r, y - r * 0.2, x + r * 1.3, y + r * 0.45], fill=(30, 70, 20, 100))
        for ox in (-0.5, 0.5, 0):
            q = r * (0.6 if ox else 0.75); w = max(2, int(r * 0.12))
            cv.ellipse([x + ox * r - q - w, y - r * 0.5 - q - w, x + ox * r + q + w, y - r * 0.5 + q + w], fill=INK)
        for ox in (-0.5, 0.5, 0):
            q = r * (0.6 if ox else 0.75)
            cv.ellipse([x + ox * r - q, y - r * 0.5 - q, x + ox * r + q, y - r * 0.5 + q], fill=shade(g, 1))
        for k in range(4):
            a = rng.uniform(-0.6, 0.6) * r
            cv.arc([x + a - r * 0.18, y - r * 0.75, x + a + r * 0.18, y - r * 0.45], 200, 340, fill=shade(g, 0.7), width=max(2, int(r * 0.08)))
    elif kind == "rock":
        r = rng.uniform(1.2, 2.0) / mpp * 0.8
        for dx, rr in ((0, 1.0), (r * 1.1, 0.65)):
            cv.ellipse([x + dx - r * rr, y - r * rr * 0.7, x + dx + r * rr, y + r * rr * 0.6], fill=(160, 166, 160, 255), outline=(70, 80, 70, 255), width=max(2, int(r * 0.15)))
            cv.ellipse([x + dx - r * rr * 0.6, y - r * rr * 0.55, x + dx + r * rr * 0.2, y - r * rr * 0.1], fill=(215, 220, 214, 255))
    elif kind == "tuft":
        r = rng.uniform(2, 3) / mpp * 0.8; w = max(2, int(r * 0.16))
        for a in (-0.6, -0.2, 0.25, 0.6):
            cv.line([x + a * r * 0.4, y, x + a * r * 1.2, y - r * (1.1 - abs(a) * 0.5)], fill=(50, 110, 40, 255), width=w)

# ---------------- flag and tee markers (no yardage markers on the fairway) ----------------
fx, fy = to_screen(G); ps = 1 / mpp
NOFLAG = os.environ.get("GAME") == "1"     # the game draws its own flag on top
if NOFLAG: fx = fy = -1e6
cv.ellipse([fx - 1.6 * ps, fy - 0.5 * ps, fx + 1.6 * ps, fy + 0.5 * ps], fill=(30, 60, 20, 90))
cv.line([fx, fy, fx + 4 * ps, fy + 1.5 * ps], fill=(30, 60, 20, 90), width=int(0.5 * ps))
cv.ellipse([fx - 0.6 * ps, fy - 0.3 * ps, fx + 0.6 * ps, fy + 0.3 * ps], fill=(20, 20, 20, 255))
pole_h = 7 * ps
cv.line([fx, fy, fx, fy - pole_h], fill=INK, width=int(0.75 * ps))
cv.line([fx, fy, fx, fy - pole_h], fill=(245, 245, 245, 255), width=int(0.35 * ps))
flag = [(fx, fy - pole_h), (fx + 3.6 * ps, fy - pole_h + 0.9 * ps), (fx + 3.0 * ps, fy - pole_h + 1.4 * ps), (fx + 3.8 * ps, fy - pole_h + 2.1 * ps), (fx, fy - pole_h + 2.6 * ps)]
cv.polygon(flag, fill=(228, 44, 50, 255), outline=INK, width=max(2, int(0.25 * ps)))
for dx in (-2.5, 2.5):
    x, y = to_screen((T[0] + dx, T[1]))
    cv.ellipse([x - 0.6 * ps, y - 0.6 * ps, x + 0.6 * ps, y + 0.4 * ps], fill=(245, 214, 50, 255), outline=INK, width=2)

try:
    fb = lambda n: ImageFont.truetype("DejaVuSans-Bold.ttf", n)
    font = fb(int(13 * U))
except OSError:
    fb = lambda n: ImageFont.load_default(); font = fb(0)
img_out = base.resize((CW // SS, CH // SS), Image.LANCZOS)
d = ImageDraw.Draw(img_out, "RGBA")
if os.environ.get("GAME") == "1" or DETAIL:
    img_out.save(out); print("saved (no title)", out)
else:
  if True:
    d.rounded_rectangle([20, 18, 360, 120], 18, fill=(40, 80, 34, 235), outline=(150, 200, 120, 255), width=3)
    d.text((42, 26), f"HOLE {H['hole']}", font=fb(44), fill=(255, 255, 255), stroke_width=3, stroke_fill=(20, 40, 15))
    d.text((44, 80), f"Par {H['par']} • {H['yards_yellow']} yds (yellow)", font=fb(22), fill=(200, 240, 120), stroke_width=2, stroke_fill=(20, 40, 15))
    # compass: screen direction of north
    nvec = cR @ (R @ np.array([0.0, 1.0])); nx, ny = nvec[0], -nvec[1] * TILT; nn = math.hypot(nx, ny); nx, ny = nx / nn, ny / nn
    ccx, ccy = OUT_W - 60, 60
    d.ellipse([ccx - 36, ccy - 36, ccx + 36, ccy + 36], fill=(40, 80, 34, 235), outline=(150, 200, 120, 255), width=3)
    d.polygon([(ccx + nx * 26, ccy + ny * 26), (ccx - ny * 10 - nx * 8, ccy + nx * 10 - ny * 8), (ccx + ny * 10 - nx * 8, ccy - nx * 10 - ny * 8)], fill=(230, 50, 50), outline=(30, 30, 30))
    img_out.save(out)
print("saved", out, "props", len(props))

# ---------------- export game data ----------------
if len(sys.argv) > 3 and not DETAIL:
    CELL = 2.0
    gx0, gy0 = bx[0], by[0]
    nx_, ny_ = int((bx[1] - bx[0]) / CELL), int((by[1] - by[0]) / CELL)
    cxs = gx0 + (np.arange(nx_) + 0.5) * CELL; cys = gy0 + (np.arange(ny_) + 0.5) * CELL
    CX, CY = np.meshgrid(cxs, cys)
    q = np.einsum("ij,jkl->ikl", cR, np.stack([CX - mid[0], CY - mid[1]]))
    sx = (W / 2 + q[0] * s).astype(int); sy = (Hh / 2 + 25 * SS - q[1] * s * TILT).astype(int)
    inb = (sx >= 0) & (sx < W) & (sy >= 0) & (sy < Hh)
    sxc, syc = np.clip(sx, 0, W - 1), np.clip(sy, 0, Hh - 1)
    lie = np.zeros(CX.shape, np.uint8)
    # 0 rough, 1 first cut, 2 fairway, 3 green, 4 tee, 5 trees/woods, 6 bunker, 7 water, 8 hay, 9 off the map
    at = lambda m: m[syc, sxc]
    lie[at(cut)] = 1; lie[at(wood)] = 5
    lie[at(fairway | ofair | ogreen | otee)] = 2
    lie[at(bunker)] = 6; lie[at(water)] = 7
    # placed pictures: water first, then the rest in drawing order (so a bridge or path laid over water wins)
    for it in sorted(sprite_lie, key=lambda it: it[1] != 7):
        if it[0] == "mask":
            _, code, wm, wx, wy = it
            rx, ry = sx - wx, sy - wy
            ins = (rx >= 0) & (ry >= 0) & (rx < wm.shape[1]) & (ry < wm.shape[0])
            hit = np.zeros_like(ins); hit[ins] = wm[ry[ins], rx[ins]]
        else:
            _, code, tx, ty, tr = it
            hit = np.hypot(CX - tx, CY - ty) < tr
        lie[hit] = code
    lie[at(teebox)] = 4; lie[at(green)] = 3
    # trees are baked in too (the game no longer checks every tree for every step of a putt)
    for tx, ty, tr in trees_out:
        rr = tr * 0.75
        i0, i1 = int((tx - rr - gx0) / CELL), int((tx + rr - gx0) / CELL) + 1
        j0, j1 = int((ty - rr - gy0) / CELL), int((ty + rr - gy0) / CELL) + 1
        for j in range(max(j0, 0), min(j1 + 1, ny_)):
            for i in range(max(i0, 0), min(i1 + 1, nx_)):
                if math.hypot(cxs[i] - tx, cys[j] - ty) < rr and lie[j, i] in (0, 1, 2): lie[j, i] = 5
    lie[~inb] = 9
    A = np.diag([s, -s * TILT]) @ cR / SS
    b = (np.array([W / 2, Hh / 2 + 25 * SS]) - np.diag([s, -s * TILT]) @ cR @ mid) / SS
    data = dict(A=A.round(6).tolist(), b=b.round(3).tolist(), tee=T.round(2).tolist(), pin=G.round(2).tolist(),
                par=H["par"], hole=H["hole"], yards=H["yards_yellow"], cell=CELL, gx0=round(float(gx0), 2), gy0=round(float(gy0), 2),
                nx=nx_, ny=ny_, lie=base64.b64encode(lie.tobytes()).decode(), trees=trees_out, img=[OUT_W, OUT_H])
    if flags_out: data["flags"] = flags_out
    # the ground's height for the game's ball roll: every 2 m over the picture, cm above its lowest point
    _g = ZW[::4, ::4]; _z0 = float(_g.min())
    data["ground"] = dict(x0=round(float(bx[0]), 2), y0=round(float(by[0]), 2), cell=4 * WC, nx=int(_g.shape[1]), ny=int(_g.shape[0]),
                          cm=base64.b64encode(np.round((_g - _z0) * 100).clip(-32000, 32000).astype("<i2").tobytes()).decode())
    json.dump(data, open(sys.argv[3], "w"))
    print("game data", nx_, ny_, len(trees_out))

# ---------------- green heat map + slope data ----------------
if len(sys.argv) > 3:
    gg = H["green_grid"]; n = gg["n"]; step = gg["step"]
    gcm = np.frombuffer(base64.b64decode(gg["cm"]), dtype="<i2").reshape(n, n).astype(float)
    c_, s_ = math.cos(-north_rot), math.sin(-north_rot)
    ys_, xs_ = np.nonzero(green)
    y0_, y1_, x0_, x1_ = ys_.min() - 8, ys_.max() + 8, xs_.min() - 8, xs_.max() + 8
    Xg, Yg = X[y0_:y1_, x0_:x1_] - G[0], Y[y0_:y1_, x0_:x1_] - G[1]
    E, N = c_ * Xg - s_ * Yg, s_ * Xg + c_ * Yg
    hz = map_coordinates(gcm, [(n - 1) / 2 - N / step, (n - 1) / 2 + E / step], order=3, mode="nearest") / 100.0
    gm = green[y0_:y1_, x0_:x1_]
    lo, hi = np.percentile(hz[gm], [3, 97]); tt = np.clip((hz - lo) / (hi - lo + 1e-6), 0, 1)
    # cartoon palette: saturated flat bands (posterised), low = blue, high = red
    stops = np.array([[30, 80, 255], [0, 200, 255], [60, 230, 90], [190, 245, 40],
                      [255, 220, 0], [255, 140, 0], [255, 40, 70]], float)
    BANDS = 9
    tq = np.round(tt * (BANDS - 1)) / (BANDS - 1)
    pos = tq * (len(stops) - 1); i0 = np.clip(pos.astype(int), 0, len(stops) - 2); fr = (pos - i0)[..., None]
    rgb = stops[i0] * (1 - fr) + stops[i0 + 1] * fr
    soft = gaussian_filter(gm.astype(float), 0.5 * U)
    alpha = soft * 0.78 * 255
    heat = Image.fromarray(np.dstack([rgb, alpha]).clip(0, 255).astype(np.uint8), "RGBA")
    # 5 cm contour lines, as their own layer so the game can switch them on/off; thin and anti-aliased
    lv = np.floor(hz / 0.05)
    edge = (np.abs(np.diff(lv, axis=0, prepend=lv[:1])) + np.abs(np.diff(lv, axis=1, prepend=lv[:, :1]))) > 0
    ca = np.clip(gaussian_filter(edge.astype(float), 0.1 * U) * 2.2, 0, 1) * soft * 0.7 * 255
    cont = Image.fromarray(np.dstack([np.full(hz.shape + (3,), (18, 40, 28), float), ca]).clip(0, 255).astype(np.uint8), "RGBA")
    hw, hh = heat.size
    heat = heat.resize((max(1, hw // SS), max(1, hh // SS)), Image.LANCZOS)
    cont = cont.resize(heat.size, Image.LANCZOS)
    heat_name = out.rsplit(".", 1)[0] + "_heat.png"
    cont_name = out.rsplit(".", 1)[0] + "_contours.png"
    heat.save(heat_name); cont.save(cont_name)
    heat_entry = dict(file=heat_name.split("/")[-1], contours=cont_name.split("/")[-1],
                      x=(x0_ + OFFX) / U, y=(y0_ + OFFY) / U, w=hw / U, h=hh / U)
    if DETAIL:
        json.dump(dict(tile=dict(file=out.split("/")[-1], x=dx_, y=dy_, w=dw_, h=dh_), heat=heat_entry), open(sys.argv[3], "w"))
        print("detail tile", out, img_out.size, "heat", heat.size); sys.exit()
    data = json.load(open(sys.argv[3]))
    data.update(heat=heat_entry,
                green_grid=dict(n=n, step=step, cm=gcm.astype(int).ravel().tolist()), north_rot=north_rot)
    json.dump(data, open(sys.argv[3], "w"))
    print("heat map", heat_name, heat.size, "relief cm", round((hi - lo) * 100, 1))
