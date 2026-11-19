"""Procedural bird's-eye render of one hole from Pure Golf point data only.
Inputs: tee, layup, green centre/front/back, hole elevation grid, green elevation grid.
No bunkers / water (not in the data)."""
import json, base64, sys, math
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from scipy.ndimage import gaussian_filter, map_coordinates
from scipy.spatial import cKDTree

src, out = sys.argv[1], sys.argv[2]
H = json.load(open(src))
rng = np.random.default_rng(13)

# ---------- geo -> local metres, rotated so tee->green points up ----------
lat0, lng0 = H["tee"]
kx, ky = math.cos(math.radians(lat0)) * 111320.0, 110540.0
def to_m(p): return np.array([(p[1] - lng0) * kx, (p[0] - lat0) * ky])
T, L, G = to_m(H["tee"]), to_m(H["layup"]), to_m(H["green"])
GF, GB = to_m(H["green_front"]), to_m(H["green_back"])
axis = (G - T) / np.linalg.norm(G - T)
ang = math.atan2(axis[0], axis[1])            # rotate so axis -> +y
R = np.array([[math.cos(ang), -math.sin(ang)], [math.sin(ang), math.cos(ang)]])
rot = lambda p: R @ p
T, L, G, GF, GB = map(rot, (T, L, G, GF, GB))
north_rot = ang                                 # for compass + north-up grids
D = np.linalg.norm(G - T)

# ---------- canvas ----------
SS, PPM = 2, 3.0                                # supersample, final px per metre
s = PPM * SS
xs = [T[0], L[0], G[0]]
xmin, xmax = min(xs) - 75, max(xs) + 75
ymin, ymax = -35, D + 45
W, Hh = int((xmax - xmin) * s), int((ymax - ymin) * s)
px, py = np.meshgrid(np.arange(W), np.arange(Hh))
X = xmin + (px + 0.5) / s
Y = ymax - (py + 0.5) / s

def fbm(shape, scales, amps, seed):
    r = np.random.default_rng(seed); a = np.zeros(shape)
    for sc, am in zip(scales, amps):
        n = gaussian_filter(r.standard_normal(shape), sc * s)
        a += am * n / (n.std() + 1e-9)
    return a
noise_big = fbm(X.shape, [14, 6], [1.0, 0.5], 1)
noise_fine = fbm(X.shape, [1.2, 0.4], [1.0, 0.6], 2)

# ---------- centreline: quadratic bezier through tee, layup, green ----------
C = 2 * L - (T + G) / 2
t = np.linspace(0, 1, 3000)[:, None]
curve = (1 - t) ** 2 * T + 2 * t * (1 - t) * C + t ** 2 * G
arc = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(curve, axis=0), axis=1))])
tree = cKDTree(curve)
dist, idx = tree.query(np.stack([X.ravel(), Y.ravel()], 1))
dist, sarc = dist.reshape(X.shape), arc[idx].reshape(X.shape)
total = arc[-1]
# signed side (left/right of line) for asymmetric edges
tang = np.gradient(curve, axis=0)[idx].reshape(*X.shape, 2)
side = np.sign(tang[..., 0] * (Y - curve[idx, 1].reshape(X.shape)) - tang[..., 1] * (X - curve[idx, 0].reshape(X.shape)))

# ---------- shapes ----------
green_len = np.linalg.norm(GB - GF)
ga = (GB - GF) / green_len
gc = (GF + GB) / 2 * 0.5 + G * 0.5
a_ax, b_ax = green_len / 2 + 2.0, (green_len / 2 + 2.0) * 0.78
du, dv = X - gc[0], Y - gc[1]
gu = du * ga[0] + dv * ga[1]; gv = -du * ga[1] + dv * ga[0]
theta = np.arctan2(gv, gu)
gr = np.sqrt((gu / a_ax) ** 2 + (gv / b_ax) ** 2) - (0.06 * np.sin(3 * theta + 1) + 0.04 * np.sin(5 * theta))
green = gr < 1.0
fringe = gr < 1.0 + 2.0 / a_ax

fw_start = 80.0
prog = np.clip((sarc - fw_start) / (total - fw_start), 0, 1)
half_w = 15 + 4 * np.exp(-((sarc - 230) / 60) ** 2) - 5 * np.clip((sarc - (total - 60)) / 50, 0, 1)
half_w = half_w + 2.5 * noise_big + 1.0 * side * fbm(X.shape, [20], [1], 3)
in_run = (sarc > fw_start) & (sarc < total - 3)
fairway = (dist < half_w) & in_run
fw_entry = np.clip((sarc - fw_start) / 6, 0, 1)
fairway &= dist < half_w * fw_entry
semi = (dist < half_w + 5) & (sarc > fw_start - 6) | (fringe & ~green) | (np.hypot(X - gc[0], Y - gc[1]) < a_ax + 6)

# tee box: rounded rect just behind the tee point
tu, tv = X - T[0], Y - (T[1] - 4)
teebox = (np.abs(tu) < 5) & (np.abs(tv) < 9) & ((np.abs(tu) - 3) ** 2 + (np.abs(tv) - 7) ** 2 < 4 + 100 * ((np.abs(tu) < 3) | (np.abs(tv) < 7)))
teeapron = (np.abs(tu) < 8) & (np.abs(tv) < 12)

# trees: scatter where far from play
tree_zone = dist - half_w - 26 - 9 * noise_big
cand = rng.uniform([xmin, ymin], [xmax, ymax], (2600, 2))
ci = np.clip(((ymax - cand[:, 1]) * s).astype(int), 0, Hh - 1), np.clip(((cand[:, 0] - xmin) * s).astype(int), 0, W - 1)
keep = (tree_zone[ci] > 0) & (np.hypot(*(cand - gc).T) > a_ax + 18) & (np.hypot(*(cand - T).T) > 16)
dens = np.clip(tree_zone[ci] / 25, 0, 1)
keep &= rng.random(len(cand)) < (0.06 + 0.5 * dens) * (noise_big[ci] > -0.3)
trees = cand[keep]
trees = trees[np.argsort(-trees[:, 1])]

# ---------- elevation -> hillshade ----------
grid = np.array(H["grid"]).reshape(12, 21)       # rows tee->green, cols across
ACROSS = 10.0                                      # assumed metres between columns
u = (Y - T[1]) / D * 11
v = (X - T[0]) / ACROSS + 10
Z = map_coordinates(grid, [np.clip(u, 0, 11), np.clip(v, 0, 20)], order=1)
Z = gaussian_filter(Z, 6 * s)
# green micro-contours (2 m step, int16 cm), assumed north-up
gg = H["green_grid"]; n = gg["n"]
gcm = np.frombuffer(base64.b64decode(gg["cm"]), dtype="<i2").reshape(n, n) / 100.0
Xg, Yg = X - G[0], Y - G[1]
c, sn = math.cos(-north_rot), math.sin(-north_rot)
E, N = c * Xg - sn * Yg, sn * Xg + c * Yg      # back to east/north
gi = (n - 1) / 2 - N / gg["step"]; gj = (n - 1) / 2 + E / gg["step"]
gz = map_coordinates(gcm, [np.clip(gi, 0, n - 1), np.clip(gj, 0, n - 1)], order=1)
inside_g = (np.abs(gi - (n - 1) / 2) < (n - 1) / 2) & (np.abs(gj - (n - 1) / 2) < (n - 1) / 2)
wgt = gaussian_filter(fringe.astype(float), 3 * s) * inside_g
Z = Z + gaussian_filter(gz, 0.8 * s) * wgt * 1.5

def hillshade(z, exag, az=315, alt=40):
    gy, gx = np.gradient(z * exag, 1 / s)
    slope = np.arctan(np.hypot(gx, gy)); aspect = np.arctan2(-gx, gy)
    a, al = math.radians(az), math.radians(alt)
    return np.sin(al) * np.cos(slope) + np.cos(al) * np.sin(slope) * np.cos(a - aspect)
hs = hillshade(Z, 7.0)
shade = 0.78 + 0.32 * (hs - hs.mean()) / (hs.std() * 3 + 1e-9) + 0.22

# ---------- paint ----------
def col(h): return np.array([int(h[i:i + 2], 16) for i in (1, 3, 5)], float)
img = np.zeros((*X.shape, 3))
img[:] = col("#557f36")
img += (noise_fine[..., None] * 4 + noise_big[..., None] * 5)
def paint(mask, base, soft=0.6, jitter=3):
    m = gaussian_filter(mask.astype(float), soft * s)[..., None]
    layer = col(base) + noise_fine[..., None] * jitter
    img[:] = img * (1 - m) + layer * m
paint(semi, "#5d8c3a", 1.2)
paint(teeapron & ~teebox, "#5d8c3a", 0.8)
stripes_fw = ((np.floor((sarc + 0.35 * side * dist) / 11) % 2) * 2 - 1)[..., None]
m = gaussian_filter(fairway.astype(float), 0.5 * s)[..., None]
img[:] = img * (1 - m) + (col("#76ab45") + stripes_fw * 4.5 + noise_fine[..., None] * 2) * m
paint(fringe, "#6aa944", 0.35, 2)
stripes_g = ((np.floor(gu / 2.5) % 2) * 2 - 1)[..., None]
m = gaussian_filter(green.astype(float), 0.3 * s)[..., None]
img[:] = img * (1 - m) + (col("#7cc552") + stripes_g * 3) * m
stripes_t = ((np.floor(tv / 3) % 2) * 2 - 1)[..., None]
m = gaussian_filter(teebox.astype(float), 0.3 * s)[..., None]
img[:] = img * (1 - m) + (col("#82bd52") + stripes_t * 4) * m
img *= shade[..., None]

base = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8))
def P(p): return ((p[0] - xmin) * s, (ymax - p[1]) * s)

# tree shadows then canopies
sh = Image.new("L", base.size, 0); d = ImageDraw.Draw(sh)
radii = rng.uniform(4, 8.5, len(trees))
for (x, y), r in zip(trees, radii):
    cx, cy = P((x + r * 0.55, y - r * 0.55)); rr = r * s
    d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=110)
sh = sh.filter(ImageFilter.GaussianBlur(2.2 * s))
base = Image.composite(Image.new("RGB", base.size, (22, 40, 18)), base, sh)
cv = ImageDraw.Draw(base)
for (x, y), r in zip(trees, radii):
    g0 = rng.uniform(0.85, 1.15)
    cx, cy = P((x, y)); rr = r * s
    cv.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=tuple(int(v * g0) for v in (38, 74, 32)))
    for k in range(5):
        o = rng.uniform(-0.45, 0.25, 2) * rr; q = rr * rng.uniform(0.35, 0.6)
        cv.ellipse([cx + o[0] - q, cy + o[1] - q, cx + o[0] + q, cy + o[1] + q], fill=tuple(int(v * g0) for v in (52, 98, 42)))
    q = rr * 0.3; cv.ellipse([cx - rr * 0.35 - q, cy - rr * 0.35 - q, cx - rr * 0.35 + q, cy - rr * 0.35 + q], fill=tuple(int(v * g0) for v in (78, 128, 58)))

# pin + shadow
fx, fy = P(G)
cv.line([fx, fy, fx + 9 * s, fy + 4 * s], fill=(30, 50, 25), width=int(0.6 * s))
cv.ellipse([fx - 0.7 * s, fy - 0.7 * s, fx + 0.7 * s, fy + 0.7 * s], fill=(25, 25, 25))
cv.line([fx, fy, fx, fy - 9 * s], fill=(245, 245, 245), width=int(0.45 * s))
cv.polygon([(fx, fy - 9 * s), (fx + 4.5 * s, fy - 7.6 * s), (fx, fy - 6.2 * s)], fill=(220, 40, 40))

# yardage discs to green centre (on centreline)
def at_yards(yd):
    m_ = yd * 0.9144; j = np.argmin(np.abs(np.linalg.norm(curve - G, axis=1) - m_) + (arc > total - 20) * 1e9)
    return curve[j]
try: font = ImageFont.truetype("DejaVuSans-Bold.ttf", int(3.4 * s))
except OSError: font = ImageFont.load_default()
for yd, c_ in ((100, (240, 240, 240)), (150, (240, 220, 60)), (200, (60, 130, 230))):
    if yd * 0.9144 < D - 10:
        x, y = P(at_yards(yd)); r = 1.3 * s
        cv.ellipse([x - r, y - r, x + r, y + r], fill=c_, outline=(30, 30, 30), width=max(1, int(0.2 * s)))
        cv.text((x + 2.4 * s, y), str(yd), fill=(255, 255, 255), font=font, anchor="lm", stroke_width=int(0.5 * s), stroke_fill=(20, 40, 20))

# tee markers
for dx in (-2.5, 2.5):
    x, y = P((T[0] + dx, T[1])); r = 0.7 * s
    cv.ellipse([x - r, y - r, x + r, y + r], fill=(240, 210, 40), outline=(40, 40, 40))

img_out = base.resize((W // SS, Hh // SS), Image.LANCZOS)
d = ImageDraw.Draw(img_out)
try:
    f1 = ImageFont.truetype("DejaVuSans-Bold.ttf", 26); f2 = ImageFont.truetype("DejaVuSans.ttf", 16)
except OSError: f1 = f2 = ImageFont.load_default()
d.rounded_rectangle([12, 12, 250, 82], 10, fill=(18, 32, 22))
d.text((26, 20), f"HOLE {H['hole']}", fill=(255, 255, 255), font=f1)
d.text((26, 54), f"Par {H['par']} · {H['yards_yellow']} yds (yellow)", fill=(190, 220, 190), font=f2)
# north arrow
cxn, cyn = img_out.width - 40, 46
vx, vy = math.sin(north_rot), -math.cos(north_rot)
d.ellipse([cxn - 22, cyn - 22, cxn + 22, cyn + 22], fill=(18, 32, 22))
d.polygon([(cxn + vx * 16, cyn + vy * 16), (cxn - vy * 6, cyn + vx * 6), (cxn + vy * 6, cyn - vx * 6)], fill=(230, 60, 60))
d.text((cxn - vx * 2, cyn - vy * 2), "N", fill=(255, 255, 255), font=f2, anchor="mm") if False else None
img_out.save(out)
print("saved", out, img_out.size, "length m", round(D), "trees", len(trees))
