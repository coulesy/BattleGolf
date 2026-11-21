"""Local course editor for tile-built courses: pick a course recipe (data/recipes/<id>.json), edit each hole's
tiles, feature modules and placed props with a live plan view, then compose and build it into the game.

    python3 tools/course_editor.py            # then open http://localhost:8790
    PORT=8800 python3 tools/course_editor.py

Only listens on 127.0.0.1. Saving writes the recipe; building composes the hole into data/<id>-NN.json
(tools/compose_hole.py) and renders it into game/courses/<id>/NN/ (tools/build_course.sh).
"""
import glob, json, os, re, subprocess, sys, threading, time
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, f"{ROOT}/tools")
import compose_hole as C

DATA, GAME, RECIPES = f"{ROOT}/data", f"{ROOT}/game", f"{ROOT}/data/recipes"
PAGE = f"{ROOT}/tools/editor/index.html"
COURSE_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
PROP_KIND = re.compile(r"^[a-z0-9_]{1,40}$")
THEMES = ("classic", "space", "neon", "medieval")

jobs = {}          # hole id (<course>-NN) -> {"state": queued|running|done|failed, "started": t, "finished": t}
build_lock = threading.Lock()        # one build at a time: each one is CPU-heavy
recipe_lock = threading.Lock()


def recipe_path(cid):
    if not COURSE_ID.match(cid): raise FileNotFoundError(cid)
    return f"{RECIPES}/{cid}.json"


def load_recipe(cid):
    p = recipe_path(cid)
    if not os.path.exists(p): raise FileNotFoundError(cid)
    return json.load(open(p))


def hole_status(cid, n):
    hid = f"{cid}-{n:02d}"; built = f"{GAME}/courses/{cid}/{n:02d}/game_data.json"
    return dict(id=hid, built=os.path.exists(built), built_at=os.path.getmtime(built) if os.path.exists(built) else None,
                preview=f"/game/courses/{cid}/{n:02d}/course.jpg", job=jobs.get(hid))


def list_courses():
    out = []
    for f in sorted(glob.glob(f"{RECIPES}/*.json")):
        r = json.load(open(f)); cid = r.get("id") or os.path.basename(f)[:-5]
        holes = []
        for n, rec in enumerate(r.get("holes", []), 1):
            try: pv = C.preview(r, n, {**rec, "theme": r.get("theme", "classic")}); par, yds = pv["par"], pv["yards"]
            except C.RecipeError: par, yds = None, None
            holes.append(dict(n=n, par=par, yards=yds, **hole_status(cid, n)))
        out.append(dict(id=cid, name=r.get("name", cid), theme=r.get("theme", "classic"), holes=holes))
    return out


def check_recipe(cid, r):
    """Validates a whole course recipe by composing every hole's shape; raises ValueError with the problem."""
    if not isinstance(r, dict): raise ValueError("recipe must be an object")
    name = str(r.get("name") or cid).strip()[:60]
    theme = r.get("theme", "classic")
    if theme not in THEMES: raise ValueError(f"theme must be one of {THEMES}")
    holes = r.get("holes")
    if not isinstance(holes, list) or not 1 <= len(holes) <= 18: raise ValueError("a course has 1-18 holes")
    out = {k: v for k, v in r.items() if k not in ("id", "name", "theme", "holes")}
    out.update(id=cid, name=name, theme=theme, holes=[])
    for n, rec in enumerate(holes, 1):
        if not isinstance(rec, dict): raise ValueError(f"hole {n} must be an object")
        rec = dict(rec)
        props = []
        for p in rec.get("props", []):
            if not (isinstance(p, dict) and isinstance(p.get("kind"), str) and PROP_KIND.match(p["kind"])): raise ValueError(f"hole {n}: bad prop")
            at = p.get("at")
            if not (isinstance(at, list) and len(at) == 2 and all(isinstance(v, (int, float)) and abs(v) < 2000 for v in at)):
                raise ValueError(f"hole {n}: prop position must be [x, y] metres")
            q = dict(kind=p["kind"], at=[round(float(at[0]), 2), round(float(at[1]), 2)])
            if p.get("scale", 1) != 1: q["scale"] = round(min(max(float(p["scale"]), 0.25), 4.0), 3)
            if p.get("flip"): q["flip"] = True
            if p.get("g"): q["g"] = int(p["g"])           # props placed or joined as a group move together
            props.append(q)
        if props: rec["props"] = props
        else: rec.pop("props", None)
        for k in ("si", "seed"):
            if rec.get(k) is None: rec.pop(k, None)
            else: rec[k] = int(rec[k])
        if "si" in rec and not 1 <= rec["si"] <= 18: raise ValueError(f"hole {n}: stroke index must be 1-18")
        try: C.preview(out, n, {**rec, "theme": theme})
        except (C.RecipeError, KeyError, TypeError) as e: raise ValueError(str(e))
        out["holes"].append(rec)
    return out


def save_recipe(cid, body):
    r = check_recipe(cid, body)
    with recipe_lock:
        p = recipe_path(cid); tmp = p + ".tmp"
        os.makedirs(RECIPES, exist_ok=True)
        with open(tmp, "w") as f: f.write(dump_recipe(r))
        os.replace(tmp, p)
        for f in glob.glob(f"{DATA}/{cid}-[0-9][0-9].json"):      # holes that were removed
            if int(f[-7:-5]) > len(r["holes"]): os.remove(f)
    return r


def dump_recipe(r):
    """One hole per line block, like the hand-written recipes, so diffs stay readable."""
    head = {k: v for k, v in r.items() if k != "holes"}
    s = json.dumps(head, indent=1)[:-2] + ',\n "holes": [\n'
    s += ",\n\n".join("  " + json.dumps(h) for h in r["holes"])
    return s + "\n ]\n}\n"


def new_course(body):
    cid = str(body.get("id", "")).strip().lower()
    if not COURSE_ID.match(cid): raise ValueError("course id: lower-case letters, numbers and dashes")
    if os.path.exists(recipe_path(cid)) or os.path.exists(f"{DATA}/{cid}-01.json"): raise ValueError(f"'{cid}' is already used")
    r = dict(name=body.get("name") or cid, theme=body.get("theme", "classic"),
             holes=[{"tiles": [{"t": "tee"}, {"t": "fairway"}, {"t": "green"}], "modules": []}])
    return save_recipe(cid, r)


def run_build(cid, n):
    hid = f"{cid}-{n:02d}"; log = f"{ROOT}/build/{hid}.log"
    os.makedirs(f"{ROOT}/build", exist_ok=True)
    with build_lock:
        jobs[hid] = dict(state="running", started=time.time())
        with open(log, "w") as lf:
            ok = subprocess.run([sys.executable, f"{ROOT}/tools/compose_hole.py", recipe_path(cid), str(n)],
                                stdout=lf, stderr=subprocess.STDOUT, cwd=ROOT).returncode == 0
            if ok:
                env = dict(os.environ, HOLE=hid, OUT=f"{GAME}/courses/{cid}/{n:02d}")
                ok = subprocess.run(["bash", f"{ROOT}/tools/build_course.sh"], env=env, stdout=lf, stderr=subprocess.STDOUT,
                                    cwd=ROOT).returncode == 0
            if ok:
                ok = subprocess.run([sys.executable, f"{ROOT}/tools/course_index.py", cid, load_recipe(cid).get("name", cid)],
                                    stdout=lf, stderr=subprocess.STDOUT, cwd=ROOT).returncode == 0
        jobs[hid].update(state="done" if ok else "failed", finished=time.time())


def start_build(cid, n):
    hid = f"{cid}-{n:02d}"
    if jobs.get(hid, {}).get("state") in ("queued", "running"): return
    jobs[hid] = dict(state="queued", started=time.time())
    threading.Thread(target=run_build, args=(cid, n), daemon=True).start()


def log_tail(hid, lines=25):
    try:
        with open(f"{ROOT}/build/{hid}.log") as f: return "".join(f.readlines()[-lines:])
    except OSError:
        return ""


def prop_sets():
    """Every placeable picture, by set: art/<set>/props/props.json."""
    out = {}
    for f in sorted(glob.glob(f"{ROOT}/art/*/props/props.json")):
        name = os.path.basename(os.path.dirname(os.path.dirname(f)))
        out[name] = {k: dict(v, url=f"/art/{name}/props/{v['file']}") for k, v in json.load(open(f)).items()}
    return out


GROUPS = f"{ROOT}/art/groups.json"
def load_groups():
    """Saved prop groups (art/groups.json): [{name, set, props: [{kind, at: [x, y] metres from the middle, scale?, flip?}]}]."""
    try: return json.load(open(GROUPS))["groups"]
    except (OSError, ValueError, KeyError): return []


def save_groups(body):
    if not isinstance(body, list) or len(body) > 200: raise ValueError("groups must be a list")
    out = []
    for g in body:
        if not isinstance(g, dict): raise ValueError("bad group")
        name = str(g.get("name", "")).strip()[:40]; st = str(g.get("set", ""))
        if not name or not PROP_KIND.match(st): raise ValueError("a group needs a name and a prop set")
        ps = []
        for p in g.get("props", [])[:60]:
            if not (isinstance(p, dict) and PROP_KIND.match(str(p.get("kind", "")))): raise ValueError(f"group {name}: bad prop")
            at = p.get("at")
            if not (isinstance(at, list) and len(at) == 2 and all(isinstance(v, (int, float)) and abs(v) < 500 for v in at)):
                raise ValueError(f"group {name}: prop position must be [x, y] metres")
            q = dict(kind=p["kind"], at=[round(float(at[0]), 2), round(float(at[1]), 2)])
            if p.get("scale", 1) != 1: q["scale"] = round(min(max(float(p["scale"]), 0.25), 4.0), 3)
            if p.get("flip"): q["flip"] = True
            ps.append(q)
        if not ps: raise ValueError(f"group {name} has no props")
        out.append(dict(name=name, set=st, props=ps))
    with recipe_lock:
        tmp = GROUPS + ".tmp"
        with open(tmp, "w") as f:
            f.write('{\n "groups": [\n' + ",\n".join("  " + json.dumps(g) for g in out) + "\n ]\n}\n")
        os.replace(tmp, GROUPS)
    return out


def options():
    """What the page offers in its tile and module forms (taken from the composer, so they can't drift)."""
    return dict(themes=THEMES, bends=list(C.BENDS), widths=list(C.WIDTHS), slopes=list(C.SLOPES), sizes=list(C.FAIRWAY_LEN),
                tee_elev=list(C.TEE_ELEV), green_shapes=list(C.GREEN_SHAPES), green_slopes=list(C.GREEN_SLOPES),
                green_elev=list(C.GREEN_ELEV), green_styles=list(C.GREEN_STYLES), tiers=list(C.TIERS), mounds=list(C.MOUNDS), module_sizes=list(C.SIZES), slots={k: sorted(v) for k, v in C.SLOTS.items()},
                fairway_len=C.FAIRWAY_LEN, tee=C.TEE, par_yards=C.PAR_YARDS)


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, *a): pass

    def send_json(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store"); self.send_header("Content-Length", str(len(b)))
        self.end_headers(); self.wfile.write(b)

    def hole_ref(self, path, prefix):
        """/prefix/<course>/<n> -> (course id, hole number)"""
        cid, _, n = path[len(prefix):].partition("/")
        if not n.isdigit(): raise FileNotFoundError(path)
        r = load_recipe(cid); n = int(n)
        if not 1 <= n <= len(r["holes"]): raise FileNotFoundError(path)
        return cid, n

    def do_GET(self):
        path = urlparse(self.path).path
        try:
            if path in ("/", "/index.html"):
                b = open(PAGE, "rb").read()
                self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(b); return
            if path == "/api/courses": return self.send_json(list_courses())
            if path == "/api/options": return self.send_json(options())
            if path == "/api/props": return self.send_json(prop_sets())
            if path == "/api/groups": return self.send_json(load_groups())
            if path.startswith("/api/recipe/"): return self.send_json(load_recipe(path[len("/api/recipe/"):]))
            if path.startswith("/api/build/"):
                cid, n = self.hole_ref(path, "/api/build/"); hid = f"{cid}-{n:02d}"
                return self.send_json(dict(hole_status(cid, n), log=log_tail(hid)))
            if path.startswith("/art/") and path.endswith((".png", ".json")) and ".." not in path:
                f = os.path.realpath(ROOT + path)
                if not f.startswith(ROOT + "/art/") or not os.path.isfile(f): raise FileNotFoundError(path)
                b = open(f, "rb").read()
                self.send_response(200); self.send_header("Content-Type", "image/png" if f.endswith(".png") else "application/json")
                self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b); return
            if path == "/game" or path.startswith("/game/"):
                self.path = self.path[len("/game"):] or "/"
                return SimpleHTTPRequestHandler.do_GET(self)
            self.send_error(404)
        except FileNotFoundError:
            self.send_json(dict(error="not found"), 404)

    def end_headers(self):
        if self.path.endswith((".jpg", ".png", ".json")): self.send_header("Cache-Control", "no-store")
        SimpleHTTPRequestHandler.end_headers(self)

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
            if path == "/api/preview":            # {course: {id, theme}, n, hole}
                course = body.get("course") or {}
                cid = course.get("id", "x") if COURSE_ID.match(str(course.get("id", ""))) else "x"
                try: return self.send_json(C.preview({"id": cid}, int(body.get("n", 1)), {**body["hole"], "theme": course.get("theme", "classic")}))
                except (C.RecipeError, KeyError, TypeError, ValueError) as e: return self.send_json(dict(error=str(e)), 400)
            if path == "/api/new": return self.send_json(new_course(body))
            if path == "/api/groups": return self.send_json(save_groups(body))
            if path.startswith("/api/recipe/"): return self.send_json(save_recipe(path[len("/api/recipe/"):], body))
            if path.startswith("/api/build/"):
                cid, n = self.hole_ref(path, "/api/build/"); start_build(cid, n)
                return self.send_json(hole_status(cid, n))
            self.send_error(404)
        except FileNotFoundError:
            self.send_json(dict(error="not found"), 404)
        except (ValueError, TypeError) as e:
            self.send_json(dict(error=str(e)), 400)


if __name__ == "__main__":
    os.chdir(GAME)
    port = int(os.environ.get("PORT", "8790"))
    print(f"Course editor on http://localhost:{port}  (game at http://localhost:{port}/game/)")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
