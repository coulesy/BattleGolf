"""Cartoon / faux-isometric render of one hole from Pure Golf point data.
Same inputs as render_hole.py (tee, layup, green front/centre/back, elevation grids)."""
import json, base64, sys, math
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from scipy.ndimage import gaussian_filter, map_coordinates, binary_erosion
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

# ---------------- centreline + shapes ----------------
C = 2 * L - (T + G) / 2
t = np.linspace(0, 1, 3000)[:, None]
curve = (1 - t) ** 2 * T + 2 * t * (1 - t) * C + t ** 2 * G
arc = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(curve, axis=0), axis=1))])
total = arc[-1]
dist, idx = cKDTree(curve).query(np.stack([X.ravel(), Y.ravel()], 1))
dist, sarc = dist.reshape(X.shape), arc[idx].reshape(X.shape)

green_len = np.linalg.norm(GB - GF); ga = (GB - GF) / green_len
gc = (GF + GB) / 4 + G / 2
a_ax = green_len / 2 + 3.0; b_ax = a_ax * 0.8
du, dv = X - gc[0], Y - gc[1]
gu = du * ga[0] + dv * ga[1]; gv = -du * ga[1] + dv * ga[0]
thg = np.arctan2(gv, gu)
gr = np.sqrt((gu / a_ax) ** 2 + (gv / b_ax) ** 2) - (0.07 * np.sin(3 * thg + 1) + 0.04 * np.sin(5 * thg))
green = gr < 1.0

fw_start = 80.0
half_w = 15 + 4 * np.exp(-((sarc - 230) / 60) ** 2) - 4 * np.clip((sarc - (total - 60)) / 50, 0, 1) + 2.0 * nb
fairway = (dist < half_w * np.clip((sarc - fw_start) / 8, 0, 1)) & (sarc < total - 2)
fairway |= gr < 1.25
cut = (dist < (half_w + 10) * np.clip((sarc - fw_start + 10) / 10, 0, 1)) | (gr < 1.0 + 9 / a_ax)
cut &= sarc > fw_start - 12
tu, tv = X - T[0], Y - (T[1] - 4)
teebox = (np.abs(tu) < 6) & (np.abs(tv) < 9)
teepad = (np.abs(tu) < 10) & (np.abs(tv) < 13)

# ---------------- elevation -> toon hill shading ----------------
grid = np.array(H["grid"]).reshape(12, 21)
ACROSS = 10.0
WXg, WYg = np.meshgrid(bx[0] + np.arange(wnx) * WC, by[0] + np.arange(wny) * WC)
ZW = map_coordinates(grid, [np.clip((WYg - T[1]) / D * 11, 0, 11), np.clip((WXg - T[0]) / ACROSS + 10, 0, 20)], order=1)
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
img[cut] = cutc[band][cut]
stripe = (np.floor(sarc / 9) % 2).astype(bool)
fwc = np.where(stripe[..., None], c("#8fd64a"), c("#7cc83c"))
img[fairway] = fwc[fairway]
gstripe = (np.floor(gu / 2.5) % 2).astype(bool)
gcol = np.where(gstripe[..., None], c("#b2ec66"), c("#a5e25c"))
img[green] = gcol[green]
img[teepad] = c("#4b9a2b")
tstripe = (np.floor(tv / 3) % 2).astype(bool)
tcol = np.where(tstripe[..., None], c("#9ee056"), c("#8ad24a"))
img[teebox] = tcol[teebox]

# outlines: edge of each region in a darker ink
ink = c("#2d5f1a")
def outline(mask, width_px, colr=ink, alpha=1.0):
    e = mask & ~binary_erosion(mask, iterations=int(round(width_px)))
    img[e] = img[e] * (1 - alpha) + colr * alpha
outline(cut, 4 * U, alpha=0.95)
outline(fairway, 3 * U, c("#3c7e22"), 0.85)
outline(green, 2 * U, c("#4f9a2b"), 0.9)
outline(teepad, 2 * U, alpha=0.8)
outline(teebox, 2 * U, c("#3c7e22"), 0.8)
# soft ink along hill-band boundaries in the rough (cartoon contours)
bedge = (np.abs(np.diff(band, axis=0, prepend=band[:1])) + np.abs(np.diff(band, axis=1, prepend=band[:, :1]))) > 0
bedge = gaussian_filter(bedge.astype(float), 1.2 * U) > 0.2
bedge &= ~cut
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
    return d_ - hw - 30 - 8 * n_, n_
props = []
for p in rng.uniform([bx[0], by[0]], [bx[1], by[1]], (1500, 2)):
    z, clump = zone_at(p)
    if z is None: continue
    nearG = np.hypot(*(p - gc)) < a_ax + 16; nearT = np.hypot(*(p - T)) < 18
    if nearG or nearT: continue
    if z > 0 and rng.random() < (0.15 + 0.75 * min(z / 25, 1)) * (clump > -0.2):
        props.append(("tree", p))
    elif z > -14 and rng.random() < 0.05:
        props.append(("bush", p))
    elif z > -16 and rng.random() < 0.05:
        props.append(("rock", p))
    elif z > -18 and rng.random() < 0.09:
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
    lie[cut[syc, sxc]] = 1; lie[teebox[syc, sxc]] = 4; lie[fairway[syc, sxc]] = 2; lie[green[syc, sxc]] = 3
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
    stops = np.array([[40, 90, 220], [40, 190, 230], [90, 215, 90], [250, 225, 60], [235, 70, 50]], float)
    pos = tt * (len(stops) - 1); i0 = np.clip(pos.astype(int), 0, len(stops) - 2); fr = (pos - i0)[..., None]
    rgb = stops[i0] * (1 - fr) + stops[i0 + 1] * fr
    lv = np.floor(hz / 0.05)                                  # 5 cm contour lines
    edge = (np.abs(np.diff(lv, axis=0, prepend=lv[:1])) + np.abs(np.diff(lv, axis=1, prepend=lv[:, :1]))) > 0
    edge = gaussian_filter(edge.astype(float), 0.6 * U) > 0.15 / K
    rgb[edge] *= 0.55
    alpha = gaussian_filter(gm.astype(float), 0.5 * U) * 0.62 * 255
    alpha[edge & gm] = 200
    heat = Image.fromarray(np.dstack([rgb, alpha]).clip(0, 255).astype(np.uint8), "RGBA")
    hw, hh = heat.size
    heat = heat.resize((max(1, hw // SS), max(1, hh // SS)), Image.LANCZOS)
    heat_name = out.rsplit(".", 1)[0] + "_heat.png"
    heat.save(heat_name)
    heat_entry = dict(file=heat_name.split("/")[-1], x=(x0_ + OFFX) / U, y=(y0_ + OFFY) / U, w=hw / U, h=hh / U)
    if DETAIL:
        json.dump(dict(tile=dict(file=out.split("/")[-1], x=dx_, y=dy_, w=dw_, h=dh_), heat=heat_entry), open(sys.argv[3], "w"))
        print("detail tile", out, img_out.size, "heat", heat.size); sys.exit()
    data = json.load(open(sys.argv[3]))
    data.update(heat=heat_entry,
                green_grid=dict(n=n, step=step, cm=gcm.astype(int).ravel().tolist()), north_rot=north_rot)
    json.dump(data, open(sys.argv[3], "w"))
    print("heat map", heat_name, heat.size, "relief cm", round((hi - lo) * 100, 1))
