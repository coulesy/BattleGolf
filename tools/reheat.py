"""Redraws a built hole's green heat map, without re-rendering the hole. build_course.sh runs it on every build.

Default (MODE=grid): the green as a 3D wire mesh, 2 m squares, each point lifted by the green's height
(exaggerated, level with the pin) and each wire coloured by steepness in eight bands from blue (flat) to magenta
(over 10 %), the same scale as the game's slope key and arrows. The mesh is cut to the green's outline.
MODE=steep: a flat map coloured by steepness. MODE=vector: flat steepness bands with ink outlines and a white grid. MODE=relief: the old height colours with slope shading.
The slopes come from the hole's green_grid (the same numbers the game rolls putts on); the green's outline from
the renderer's flat heat image (kept in build/heat-backup/ once a hole in game/courses has been redrawn).

    python3 tools/reheat.py game/courses/patchwork/04/            # rewrites both heat maps in place
    python3 tools/reheat.py game/courses/*/[0-9][0-9]/            # every hole
    python3 tools/reheat.py --out build/preview game/courses/patchwork/04/
    MODE=steep python3 tools/reheat.py ...
"""
import json, math, os, sys
import numpy as np
from PIL import Image
from scipy.ndimage import gaussian_filter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pin

STOPS = np.array([[30, 80, 255], [0, 200, 255], [60, 230, 90], [190, 245, 40],
                  [255, 220, 0], [255, 140, 0], [255, 40, 70]], float)
BANDS = 9
FULL = 0.05          # a slope this steep (5 %) gets the full light/shadow
LIGHT = 0.6         # how far a fully lit (or shaded) slope moves from the band colour


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def outline_source(hole_dir, name):
    """The flat heat image whose alpha is the green's outline. Redrawing replaces that alpha (the wire grid is
    mostly clear), so the first redraw of a hole in game/courses keeps a copy in build/heat-backup/ and every later
    one reads the outline from there. A fresh build (in build/<hole>/) still has the renderer's own image."""
    hd = os.path.abspath(hole_dir); games = os.path.join(ROOT, "game", "courses")
    cur = os.path.join(hd, name)
    if not hd.startswith(games + os.sep): return cur
    keep = os.path.join(ROOT, "build", "heat-backup", os.path.relpath(hd, games), name)
    if not os.path.exists(keep):
        import shutil; os.makedirs(os.path.dirname(keep), exist_ok=True); shutil.copy2(cur, keep)
    return keep


def smooth_height(d):
    """the green grid with cubic interpolation, so the shading has no 2 m facets (putts still use the plain grid)"""
    from scipy.ndimage import map_coordinates
    gg = d["green_grid"]; n, step = gg["n"], gg["step"]
    cm = np.asarray(gg["cm"], float).reshape(n, n)
    c0 = d.get("gcen", d["pin"]); c, s_ = math.cos(-d["north_rot"]), math.sin(-d["north_rot"])
    def h(x, y):
        xg, yg = np.asarray(x) - c0[0], np.asarray(y) - c0[1]
        E, N = c * xg - s_ * yg, s_ * xg + c * yg
        return map_coordinates(cm, [(n - 1) / 2 - N / step, (n - 1) / 2 + E / step], order=3, mode="nearest") / 100
    return h


# MODE=steep: colour is steepness instead of height, in the same eight bands as the game's slope key and
# arrows (SLOPE_COLS in game/index.html; keep the two in step): blue flat, through green and yellow, to red and magenta.
STEEP = [(0.01, "#3a6bff"), (0.02, "#00c8ff"), (0.03, "#3ce65a"), (0.04, "#bef528"),
         (0.05, "#ffdc00"), (0.07, "#ff8c00"), (0.10, "#ff2846"), (math.inf, "#c81eb4")]
STEEP = [(lim, tuple(int(c[i:i + 2], 16) for i in (1, 3, 5))) for lim, c in STEEP]


def reheat(hole_dir, data_name, out_dir=None, mode="steep"):
    d = json.load(open(f"{hole_dir}/{data_name}"))
    hp = f"{hole_dir}/{d['heat']['file']}"
    old = Image.open(outline_source(hole_dir, d['heat']['file'])).convert("RGBA")
    W, H = old.size
    alpha = np.asarray(old, float)[..., 3]
    hx, hy, hw, hh = (d["heat"][k] for k in ("x", "y", "w", "h"))
    # every heat pixel -> base-image px -> hole-frame metres (inverse of the game's toImg)
    px = hx + (np.arange(W) + 0.5) * hw / W; py = hy + (np.arange(H) + 0.5) * hh / H
    PX, PY = np.meshgrid(px, py)
    Ai = np.linalg.inv(np.array(d["A"])); b = np.array(d["b"])
    X = Ai[0, 0] * (PX - b[0]) + Ai[0, 1] * (PY - b[1])
    Y = Ai[1, 0] * (PX - b[0]) + Ai[1, 1] * (PY - b[1])
    h = smooth_height(d)
    Z = h(X, Y)
    e = 0.5
    gx = (h(X + e, Y) - h(X - e, Y)) / (2 * e); gy = (h(X, Y + e) - h(X, Y - e)) / (2 * e)
    slope = np.hypot(gx, gy)
    # light from the top-left of the screen, in world terms: the screen direction (-1, -1) mapped back to metres
    lw = Ai @ np.array([-1.0, -1.0]); lw /= np.linalg.norm(lw)
    facing = -(gx * lw[0] + gy * lw[1]) / (slope + 1e-9)          # +1 faces the light, -1 faces away
    shade = np.clip(slope / FULL, 0, 1) * facing
    shade = gaussian_filter(shade, 0.8)
    gm = alpha > 20
    if mode == "steep":
        sl = gaussian_filter(slope, 1.2)                         # soft band edges, no single-pixel speckle
        rgb = np.zeros(sl.shape + (3,))
        for lim, col in reversed(STEEP): rgb[sl < lim] = col
        img = Image.fromarray(np.dstack([rgb, alpha]).clip(0, 255).astype(np.uint8), "RGBA")
        dest = f"{out_dir}/{d['heat']['file']}" if out_dir else hp
        img.save(dest)
        return dest, float(np.percentile(slope[gm], 50)), float(slope[gm].max())
    lo, hi = np.percentile(Z[gm], [3, 97]) if gm.any() else (0, 1)
    tt = np.clip((Z - lo) / (hi - lo + 1e-6), 0, 1)
    tq = np.round(tt * (BANDS - 1)) / (BANDS - 1)
    pos = tq * (len(STOPS) - 1); i0 = np.clip(pos.astype(int), 0, len(STOPS) - 2); fr = (pos - i0)[..., None]
    rgb = STOPS[i0] * (1 - fr) + STOPS[i0 + 1] * fr
    k = (shade * LIGHT)[..., None]
    rgb = np.where(k > 0, rgb + (255 - rgb) * k, rgb * (1 + k))
    img = Image.fromarray(np.dstack([rgb, alpha]).clip(0, 255).astype(np.uint8), "RGBA")
    dest = f"{out_dir}/{d['heat']['file']}" if out_dir else hp
    img.save(dest)
    return dest, float(np.percentile(slope[gm], 50)) if gm.any() else 0.0, float(slope[gm].max()) if gm.any() else 0.0


CELL = 2.0           # grid spacing, metres
LIFT_M = 3.5         # the green's whole relief is shown as about this many metres of rise (it's exaggerated)
WIRE = 1.1           # wire width, heat px


def reheat_grid(hole_dir, data_name, out_dir=None):
    """MODE=grid: the green as a 3D wire mesh. Each grid point is lifted by the green's height (exaggerated, and
    level with the pin so the ball and cup still sit on it), and each wire is coloured by the steepness where it
    runs. The mesh is laid well past the green and then cut to the green's outline (with a soft edge), so it
    always covers the whole green and never spills off it. Same size and place as the flat heat map."""
    from PIL import ImageDraw
    d = json.load(open(f"{hole_dir}/{data_name}"))
    hp = f"{hole_dir}/{d['heat']['file']}"
    src = Image.open(outline_source(hole_dir, d['heat']['file'])).convert("RGBA"); W, H = src.size
    alpha = np.asarray(src, float)[..., 3]
    hx, hy, hw, hh = (d["heat"][k] for k in ("x", "y", "w", "h"))
    A = np.array(d["A"]); b = np.array(d["b"]); Ai = np.linalg.inv(A)
    kx, ky = W / hw, H / hh                                    # heat px per base-image px
    to_px = lambda x, y: ((A[0, 0] * x + A[0, 1] * y + b[0] - hx) * kx, (A[1, 0] * x + A[1, 1] * y + b[1] - hy) * ky)
    up_m = math.sqrt(abs(np.linalg.det(A))) / math.sqrt(0.72) * ky   # heat px for one upright metre (camera tilt 0.72)
    h = smooth_height(d)
    ys_, xs_ = np.nonzero(alpha > 20)                          # the green, in metres, from the flat outline
    bxp, byp = hx + (xs_ + 0.5) / kx, hy + (ys_ + 0.5) / ky
    WX = Ai[0, 0] * (bxp - b[0]) + Ai[0, 1] * (byp - b[1]); WY = Ai[1, 0] * (bxp - b[0]) + Ai[1, 1] * (byp - b[1])
    M = 10.0                                                   # lay the mesh this far past the green, then crop
    gxs = np.arange(WX.min() - M, WX.max() + M + CELL, CELL); gys = np.arange(WY.min() - M, WY.max() + M + CELL, CELL)
    GX, GY = np.meshgrid(gxs, gys)
    Z = h(GX, GY); zp = float(h(np.array([d["pin"][0]]), np.array([d["pin"][1]]))[0])
    PXg, PYg = to_px(GX, GY)
    on = alpha[np.clip(PYg.astype(int), 0, H - 1), np.clip(PXg.astype(int), 0, W - 1)] > 128
    on &= (PXg >= 0) & (PXg < W) & (PYg >= 0) & (PYg < H)
    # past the green's edge the mesh carries on level, at the height (and colour) of the nearest point on the green,
    # so the banks round the green don't fold into view when the mesh is lifted
    from scipy.ndimage import distance_transform_edt
    _, (ni, nj) = distance_transform_edt(~on, return_indices=True)
    SX, SY = GX[ni, nj], GY[ni, nj]                            # where each grid point takes its height and colour from
    Z = Z[ni, nj]
    relief = float(np.ptp(Z[on])) if on.any() else 0.1
    exag = min(max(LIFT_M / max(relief, 0.05), 3), 25)
    LIFT = (Z - zp) * exag * up_m                              # heat px, up is positive
    SS = 3
    img = Image.new("RGBA", (W * SS, H * SS), (0, 0, 0, 0)); dr = ImageDraw.Draw(img)
    e = 0.5
    def steep_col(x, y):
        sx = (h(np.array([x + e]), np.array([y]))[0] - h(np.array([x - e]), np.array([y]))[0]) / (2 * e)
        sy = (h(np.array([x]), np.array([y + e]))[0] - h(np.array([x]), np.array([y - e]))[0]) / (2 * e)
        return next(c for lim, c in STEEP if math.hypot(sx, sy) < lim)
    P = lambda v: (PXg[v] * SS, (PYg[v] - LIFT[v]) * SS)
    lines = []
    ny_, nx_ = GX.shape
    for i in range(ny_):
        for j in range(nx_):
            for v1 in ((i, j + 1), (i + 1, j)):
                if v1[0] >= ny_ or v1[1] >= nx_: continue
                v0 = (i, j); p0, p1 = P(v0), P(v1)
                if max(p0[0], p1[0]) < -SS or min(p0[0], p1[0]) > (W + 1) * SS or max(p0[1], p1[1]) < -SS or min(p0[1], p1[1]) > (H + 1) * SS:
                    continue
                cx_, cy_ = (SX[v0] + SX[v1]) / 2, (SY[v0] + SY[v1]) / 2
                if not (on[v0] or on[v1]): cx_, cy_ = SX[v0], SY[v0]
                lines.append(((PYg[v0] + PYg[v1]) / 2, [p0, p1], steep_col(cx_, cy_)))
    for _, pts, col in sorted(lines, key=lambda t: t[0]):     # far first, near wires on top
        dr.line(pts, fill=(15, 30, 20, 140), width=max(1, int((WIRE + 0.9) * SS)))
        dr.line(pts, fill=col + (255,), width=max(1, int(WIRE * SS)))
    out = np.asarray(img.resize((W, H), Image.LANCZOS), float)
    mask = gaussian_filter((alpha > 128).astype(float), 0.9)  # the green's edge, softened into a short fade
    out[..., 3] *= mask
    dest = f"{out_dir}/{d['heat']['file']}" if out_dir else hp
    Image.fromarray(out.clip(0, 255).astype(np.uint8), "RGBA").save(dest)
    return dest, 0, exag, relief


INK = (18, 40, 28)   # outline colour, the same dark green as the contour lines and the toon renderer's ink


def reheat_vector(hole_dir, data_name, out_dir=None):
    """MODE=vector: the green drawn flat, like the rest of the cartoon art. Solid, saturated steepness bands
    (the same eight as the slope key and arrows) with dark ink outlines where one band meets the next, and a
    flat white 2 m grid on top, laid out from the pin so the cup sits on a corner. Drawn 3x and shrunk, so every
    edge is crisp and anti-aliased. Same size and place as the flat heat map."""
    d = json.load(open(f"{hole_dir}/{data_name}"))
    hp = f"{hole_dir}/{d['heat']['file']}"
    src = Image.open(outline_source(hole_dir, d['heat']['file'])).convert("RGBA"); W, H = src.size
    SS = 3
    alpha = np.asarray(src.resize((W * SS, H * SS), Image.BILINEAR), float)[..., 3]
    hx, hy, hw, hh = (d["heat"][k] for k in ("x", "y", "w", "h"))
    A = np.array(d["A"]); b = np.array(d["b"]); Ai = np.linalg.inv(A)
    px = hx + (np.arange(W * SS) + 0.5) * hw / (W * SS); py = hy + (np.arange(H * SS) + 0.5) * hh / (H * SS)
    PX, PY = np.meshgrid(px, py)
    X = Ai[0, 0] * (PX - b[0]) + Ai[0, 1] * (PY - b[1])
    Y = Ai[1, 0] * (PX - b[0]) + Ai[1, 1] * (PY - b[1])
    h = smooth_height(d); e = 0.5
    gx = (h(X + e, Y) - h(X - e, Y)) / (2 * e); gy = (h(X, Y + e) - h(X, Y - e)) / (2 * e)
    sl = gaussian_filter(np.hypot(gx, gy), 2.5 * SS)              # smooth band shapes, no speckle
    band = np.searchsorted([lim for lim, _ in STEEP], sl, side="right").clip(0, len(STEEP) - 1)
    rgb = np.array([c for _, c in STEEP], float)[band]
    px_m = 1 / math.sqrt(abs(np.linalg.det(A)) * (W * SS / hw) * (H * SS / hh))   # metres per supersampled px
    # ink where the band changes, about 1.3 heat px wide
    edge = (np.diff(band, axis=0, prepend=band[:1]) != 0) | (np.diff(band, axis=1, prepend=band[:, :1]) != 0)
    from scipy.ndimage import binary_dilation
    edge = binary_dilation(edge, iterations=max(1, int(0.6 * SS)))
    # flat white grid, CELL metres, anchored on the pin
    qx, qy = (X - d["pin"][0]) / CELL, (Y - d["pin"][1]) / CELL
    dist = np.minimum(np.abs(qx - np.round(qx)), np.abs(qy - np.round(qy))) * CELL / px_m   # px to the nearest line
    gridk = np.clip(0.55 * SS + 0.5 - dist, 0, 1)[..., None]
    rgb = rgb * (1 - gridk * 0.6) + 255 * gridk * 0.6
    rgb[edge] = INK
    # ink round the green's own edge too, so it reads as a sticker laid on the grass
    inside = alpha > 128
    rim = inside & binary_dilation(~inside, iterations=SS)
    rgb[rim] = INK
    a = np.where(inside, 235, 0).astype(float)
    img = Image.fromarray(np.dstack([rgb, a]).clip(0, 255).astype(np.uint8), "RGBA").resize((W, H), Image.LANCZOS)
    dest = f"{out_dir}/{d['heat']['file']}" if out_dir else hp
    img.save(dest)
    gm = inside
    return dest, float(np.percentile(sl[gm], 50)) if gm.any() else 0.0, float(sl[gm].max()) if gm.any() else 0.0


if __name__ == "__main__":
    args = sys.argv[1:]; out = None; mode = os.environ.get("MODE", "grid")
    if args[:1] == ["--out"]: out = args[1]; args = args[2:]; os.makedirs(out, exist_ok=True)
    for hd in args:
        for dn in ("game_data.json", "game_data_portrait.json"):
            if mode == "vector":
                dest, med, mx = reheat_vector(hd.rstrip("/"), dn, out)
                print(f"{dest}: median slope {med * 100:.1f}%, steepest {mx * 100:.1f}%")
            elif mode == "grid":
                dest, _, exag, relief = reheat_grid(hd.rstrip("/"), dn, out)
                print(f"{dest}: relief {relief * 100:.0f} cm, shown {exag:.1f}x")
            else:
                dest, med, mx = reheat(hd.rstrip("/"), dn, out, mode)
                print(f"{dest}: median slope {med * 100:.1f}%, steepest {mx * 100:.1f}%")
