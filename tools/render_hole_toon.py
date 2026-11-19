"""Cartoon / faux-isometric render of one hole from Pure Golf point data.
Same inputs as render_hole.py (tee, layup, green front/centre/back, elevation grids)."""
import json, base64, sys, math
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from scipy.ndimage import gaussian_filter, map_coordinates, binary_erosion, distance_transform_edt
from scipy.spatial import cKDTree

src, out = sys.argv[1], sys.argv[2]
H = json.load(open(src))
rng = np.random.default_rng(7)

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
SS = 2
import os
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
    S_ = lambda Wm: world_sample(np.asarray(Wm, float), X, Y) > 0.5
    wood, water, bunker = S_(W_wood), S_(W_water), S_(W_bunker)
    ogreen, otee = S_(W_green_oth), S_(W_tee)
    ofair = S_(W_fair_osm) | S_(W_nfair); ocut = S_(W_ncut)

# ---------------- centreline + shapes ----------------
C = 2 * L - (T + G) / 2
t = np.linspace(0, 1, 3000)[:, None]
curve = (1 - t) ** 2 * T + 2 * t * (1 - t) * C + t ** 2 * G
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
    green = world_sample(W_green_own, X, Y) > 0.5
    GD = distance_transform_edt(W_green_own < 0.5) * WC          # metres outside the real green
    gdist = world_sample(GD, X, Y)
else:
    gdist = (gr - 1.0) * a_ax                                     # roughly metres outside the generated green

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
    WGd = GD
else:
    WGd = (green_r(WXw - gc[0], WYw - gc[1])[2] - 1.0) * a_ax
Wfr = (WDst < Whw) & (WSarc > fw_start) & (WSarc < total - 2)
if D < 200: Wfr &= WSarc > total - 45
Wfr |= WGd < 2.5
Wcr = ((WDst < Whw + 10) & (WSarc > fw_start - 12)) | (WGd < 9)
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
    cut &= ~wood; cut |= ocut
else:
    cut &= ~water

# ---------------- elevation -> toon hill shading ----------------
# Same layout as the Pure Golf app's generateHoleGrid: rows every total/(rows-1) metres from the tee to 20 m
# past the green, columns 18 m apart either side of the tee->green line (positive = right of the line).
GSTEP, gtotal = 18.0, D + 20.0
garr = np.array(H["grid"], float)
half = min(max(math.floor(gtotal / 2 / GSTEP + 0.5), 1), 12)
for h_ in (half, half - 1, half + 1):                # distances differ slightly from the app's: try neighbours
    if h_ >= 1 and len(garr) % (2 * h_ + 1) == 0 and len(garr) // (2 * h_ + 1) >= 3: half = h_; break
gcols = 2 * half + 1; grows = len(garr) // gcols
grid = garr[:grows * gcols].reshape(grows, gcols)
WXg, WYg = np.meshgrid(bx[0] + np.arange(wnx) * WC, by[0] + np.arange(wny) * WC)
ZW = map_coordinates(grid, [np.clip((WYg - T[1]) / (gtotal / (grows - 1)), 0, grows - 1),
                            np.clip((WXg - T[0]) / GSTEP + half, 0, gcols - 1)], order=1)
ZW = gaussian_filter(ZW, 14 / WC) + 0.35 * NBW
gyw, gxw = np.gradient(ZW * 6, WC)
lx, ly = cR.T @ np.array([-0.7, 0.7])          # light from top-left of the *screen*
HSW = gaussian_filter((gxw * lx + gyw * ly) / np.sqrt(1 + gxw ** 2 + gyw ** 2), 3 / WC)
hs = world_sample(HSW, X, Y)
band = np.digitize(hs, [-0.12, 0.10])          # 0 shadow, 1 mid, 2 lit

# ---------------- paint flat colours ----------------
def c(h): return np.array([int(h[i:i + 2], 16) for i in (1, 3, 5)], float)
rough = np.stack([c("#4f9e2a"), c("#62b434"), c("#74c63e")])
img = rough[band].copy()
def fill(mask, colr): img[mask] = colr
cutc = np.stack([c("#3f8a24"), c("#4b9a2b"), c("#56a831")])
woodc = np.stack([c("#3a7a22"), c("#438727"), c("#4c912b")])        # forest floor
img[wood] = woodc[band][wood]
img[cut] = cutc[band][cut]
stripe = (np.floor(sarc / 9) % 2).astype(bool)
fwc = np.where(stripe[..., None], c("#8fd64a"), c("#7cc83c"))
allfair = fairway | ofair
img[allfair] = fwc[allfair]
gstripe = (np.floor(gu / 2.5) % 2).astype(bool)
gcol = np.where(gstripe[..., None], c("#b2ec66"), c("#a5e25c"))
img[ogreen] = gcol[ogreen]
img[green] = gcol[green]
tstripe = (np.floor(tv / 3) % 2).astype(bool)
tcol = np.where(tstripe[..., None], c("#9ee056"), c("#8ad24a"))
img[otee & ~green] = tcol[otee & ~green]
img[teepad] = c("#4b9a2b")
img[teebox] = tcol[teebox]
# sand: warm, lighter towards the lit side; water: blue with soft noise ripples
sandc = np.stack([c("#e2c46e"), c("#efd486"), c("#f7e3a0")])
img[bunker] = sandc[band][bunker]
rip = (np.sin((X * 0.7 + Y * 0.35) + 3 * nb) > 0.75)
waterc = np.where(rip[..., None], c("#7ad2f5"), c("#45aee6"))
img[water] = waterc[water]

# outlines: edge of each region in a darker ink
ink = c("#2d5f1a")
def outline(mask, width_px, colr=ink, alpha=1.0):
    # a detail tile is a window onto the full picture: regions that run off its edge carry on,
    # so the tile border must not count as a region edge (that drew a hard line across the fairway)
    e = mask & ~binary_erosion(mask, iterations=int(round(width_px)), border_value=1 if DETAIL else 0)
    img[e] = img[e] * (1 - alpha) + colr * alpha
outline(cut, 4 * U, alpha=0.95)
outline(allfair, 3 * U, c("#3c7e22"), 0.85)
outline(green, 2 * U, c("#4f9a2b"), 0.9)
outline(ogreen, 2 * U, c("#4f9a2b"), 0.9)
outline(otee, 2 * U, c("#3c7e22"), 0.8)
outline(bunker, 3 * U, c("#b48a3c"), 0.95)
outline(water, 3 * U, c("#2a6aa0"), 0.95)
outline(teepad, 2 * U, alpha=0.8)
outline(teebox, 2 * U, c("#3c7e22"), 0.8)
# soft ink along hill-band boundaries in the rough (cartoon contours)
bedge = (np.abs(np.diff(band, axis=0, prepend=band[:1])) + np.abs(np.diff(band, axis=1, prepend=band[:, :1]))) > 0
bedge = gaussian_filter(bedge.astype(float), 1.2 * U) > 0.2
bedge &= ~cut & ~bunker & ~water & ~ogreen & ~ofair
img[bedge] = img[bedge] * 0.86

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
        if d_ < 29 and fw_start - 15 < sa < total + 5: return False      # this hole's fairway and first cut
        if np.hypot(*(p - T)) < 14 or np.hypot(*(p - G)) < a_ax + 12: return False
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
            if not (-80 <= q[0] < W + 80 and -80 <= q[1] < Hh + 80): continue
            if too_close(p, gap) or not clear_of_play(p): continue
            cells.setdefault((int(p[0] // 8), int(p[1] // 8)), []).append(p); props.append(("tree", p))
for p in rng.uniform([bx[0], by[0]], [bx[1], by[1]], (2600, 2)):
    z, clump = zone_at(p)
    if z is None: continue
    nearG = np.hypot(*(p - gc)) < a_ax + 16; nearT = np.hypot(*(p - T)) < 18
    if nearG or nearT: continue
    if in_world(W_play, p) or (OSM_ON and in_world(W_wood, p)): continue
    if z > 0 and not OSM_ON and rng.random() < (0.35 + 0.6 * min(z / 12, 1)) * (clump > -0.6):   # tight treeline
        props.append(("tree", p))
    elif z > -3 and rng.random() < 0.05:
        props.append(("bush", p))
    elif z > -3.5 and rng.random() < 0.05:
        props.append(("rock", p))
    elif z > -4 and rng.random() < 0.09:
        props.append(("tuft", p))
props.sort(key=lambda it: to_screen(it[1])[1])
trees_out = []

INK = (34, 70, 24, 255)
def blob(x, y, r, fillc, w=None):
    w = w or max(2, int(r * 0.12))
    cv.ellipse([x - r - w, y - r - w, x + r + w, y + r + w], fill=INK)
    cv.ellipse([x - r, y - r, x + r, y + r], fill=fillc)
def shade(col, k): return tuple(int(min(255, v * k)) for v in col[:3]) + (255,)

for kind, p in props:
    x, y = to_screen(p)
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

# ---------------- flag, tee markers, yardages ----------------
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
def at_yards(yd):
    j = np.argmin(np.abs(np.linalg.norm(curve - G, axis=1) - yd * 0.9144) + (arc > total - 20) * 1e9)
    return curve[j]
for yd, colr in ((100, (245, 245, 245)), (150, (245, 205, 40)), (200, (40, 140, 230))):
    if yd * 0.9144 < D - 10:
        x, y = to_screen(at_yards(yd)); r = 5 * U
        cv.ellipse([x - r, y - r * 0.8, x + r, y + r * 0.8], fill=colr + (255,), outline=INK, width=int(U) + 1)
        cv.text((x + 9 * U, y), str(yd), font=font, anchor="lm", fill=(255, 255, 255), stroke_width=int(3 * U), stroke_fill=(30, 55, 25))

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
    # 0 rough, 1 first cut, 2 fairway, 3 green, 4 tee, 5 trees/woods, 6 bunker, 7 water, 9 off the map
    at = lambda m: m[syc, sxc]
    lie[at(cut)] = 1; lie[at(wood)] = 5
    lie[at(fairway | ofair | ogreen | otee)] = 2
    lie[at(bunker)] = 6; lie[at(water)] = 7
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
