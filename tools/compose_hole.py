"""Builds holes from tiles. A recipe names the core tiles (tee, fairway, green) and the feature modules
(bunkers, lakes, streams, trees, props) that sit on them, and this writes ordinary data/<course>-NN.json hole
files: made-up GPS points, a centre line, an elevation grid, a green slope grid and a drawn `map`. The usual
build (tools/build_round.sh) then renders them like any other hole.

    python3 tools/compose_hole.py data/recipes/patchwork.json           # writes data/patchwork-01.json ...
    python3 tools/compose_hole.py data/recipes/patchwork.json 3 7       # just holes 3 and 7

Recipe (see data/recipes/patchwork.json and the README for every tile, variant and module):

    {"id": "patchwork", "name": "Patchwork Park", "theme": "classic",
     "holes": [{"tiles": [{"t": "tee"}, {"t": "fairway", "bend": "left", "len": 210}, {"t": "green", "shape": "kidney"}],
                "modules": [{"m": "bunker", "at": "green.front_left"}, {"m": "stream", "at": "fairway.cross", "pos": 0.8}]}]}

Par comes from the tiles: tee + green is a par 3, tee + fairway + green a par 4, tee + 2 fairways + green a par 5.
Geometry is in metres, x east and y north, with the tee at the origin.
"""
import base64, json, math, os, sys
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
YD = 0.9144
PAR_YARDS = {3: (110, 230), 4: (290, 470), 5: (460, 600)}

# ---------------- core tiles ----------------
# Each tile is a stretch of centre line. len: metres along the line; turn: degrees (+ right, - left);
# width: fairway half-width in metres; elev: metres the ground rises (or falls) over the tile.
TEE = dict(len=55, carry=150)                   # par 4/5: a short carry over rough; par 3: the whole shot
FAIRWAY_LEN = dict(short=165, medium=200, long=240)
BENDS = {"straight": [], "left": [(-25, 0.7)], "right": [(25, 0.7)], "hard_left": [(-45, 0.7)],
         "hard_right": [(45, 0.7)], "s_left": [(-25, 0.3), (25, 0.8)], "s_right": [(25, 0.3), (-25, 0.8)]}
WIDTHS = dict(narrow=11.0, normal=15.0, wide=20.0)
SLOPES = dict(flat=(0, 0), uphill=(6, 0), downhill=(-6, 0), ridge=(0, 4), valley=(0, -4))   # (end rise, middle bump)
TEE_ELEV = dict(level=0, raised=2.5, elevated=9)
GREEN_SHAPES = dict(oval=(15, 11), long=(19, 9), round=(13, 13), wide=(10, 17), kidney=(15, 12))
GREEN_SLOPES = ("flat", "back_to_front", "front_to_back", "left_to_right", "right_to_left", "crown", "bowl", "two_tier")
GREEN_ELEV = dict(level=0, raised=2.5, sunken=-2)
# fairway tiers: a step in the ground across the fairway (metres up, + or -, and where along the tile, 0-1)
TIERS = dict(none=[], up=[(2.4, 0.55)], down=[(-2.4, 0.55)], double_up=[(1.8, 0.35), (1.8, 0.72)],
             double_down=[(-1.8, 0.35), (-1.8, 0.72)])
TIER_RAMP = 9.0                                  # metres the step takes to climb
# mounds and hollows over the hole: how many per 100 m of fairway, and how tall (m)
MOUNDS = dict(flat=(0, 0), gentle=(3, 0.7), rolling=(6, 1.3), wild=(10, 2.0))
GREEN_STYLES = ("stripes", "checker", "diamond", "rings", "crosscut", "plain")   # the green's mowing pattern (art only)
SIZES = dict(small=0.75, medium=1.0, large=1.35)
TILE_OPTS = dict(tee={"elev", "len", "turn"},
                 fairway={"len", "size", "bend", "turn", "corner", "width", "slope", "gap", "tier", "mounds"},
                 green={"len", "shape", "slope", "elev", "angle", "turn", "style"})
SLOTS = {"bunker": {"left", "right", "cross", "centre", "front", "back", "front_left", "front_right", "back_left", "back_right"},
         "lake": {"left", "right", "cross", "front", "island"},
         "stream": {"left", "right", "cross", "front"},
         "treeline": {"left", "right"}, "copse": {"left", "right", "back"}, "tree": {"left", "right"},
         "props": {"left", "right"}}


class RecipeError(ValueError):
    pass


GRID_STEP, GRID_HALF = 4.0, 40         # the elevation grid: 4 m cells, 160 m either side of the tee->green line


def smooth(x):
    x = np.clip(x, 0, 1); return x * x * (3 - 2 * x)


class Hole:
    def __init__(self, rec, n, seed):
        self.rec, self.n = rec, n
        self.rng = np.random.default_rng(seed)
        tiles = rec.get("tiles") or []
        kinds = [t.get("t") for t in tiles]
        if len(kinds) < 2 or kinds[0] != "tee" or kinds[-1] != "green" or any(k != "fairway" for k in kinds[1:-1]):
            raise RecipeError(f"hole {n}: tiles must be a tee, 0-2 fairways and a green (got {kinds})")
        if len(kinds) > 4: raise RecipeError(f"hole {n}: at most 2 fairway tiles (a par 5)")
        for t in tiles:
            bad = set(t) - {"t"} - TILE_OPTS[t["t"]]
            if bad: raise RecipeError(f"hole {n}: {t['t']} tile has unknown option(s) {sorted(bad)}")
        self.par = len(tiles) + 1
        self.tiles = tiles
        self.build_path()

    # ---- centre line ----
    def build_path(self):
        h = self.heading = math.radians(self.rec.get("heading", float(self.rng.uniform(0, 360))))
        pts, heads, spans, s = [np.zeros(2)], [h], [], 0.0
        fw_names = ["fairway"] if self.par == 4 else ["fairway1", "fairway2"]
        names = ["tee"] + (fw_names if self.par > 3 else []) + ["green"]
        for i, (t, nm) in enumerate(zip(self.tiles, names)):
            k = t["t"]
            if k == "tee":
                L = float(t.get("len", TEE["carry"] if self.par == 3 else TEE["len"])); turns = [(t.get("turn", 0), 0.5)]
            elif k == "fairway":
                L = float(t.get("len", FAIRWAY_LEN[t.get("size", "medium")]))
                bend = t.get("bend", "straight")
                if bend not in BENDS: raise RecipeError(f"hole {self.n}: bend '{bend}' isn't one of {list(BENDS)}")
                turns = [(a, t.get("corner", c) if len(BENDS[bend]) == 1 else c) for a, c in BENDS[bend]]
                if "turn" in t: turns = [(t["turn"], t.get("corner", 0.7))]
            else:
                L = float(t.get("len", 40)); turns = [(t.get("turn", 0), 0.4)]
            steps = max(int(L), 2)
            h0 = heads[-1]
            for j in range(1, steps + 1):
                f = j / steps
                hh = h0 + sum(math.radians(a) * smooth((f - (c - 0.15)) / 0.3) for a, c in turns)
                pts.append(pts[-1] + np.array([math.sin(hh), math.cos(hh)]) * (L / steps)); heads.append(hh)
            spans.append((nm, s, s + L, t)); s += L
        self.P = np.array(pts)
        self.arc = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(self.P, axis=0), axis=1))])
        self.total = self.arc[-1]
        self.spans = {nm: (a, b, t) for nm, a, b, t in spans}
        if self.par == 4: self.spans["fairway1"] = self.spans["fairway"]
        if self.par == 5: self.spans["fairway"] = self.spans["fairway1"]
        self.T, self.G = self.P[0], self.P[-1]
        self.fw0 = self.spans["tee"][1]
        ph = self.rng.uniform(0, 6.3, 2); self._wob = lambda s_: 1.4 * np.sin(s_ / 37 + ph[0]) + 0.9 * np.sin(s_ / 13 + ph[1])

    def at(self, s):
        """point, unit tangent and unit right-hand normal on the centre line at arc length s"""
        s = float(np.clip(s, 0, self.total))
        j = int(np.clip(np.searchsorted(self.arc, s), 1, len(self.arc) - 1))
        f = (s - self.arc[j - 1]) / max(self.arc[j] - self.arc[j - 1], 1e-9)
        p = self.P[j - 1] * (1 - f) + self.P[j] * f
        tg = self.P[j] - self.P[j - 1]; tg = tg / (np.linalg.norm(tg) + 1e-9)
        return p, tg, np.array([tg[1], -tg[0]])

    def tile_at(self, s):
        for nm in ("tee", "fairway1", "fairway2", "green"):
            if nm in self.spans and self.spans[nm][0] <= s <= self.spans[nm][1] + 1e-6: return nm
        return "green"

    # ---- fairway ----
    def half_width(self, s):
        """fairway half-width at arc length s (0 where there's no fairway)"""
        if s < self.fw0 - (30 if self.par == 3 else 0): return 0.0
        nm = self.tile_at(s); a, b, t = self.spans[nm]
        if self.par == 3:                                   # just an apron in front of the green
            start = self.fw0 - 30
            return 9.0 * smooth((s - start) / 12) + self._wob(s) * 0.4
        if nm == "green":
            prev = self.spans["fairway2" if self.par == 5 else "fairway"][2]
            w0 = WIDTHS[prev.get("width", "normal")]
            return w0 + (10.0 - w0) * smooth((s - a) / max(b - a - 8, 1)) + self._wob(s) * 0.5
        w = WIDTHS[t.get("width", "normal")]
        if nm == "fairway1" and s < a + 12: w *= 0.4 + 0.6 * smooth((s - a) / 12)          # rounded start
        gap = t.get("gap")
        if gap:
            g0, g1 = a + gap[0] * (b - a), a + gap[1] * (b - a)
            if g0 <= s <= g1: return 0.0
        return w + self._wob(s)

    def fairway_polys(self):
        polys, cur = [], []
        for s in list(np.arange(self.fw0 - (30 if self.par == 3 else 0), self.total, 4.0)) + [self.total]:
            hw = self.half_width(s)
            if hw > 1:
                p, _, r = self.at(s); cur.append((p + r * hw, p - r * hw))
            elif cur:
                polys.append(cur); cur = []
        if cur: polys.append(cur)
        return [[a for a, _ in c] + [b for _, b in c][::-1] for c in polys if len(c) > 2]

    # ---- green ----
    def green_frame(self):
        p, tg, r = self.at(self.total)
        t = self.spans["green"][2]
        a = math.radians(t.get("angle", 0))
        u = np.array([tg[0] * math.cos(a) + r[0] * math.sin(a), tg[1] * math.cos(a) + r[1] * math.sin(a)])
        return u, np.array([u[1], -u[0]])               # along (away from the player), across (to the right)

    def green_radius(self, phi):
        """distance from the green centre to its edge, in direction phi (0 = back, +90 = right)"""
        t = self.spans["green"][2]; shape = t.get("shape", "oval")
        if shape not in GREEN_SHAPES: raise RecipeError(f"hole {self.n}: green shape '{shape}' isn't one of {list(GREEN_SHAPES)}")
        A, B = GREEN_SHAPES[shape]
        r = 1 / math.sqrt((math.cos(phi) / A) ** 2 + (math.sin(phi) / B) ** 2)
        if shape == "kidney":                            # a bite out of the front-right
            d = (phi - math.radians(130) + math.pi) % (2 * math.pi) - math.pi
            r *= 1 - 0.28 * math.exp(-(d / 0.55) ** 2)
        return r

    def green_point(self, phi, extra=0.0):
        u, v = self.green_frame()
        d = self.green_radius(phi) + extra
        return self.G + u * d * math.cos(phi) + v * d * math.sin(phi)

    def green_poly(self):
        return [self.green_point(p) for p in np.linspace(0, 2 * math.pi, 64, endpoint=False)]

    def green_grid(self):
        """33 x 33 cm grid, 2 m cells, north-up, centred on the green (the game's green_grid)"""
        t = self.spans["green"][2]; kind = t.get("slope", "back_to_front")
        if kind not in GREEN_SLOPES: raise RecipeError(f"hole {self.n}: green slope '{kind}' isn't one of {list(GREEN_SLOPES)}")
        u, v = self.green_frame(); n, step = 33, 2.0
        jj, ii = np.meshgrid(np.arange(n), np.arange(n))
        E, N = (jj - (n - 1) / 2) * step, ((n - 1) / 2 - ii) * step
        gu, gv = E * u[0] + N * u[1], E * v[0] + N * v[1]
        rr = np.hypot(gu, gv)
        tilt = self.rng.uniform(0, 2 * math.pi)
        z = 0.6 * (np.cos(tilt) * gu + np.sin(tilt) * gv)                # a gentle 0.6 % lean on every green
        z += {"flat": 0, "back_to_front": 2.2 * gu, "front_to_back": -1.6 * gu, "left_to_right": -2.2 * gv,
              "right_to_left": 2.2 * gv, "crown": -30 * (rr / 14) ** 2, "bowl": 26 * (rr / 14) ** 2,
              "two_tier": 32 * np.tanh(gu / 2.6) + 1.0 * gu}[kind]
        from scipy.ndimage import gaussian_filter
        z += gaussian_filter(self.rng.standard_normal((n, n)), 2.5) * 18          # small rolls, a few cm
        z -= z[(n - 1) // 2, (n - 1) // 2]
        return dict(n=n, step=int(step), cm=base64.b64encode(np.round(z).astype("<i2").tobytes()).decode())

    # ---- ground ----
    def profile(self, s):
        """ground height on the centre line, metres"""
        z = TEE_ELEV.get(self.spans["tee"][2].get("elev", "level"), 0) * (1 - smooth(s / 25 if self.spans["tee"][2].get("elev") == "raised" else s / max(self.spans["tee"][1], 1)))
        for nm in ("fairway1", "fairway2"):
            if nm not in self.spans: continue
            a, b, t = self.spans[nm]; sl = t.get("slope", "flat")
            if sl not in SLOPES: raise RecipeError(f"hole {self.n}: fairway slope '{sl}' isn't one of {list(SLOPES)}")
            rise, bump = SLOPES[sl]; f = (s - a) / (b - a)
            z += rise * smooth(f) + bump * math.exp(-((f - 0.5) / 0.22) ** 2) * (0 <= f <= 1.3)
            tr = t.get("tier", "none")
            if tr not in TIERS: raise RecipeError(f"hole {self.n}: fairway tier '{tr}' isn't one of {list(TIERS)}")
            for h_, at_ in TIERS[tr]:
                z += h_ * smooth((s - (a + at_ * (b - a))) / TIER_RAMP + 0.5)
        ge = self.spans["green"][2].get("elev", "level")
        if ge not in GREEN_ELEV: raise RecipeError(f"hole {self.n}: green elev '{ge}' isn't one of {list(GREEN_ELEV)}")
        z += GREEN_ELEV[ge] * math.exp(-((s - self.total) / 18) ** 2)
        return z

    def ground(self, pts, base=30.0):
        from scipy.spatial import cKDTree
        d, i = cKDTree(self.P).query(pts)
        prof = np.array([self.profile(a) for a in self.arc[::4]])
        z = np.interp(self.arc[i], self.arc[::4], prof)
        z += 0.035 * np.clip(d - 25, 0, None)            # land rises gently away from the hole
        ph = self.rng.uniform(0, 6.3, 4)
        z += 1.2 * np.sin(pts[:, 0] / 41 + ph[0]) * np.cos(pts[:, 1] / 53 + ph[1]) + 0.7 * np.sin(pts[:, 0] / 23 + pts[:, 1] / 29 + ph[2])
        for mx, my, r_, h_ in self.mounds():
            z += h_ * np.exp(-((pts[:, 0] - mx) ** 2 + (pts[:, 1] - my) ** 2) / (2 * r_ * r_))
        return base + z

    def mounds(self):
        """mounds and hollows along the hole, from each fairway's `mounds` (par 3s: rolling over the carry).
        Their own random numbers, so adding them doesn't move anything else on the hole."""
        if hasattr(self, "_mounds"): return self._mounds
        rng = np.random.default_rng(self.n * 977 + 13); out = []
        spans = [(a, b, t.get("mounds", "rolling")) for nm, (a, b, t) in self.spans.items() if nm.startswith("fairway")]
        if not spans: spans = [(25, self.total - 22, "rolling")]
        for a, b, lv in spans:
            if lv not in MOUNDS: raise RecipeError(f"hole {self.n}: fairway mounds '{lv}' isn't one of {list(MOUNDS)}")
            per, hgt = MOUNDS[lv]
            for _ in range(int(round(per * (b - a) / 100))):
                s_ = rng.uniform(a, b); p_, _, side = self.at(s_)
                c_ = p_ + side * rng.uniform(-26, 26)
                if np.linalg.norm(c_ - self.G) < 20 or np.linalg.norm(c_ - self.T) < 15: continue
                out.append((float(c_[0]), float(c_[1]), rng.uniform(5, 12), hgt * rng.uniform(0.5, 1.0) * (1 if rng.random() < 0.7 else -0.8)))
        self._mounds = out
        return out

    def elevation_grid(self):
        """the renderer's grid: rows from the tee to 20 m past the green, columns 18 m either side"""
        D = float(np.linalg.norm(self.G - self.T)); gtotal = D + 20
        half = GRID_HALF; cols = 2 * half + 1
        rows = max(int(gtotal / GRID_STEP) + 1, 3)
        a = (self.G - self.T) / D; r = np.array([a[1], -a[0]])
        pts = np.array([self.T + a * (gtotal * i / (rows - 1)) + r * (GRID_STEP * (j - half)) for i in range(rows) for j in range(cols)])
        return [round(float(z), 2) for z in self.ground(pts)]

    # ---- feature modules ----
    def blob(self, c, ra, rb, rot, wob=0.14):
        ph = self.rng.uniform(0, 6.3, 2); th = np.linspace(0, 2 * np.pi, 40, endpoint=False)
        rr = 1 + wob * np.sin(2 * th + ph[0]) + wob * 0.6 * np.sin(3 * th + ph[1])
        x, y = ra * rr * np.cos(th), rb * rr * np.sin(th)
        cr, sr = math.cos(rot), math.sin(rot)
        return np.stack([c[0] + cr * x - sr * y, c[1] + sr * x + cr * y], 1)

    def ribbon(self, S, w):
        S = np.asarray(S, float); tg = np.gradient(S, axis=0); tg /= np.linalg.norm(tg, axis=1, keepdims=True) + 1e-9
        nr = np.stack([tg[:, 1], -tg[:, 0]], 1) * w / 2
        return np.concatenate([S + nr, (S - nr)[::-1]])

    def wiggle_line(self, c, along, across, half_len, amp=7):
        ts = np.linspace(-half_len, half_len, 90); ph = self.rng.uniform(0, 6.3, 2)
        wig = amp * np.sin(ts / 23 + ph[0]) + amp * 0.55 * np.sin(ts / 9 + ph[1])
        return c + np.outer(ts, along) + np.outer(wig, across)

    def modules(self):
        out = dict(fairway=self.fairway_polys(), green=[self.green_poly()], bunker=[], water=[], wood=[], trees=[], props=[])
        for k, m in enumerate(self.rec.get("modules", [])):
            self.module(m, out, k)
        return out

    def module(self, m, out, k):
        kind, at = m.get("m"), m.get("at", "")
        if kind not in SLOTS: raise RecipeError(f"hole {self.n}: module '{kind}' isn't one of {list(SLOTS)}")
        tile, _, slot = at.partition(".")
        if tile not in self.spans: raise RecipeError(f"hole {self.n}: {kind} at '{at}': this par {self.par} has tiles {sorted(set(self.spans))}")
        if slot not in SLOTS[kind]: raise RecipeError(f"hole {self.n}: {kind} can go at {sorted(SLOTS[kind])}, not '{slot}'")
        a, b, _ = self.spans[tile]
        size = SIZES.get(m.get("size", "medium"), 1.0)
        side = 1 if "right" in slot else -1
        default_pos = {"tee": 0.6, "green": 0.3}.get(tile, 0.6)
        s = a + float(m.get("pos", default_pos)) * (b - a)
        p, tg, r = self.at(s)
        hw = max(self.half_width(s), 9.0 if tile != "tee" else 6.0)
        count = int(m.get("count", 1))

        if kind == "bunker":
            if tile == "green" and slot != "cross":
                phi = {"back": 0, "back_right": 45, "right": 90, "front_right": 140, "front": 180,
                       "front_left": -140, "left": -90, "back_left": -45, "centre": 180}[slot]
                for j in range(count):
                    ph = math.radians(phi + (j - (count - 1) / 2) * 34)
                    rb = 3.6 * size; edge = self.green_point(ph, 3.0 + rb * 1.2)
                    d = edge - self.G
                    out["bunker"].append(self.blob(edge, 6 * size, rb, math.atan2(d[1], d[0]) + math.pi / 2))
                return
            for j in range(count):
                sj = s + j * 24
                p, tg, r = self.at(sj); hw = max(self.half_width(sj), 9.0)
                if slot == "cross":
                    out["bunker"].append(self.blob(p, hw * 1.05, 3.6 * size, math.atan2(r[1], r[0]), 0.1))
                elif slot == "centre":
                    out["bunker"].append(self.blob(p, 3.6 * size, 3.2 * size, 0, 0.08))
                else:
                    rb = 4.2 * size
                    out["bunker"].append(self.blob(p + r * side * (hw + rb * 0.4), 9 * size, rb, math.atan2(tg[1], tg[0])))
        elif kind == "lake":
            if slot == "island":
                if tile != "green": raise RecipeError(f"hole {self.n}: an island needs the green tile")
                inner, wide = 2.5, 16 * size
                for lo in (-math.pi / 2 - 0.05, math.pi / 2 - 0.05):     # two half rings, overlapping a touch
                    ph = np.linspace(lo, lo + math.pi + 0.1, 40)
                    ring = [self.green_point(q, inner) for q in ph] + [self.green_point(q, inner + wide) for q in ph[::-1]]
                    out["water"].append(np.array(ring))
                return
            if slot == "front":
                if tile != "green": raise RecipeError(f"hole {self.n}: lake at front needs the green tile")
                d = self.green_radius(math.pi) + 3 + 11 * size
                p, tg, r = self.at(self.total - d)
                out["water"].append(self.blob(p + r * float(m.get("offset", 0)), 34 * size, 11 * size, math.atan2(r[1], r[0]), 0.12))
            elif slot == "cross":
                out["water"].append(self.blob(p, 45 * size, 15 * size, math.atan2(r[1], r[0]), 0.12))
            else:
                bite = m.get("bite", False)
                rb = 15 * size
                c = p + r * side * (hw + (rb * 0.55 if bite else rb + 6))
                out["water"].append(self.blob(c, 36 * size, rb, math.atan2(tg[1], tg[0]), 0.12))
        elif kind == "stream":
            w = 6 * size
            if slot in ("cross", "front"):
                if slot == "front":
                    p, tg, r = self.at(self.total - self.green_radius(math.pi) - 8)
                ang = math.radians(m.get("angle", 0))
                al = r * math.cos(ang) + tg * math.sin(ang)
                out["water"].append(self.ribbon(self.wiggle_line(p, al, np.array([-al[1], al[0]]), 170), w))
            else:
                pts = []
                if tile == "green": a, b = a - 60, b + 30        # a stream beside the green runs on past it
                for sj in np.arange(a, b + 1, 4.0):
                    q, _, rq = self.at(sj); pts.append(q + rq * side * (max(self.half_width(sj), 9) + 16))
                pts = np.array(pts); ph = self.rng.uniform(0, 6.3)
                tg_ = np.gradient(pts, axis=0); tg_ /= np.linalg.norm(tg_, axis=1, keepdims=True) + 1e-9
                wig = 4 * np.sin(np.arange(len(pts)) / 4 + ph)
                pts = pts + np.stack([tg_[:, 1], -tg_[:, 0]], 1) * wig[:, None]
                out["water"].append(self.ribbon(pts, w))
        elif kind == "treeline":
            f0, f1 = m.get("from", 0.0), m.get("to", 1.0)
            inner = 11 if m.get("tight") else 15; depth = 32 * size
            edge_in, edge_out = [], []
            for sj in np.arange(a + f0 * (b - a), a + f1 * (b - a) + 1, 6.0):
                q, _, rq = self.at(sj); hwj = max(self.half_width(sj), 9.0 if sj > self.fw0 else 5.0)
                n_ = self.rng.uniform(-2, 2)
                edge_in.append(q + rq * side * (hwj + inner + n_)); edge_out.append(q + rq * side * (hwj + inner + depth + n_))
            if len(edge_in) > 1: out["wood"].append(np.array(edge_in + edge_out[::-1]))
        elif kind == "copse":
            if slot == "back":
                c = self.green_point(0, 14 + 12 * size)
            else:
                c = p + r * side * (hw + 18 + 10 * size)
            out["wood"].append(self.blob(c, 14 * size, 11 * size, self.rng.uniform(0, 3.1), 0.18))
        elif kind == "tree":
            for j in range(count):
                sj = s + j * 9; q, _, rq = self.at(sj)
                out["trees"].append(q + rq * side * (max(self.half_width(sj), 6) + float(m.get("offset", 4))))
        elif kind == "props":
            what = m.get("kind", "rock")
            if what not in ("rock", "bush"): raise RecipeError(f"hole {self.n}: props kind is rock or bush")
            for j in range(count if "count" in m else 6):
                sj = self.rng.uniform(a, b); q, _, rq = self.at(sj)
                out["props"].append(dict(kind=what, pt=q + rq * side * (max(self.half_width(sj), 9) + self.rng.uniform(12, 30))))

    # ---- checks ----
    def check(self, feats):
        warn = []
        lo, hi = PAR_YARDS[self.par]; yd = self.total / YD
        if not lo <= yd <= hi: warn.append(f"{yd:.0f} yds is outside {lo}-{hi} for a par {self.par}")
        tee_box = [self.T + np.array([dx, dy]) for dx in (-8, 0, 8) for dy in (-8, 0, 8)]
        for k in ("bunker", "water"):
            for P in feats[k]:
                if inside(P, tee_box).any(): warn.append(f"a {k} covers the tee")
                if inside(P, [self.G])[0]: warn.append(f"a {k} covers the middle of the green")
        return warn


def inside(P, pts):
    """even-odd point-in-polygon test"""
    P = np.asarray(P, float); pts = np.atleast_2d(np.asarray(pts, float)); res = np.zeros(len(pts), bool)
    x, y = pts[:, 0], pts[:, 1]
    for (x1, y1), (x2, y2) in zip(P, np.roll(P, -1, axis=0)):
        c = ((y1 > y) != (y2 > y)) & (x < (x2 - x1) * (y - y1) / (y2 - y1 + 1e-12) + x1)
        res ^= c
    return res


def to_ll(P, lat0, lng0):
    kx, ky = math.cos(math.radians(lat0)) * 111320.0, 110540.0
    P = np.atleast_2d(np.asarray(P, float))
    return [[round(lat0 + y / ky, 8), round(lng0 + x / kx, 8)] for x, y in P]


def hole_seed(course, i, rec):
    return (sum(map(ord, course["id"])) * 131 + i * 7919 + rec.get("seed", 0)) % 2 ** 32


def placed_props(h, rec):
    """Props placed in the editor ("props" in the hole recipe): [x, y] metres from the tee, x to the right of the
    tee's heading and y along it, so they turn with the hole if its heading changes."""
    fwd = np.array([math.sin(h.heading), math.cos(h.heading)]); right = np.array([fwd[1], -fwd[0]])
    out = []
    for p in rec.get("props", []):
        q = dict(kind=p["kind"], pt=right * float(p["at"][0]) + fwd * float(p["at"][1]))
        if p.get("scale", 1) != 1: q["scale"] = float(p["scale"])
        if p.get("flip"): q["flip"] = True
        out.append(q)
    return out


def preview(course, i, rec):
    """The hole's shapes for the editor's plan view, in metres from the tee with the tee's heading pointing up
    (x right, y forward). No elevation or green grid, so it's quick."""
    h = Hole(rec, i, hole_seed(course, i, rec))
    feats = h.modules(); warn = h.check(feats)
    c, s_ = math.cos(h.heading), math.sin(h.heading)
    loc = lambda P: [[round(float(x * c - y * s_), 2), round(float(x * s_ + y * c), 2)] for x, y in np.atleast_2d(np.asarray(P, float))]
    spans = {nm: [round(float(a), 1), round(float(b), 1)] for nm, (a, b, _) in h.spans.items()}
    marks = {nm: loc(h.at(a)[0])[0] for nm, (a, b) in spans.items() if nm in ("tee", "fairway1", "fairway2", "green")}
    return dict(par=h.par, yards=int(round(h.total / YD)), metres=round(float(h.total), 1), warnings=warn,
                path=loc(h.P[::3].tolist() + [h.G]), tee=loc(h.T)[0], pin=loc(h.G)[0], tile_starts=marks,
                fairway=[loc(P) for P in feats["fairway"]], green=[loc(P) for P in feats["green"]],
                bunker=[loc(P) for P in feats["bunker"]], water=[loc(P) for P in feats["water"]],
                wood=[loc(P) for P in feats["wood"]], trees=[loc(p)[0] for p in feats["trees"]],
                props=[dict(kind=p["kind"], at=loc(p["pt"])[0]) for p in feats["props"]])


def compose(course, i, rec, origin):
    h = Hole(rec, i, hole_seed(course, i, rec))
    feats = h.modules()
    feats["props"] += placed_props(h, rec)
    warn = h.check(feats)
    lat0, lng0 = origin
    ll = lambda P: to_ll(P, lat0, lng0)
    yd = int(round(h.total / YD))
    mid = h.at(h.total / 2)[0]
    u, _ = h.green_frame()
    z_t, z_g = h.ground(np.array([h.T, h.G]))
    data = dict(course=course["name"], hole=i, par=h.par, si=rec.get("si"),
                yards_yellow=yd, yards_white=int(round(yd * 1.06)), yards_red=int(round(yd * 0.88)),
                tee=ll(h.T)[0], layup=ll(mid)[0], green=ll(h.G)[0],
                green_front=ll(h.G - u * h.green_radius(math.pi))[0], green_back=ll(h.G + u * h.green_radius(0))[0],
                tee_elev=round(float(z_t), 2), green_elev=round(float(z_g), 2),
                theme=rec.get("theme", course.get("theme", "classic")),
                green_style=h.spans["green"][2].get("style", "stripes"),
                grid=h.elevation_grid(), grid_step=GRID_STEP, grid_half=GRID_HALF, green_grid=h.green_grid(),
                path=ll(h.P[::5].tolist() + [h.G]),
                map=dict(fairway=[ll(P) for P in feats["fairway"]], green=[ll(P) for P in feats["green"]],
                         bunker=[ll(P) for P in feats["bunker"]], water=[ll(P) for P in feats["water"]],
                         wood=[ll(P) for P in feats["wood"]], trees=[ll(p)[0] for p in feats["trees"]],
                         props=[dict(p, pt=ll(p["pt"])[0]) for p in feats["props"]],
                         auto_trees=bool(rec.get("auto_trees", course.get("auto_trees", False)))),
                tiles=dict(tiles=rec["tiles"], modules=rec.get("modules", [])))
    return data, warn


def stroke_indexes(holes):
    """1 = hardest: longest for its par, odd numbers on the front 9 and even on the back (18 holes)"""
    mean = {3: 165, 4: 380, 5: 520}
    order = sorted(range(len(holes)), key=lambda k: -holes[k]["yards_yellow"] / mean[holes[k]["par"]])
    if len(holes) != 18: return {k: r + 1 for r, k in enumerate(order)}
    front = [k for k in order if k < 9]; back = [k for k in order if k >= 9]
    return {**{k: 2 * r + 1 for r, k in enumerate(front)}, **{k: 2 * r + 2 for r, k in enumerate(back)}}


def main(argv):
    if not argv: print(__doc__); return 1
    course = json.load(open(argv[0]))
    only = {int(x) for x in argv[1:]}
    origin = course.get("origin", [51.0, -0.2])
    built, ok = [], True
    for i, rec in enumerate(course["holes"], 1):
        rec = {**rec, "theme": rec.get("theme", course.get("theme", "classic"))}
        try:
            data, warn = compose(course, i, rec, origin)
        except RecipeError as e:
            print("ERROR", e); ok = False; continue
        built.append((i, data))
        print(f"hole {i:2}: par {data['par']}, {data['yards_yellow']} yds, "
              f"{len(data['map']['bunker'])} bunkers, {len(data['map']['water'])} water, {len(data['map']['wood'])} woods"
              + "".join(f"\n   warning: {w}" for w in warn))
    if not ok: return 1
    si = stroke_indexes([d for _, d in built])
    for k, (i, data) in enumerate(built):
        if data["si"] is None: data["si"] = si[k]
        if only and i not in only: continue
        path = f"{ROOT}/data/{course['id']}-{i:02d}.json"
        json.dump(data, open(path, "w"))
    print(f"wrote {len(only) or len(built)} hole file(s) to data/{course['id']}-NN.json")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
