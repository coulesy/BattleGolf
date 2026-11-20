"""Cut a prop sheet into one transparent PNG per object, using a black-and-white mask drawn over the same sheet.

    python3 tools/split_props.py art/medieval            # reads art/<set>/source/, writes art/<set>/props/
    python3 tools/split_props.py art/nature /tmp/contact.png   # also saves a contact sheet to check by eye

art/<set>/source/sheet.json names the two pictures and every prop on the sheet:
  "mask", "colour"   the mask (white = object, grey = shadow, black = background) and the coloured sheet
  "min_area"         pixels of white a group needs to stand alone; smaller specks join the nearest prop
  "split"            lists of props that share one shadow but should come out separately
  "props"            name -> {"at": [x, y] rough centre on the sheet, "m": width on the course in metres,
                              "solid": blocks shots like a tree, "k": ground point is k * width above the
                              bottom of the picture (or "centre" for flat things), "lie": "water" (optional)}
Shadows are left out: the game draws its own. Each prop's mask is lined up with the colour sheet automatically.
"""
import json, os, sys
import numpy as np
from PIL import Image
from scipy import ndimage as ndi

SET = sys.argv[1].rstrip("/")
cfg = json.load(open(f"{SET}/source/sheet.json"))
OUT = f"{SET}/props"
os.makedirs(OUT, exist_ok=True)
m = np.array(Image.open(f"{SET}/source/{cfg['mask']}").convert("L")).astype(float)
c = np.array(Image.open(f"{SET}/source/{cfg['colour']}").convert("RGB"))

# The mask can be a few pixels off the colour sheet, and not by the same amount everywhere (it may be
# stretched slightly), so each prop is lined up on its own: its mask edge onto the sheet's dark ink outline.
dark = c.astype(int).sum(2) < 200
def align(g):
    ys, xs = np.nonzero(g); y0, y1, x0, x1 = max(ys.min() - 12, 0), ys.max() + 13, max(xs.min() - 12, 0), xs.max() + 13
    e = g[y0:y1, x0:x1]; e = e & ~ndi.binary_erosion(e, iterations=2); d = dark[y0:y1, x0:x1]
    return max(((np.roll(e, (dy, dx), (0, 1)) & d).sum(), dy, dx) for dy in range(-9, 10) for dx in range(-9, 10))[1:]

P = cfg["props"]
names = list(P); C = np.array([P[k]["at"] for k in names], float)
def nearest(x, y, allowed=None):
    d = ((C - [x, y]) ** 2).sum(1)
    if allowed: d = np.where([n in allowed for n in names], d, 1e12)
    i = int(d.argmin()); return names[i], d[i] ** 0.5
split_of = {n: g for g in cfg.get("split", []) for n in g}

obj = m > 185
alpha = np.clip((m - 150) / (235 - 150), 0, 1)       # soft edge, leaves out the grey shadow
lab, n = ndi.label(ndi.binary_dilation(m > 60, iterations=4))
groups = {}
for i in range(1, n + 1):
    sel = (lab == i) & obj
    area = sel.sum()
    if area < 15: continue
    ys, xs = np.nonzero(sel); nm, dist = nearest(xs.mean(), ys.mean())
    if area < cfg.get("min_area", 200) and dist > 150: continue          # a stray speck far from anything
    if nm in split_of:                    # one shadow holding several props: split by the object pieces
        ol, k = ndi.label(ndi.binary_dilation(sel, iterations=2) & obj)
        for j in range(1, k + 1):
            p = ol == j
            if p.sum() < 50: continue
            yy, xx = np.nonzero(p); groups.setdefault(nearest(xx.mean(), yy.mean(), split_of[nm])[0], []).append(p)
    else:
        groups.setdefault(nm, []).append(lab == i)

man = {}
for nm in names:
    if nm not in groups: print("MISSING", nm); continue
    g = np.any(groups[nm], axis=0)
    dy, dx = align(g & obj)
    a = np.roll(alpha * g, (dy, dx), (0, 1))
    ys, xs = np.nonzero(a > 0.02); y0, y1, x0, x1 = ys.min() - 2, ys.max() + 3, xs.min() - 2, xs.max() + 3
    rgba = np.dstack([c[y0:y1, x0:x1], (a[y0:y1, x0:x1] * 255).astype(np.uint8)])
    Image.fromarray(rgba, "RGBA").save(f"{OUT}/{nm}.png", optimize=True)
    w, h, p = int(x1 - x0), int(y1 - y0), P[nm]
    ay = h / 2 if p.get("k") == "centre" else h - p.get("k", 0.25) * w
    man[nm] = dict(file=f"{nm}.png", w=w, h=h, m=p["m"], solid=bool(p.get("solid")), anchor=[round(w / 2), round(ay)],
                   sheet=[int(x0), int(y0)], **({"lie": p["lie"]} if p.get("lie") else {}))
json.dump(man, open(f"{OUT}/props.json", "w"), indent=1)
print(len(man), "props in", OUT)

if len(sys.argv) > 2:                    # contact sheet on grass, to check the edges
    cols, cell = 8, 150; rows = (len(man) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cell, rows * cell), (60, 90, 60))
    for k, nm in enumerate(man):
        im = Image.open(f"{OUT}/{nm}.png"); im.thumbnail((cell - 8, cell - 8))
        sheet.paste(im, ((k % cols) * cell + 4, (k // cols) * cell + 4), im)
    sheet.save(sys.argv[2])
