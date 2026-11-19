"""Local course editor: move a hole's tee, layup and green on a satellite map, set par / SI / yardages,
save to data/<course>-NN.json and rebuild the hole's game assets.

    python3 tools/course_editor.py            # then open http://localhost:8790
    PORT=8800 python3 tools/course_editor.py

Only listens on 127.0.0.1. The first save of a hole keeps its original data in
build/editor-backups/<hole>.orig.json (and the previous version in <hole>.prev.json), so it can be restored.
"""
import glob, json, os, re, shutil, subprocess, sys, tempfile, threading, time
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA, GAME = f"{ROOT}/data", f"{ROOT}/game"
BACKUP = f"{ROOT}/build/editor-backups"
PAGE = f"{ROOT}/tools/editor/index.html"
HOLE_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*-\d\d$")
POINTS = ("tee", "layup", "green")
NUMBERS = ("par", "si", "yards_yellow", "yards_white", "yards_red")

jobs = {}          # hole id -> {"state": queued|running|done|failed, "started": t, "finished": t}
build_lock = threading.Lock()        # one build at a time: each one is CPU-heavy


def split_id(hid):
    course, n = hid.rsplit("-", 1)
    return course, n


def course_names():
    try:
        return {c["id"]: c["name"] for c in json.load(open(f"{GAME}/courses/courses.json"))}
    except (OSError, ValueError):
        return {}


def list_courses():
    names, out = course_names(), {}
    for f in sorted(glob.glob(f"{DATA}/*-[0-9][0-9].json")):
        hid = os.path.basename(f)[:-5]
        course, n = split_id(hid)
        h = json.load(open(f))
        c = out.setdefault(course, dict(id=course, name=names.get(course) or h.get("course", course), holes=[]))
        built = f"{GAME}/courses/{course}/{n}/game_data.json"
        c["holes"].append(dict(id=hid, n=h["hole"], par=h["par"], si=h.get("si"), yards=h.get("yards_yellow"),
                               built=os.path.exists(built), built_at=os.path.getmtime(built) if os.path.exists(built) else None,
                               edited=os.path.exists(f"{BACKUP}/{hid}.orig.json"), job=jobs.get(hid)))
    return list(out.values())


def load_hole(hid):
    h = json.load(open(f"{DATA}/{hid}.json"))
    course, n = split_id(hid)
    orig_path = f"{BACKUP}/{hid}.orig.json"
    orig = json.load(open(orig_path)) if os.path.exists(orig_path) else h
    built = f"{GAME}/courses/{course}/{n}"
    info = {k: v for k, v in h.items() if k not in ("grid", "green_grid")}
    info.update(id=hid, course_id=course, dir=n, original={k: orig[k] for k in POINTS + NUMBERS if k in orig},
                built=os.path.exists(f"{built}/game_data.json"),
                built_at=os.path.getmtime(f"{built}/course.jpg") if os.path.exists(f"{built}/course.jpg") else None,
                preview=f"/game/courses/{course}/{n}/course.jpg", job=jobs.get(hid))
    return info


def check_point(p):
    if not (isinstance(p, list) and len(p) == 2 and all(isinstance(v, (int, float)) for v in p)):
        raise ValueError("points must be [lat, lng]")
    if not (-90 <= p[0] <= 90 and -180 <= p[1] <= 180):
        raise ValueError("point out of range")
    return [float(p[0]), float(p[1])]


MAP_POLYS = ("fairway", "green", "bunker", "water", "wood")


def check_map(m):
    """A drawn map: lists of polygons (each a list of [lat, lng]) per kind, single trees, and the treeline switch."""
    if m is None: return None
    if not isinstance(m, dict): raise ValueError("map must be an object")
    out = {k: [[check_point(p) for p in P] for P in m.get(k, []) if isinstance(P, list) and len(P) >= 3] for k in MAP_POLYS}
    out["trees"] = [check_point(p) for p in m.get("trees", [])]
    out["auto_trees"] = bool(m.get("auto_trees", True))
    return out


def auto_layout(hid):
    """The renderer's own fairway, bunkers and water for this hole, as a starting map (takes a few seconds)."""
    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run([sys.executable, f"{ROOT}/tools/render_hole_toon.py", f"{DATA}/{hid}.json", f"{tmp}/auto.json"],
                           env=dict(os.environ, FEATURES_ONLY="1"), cwd=tmp, capture_output=True, text=True)
        if r.returncode != 0: raise RuntimeError(r.stderr[-800:])
        return json.load(open(f"{tmp}/auto.json"))


def save_hole(hid, body):
    path = f"{DATA}/{hid}.json"
    h = json.load(open(path))
    if "map" in body:
        m = check_map(body["map"])
        if m is None: h.pop("map", None)
        else: h["map"] = m
    for k in POINTS:
        if k in body:
            new = check_point(body[k])
            if k == "green":           # front/back aren't used by the renderer; keep them where they were relative to the centre
                dlat, dlng = new[0] - h["green"][0], new[1] - h["green"][1]
                for fb in ("green_front", "green_back"):
                    if fb in h: h[fb] = [h[fb][0] + dlat, h[fb][1] + dlng]
            h[k] = new
    for k in NUMBERS:
        if k in body and body[k] is not None:
            v = int(body[k])
            if k == "par" and v not in (3, 4, 5, 6): raise ValueError("par must be 3-6")
            if k == "si" and not 1 <= v <= 18: raise ValueError("SI must be 1-18")
            if k.startswith("yards") and not 50 <= v <= 800: raise ValueError("yards must be 50-800")
            h[k] = v
    os.makedirs(BACKUP, exist_ok=True)           # back up only once the edit is known to be valid
    if not os.path.exists(f"{BACKUP}/{hid}.orig.json"):
        shutil.copy(path, f"{BACKUP}/{hid}.orig.json")
    shutil.copy(path, f"{BACKUP}/{hid}.prev.json")
    tmp = path + ".tmp"
    json.dump(h, open(tmp, "w")); os.replace(tmp, path)


def restore_hole(hid):
    orig = f"{BACKUP}/{hid}.orig.json"
    if not os.path.exists(orig): raise ValueError("this hole hasn't been edited")
    shutil.copy(f"{DATA}/{hid}.json", f"{BACKUP}/{hid}.prev.json")
    shutil.copy(orig, f"{DATA}/{hid}.json")


def run_build(hid):
    course, n = split_id(hid)
    log = f"{ROOT}/build/{hid}.log"
    with build_lock:
        jobs[hid] = dict(state="running", started=time.time())
        env = dict(os.environ, HOLE=hid, OUT=f"{GAME}/courses/{course}/{n}")
        with open(log, "w") as lf:
            ok = subprocess.run(["bash", f"{ROOT}/tools/build_course.sh"], env=env, stdout=lf, stderr=subprocess.STDOUT,
                                cwd=ROOT).returncode == 0
            if ok:
                name = course_names().get(course) or json.load(open(f"{DATA}/{hid}.json")).get("course", course)
                ok = subprocess.run([sys.executable, f"{ROOT}/tools/course_index.py", course, name], stdout=lf,
                                    stderr=subprocess.STDOUT, cwd=ROOT).returncode == 0
        jobs[hid].update(state="done" if ok else "failed", finished=time.time())


def start_build(hid):
    if jobs.get(hid, {}).get("state") in ("queued", "running"): return
    jobs[hid] = dict(state="queued", started=time.time())
    threading.Thread(target=run_build, args=(hid,), daemon=True).start()


def log_tail(hid, lines=25):
    try:
        with open(f"{ROOT}/build/{hid}.log") as f: return "".join(f.readlines()[-lines:])
    except OSError:
        return ""


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, *a): pass

    def send_json(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store"); self.send_header("Content-Length", str(len(b)))
        self.end_headers(); self.wfile.write(b)

    def hole_id(self, path, prefix):
        hid = path[len(prefix):]
        if not HOLE_ID.match(hid) or not os.path.exists(f"{DATA}/{hid}.json"): raise FileNotFoundError(hid)
        return hid

    def do_GET(self):
        path = urlparse(self.path).path
        try:
            if path in ("/", "/index.html"):
                b = open(PAGE, "rb").read()
                self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(b); return
            if path == "/api/courses": return self.send_json(list_courses())
            if path.startswith("/api/hole/"): return self.send_json(load_hole(self.hole_id(path, "/api/hole/")))
            if path.startswith("/api/auto/"):
                try: return self.send_json(auto_layout(self.hole_id(path, "/api/auto/")))
                except RuntimeError as e: return self.send_json(dict(error=str(e)), 500)
            if path.startswith("/api/build/"):
                hid = self.hole_id(path, "/api/build/")
                return self.send_json(dict(job=jobs.get(hid), log=log_tail(hid)))
            if path == "/game" or path.startswith("/game/"):
                self.path = self.path[len("/game"):] or "/"
                return SimpleHTTPRequestHandler.do_GET(self)
            self.send_error(404)
        except FileNotFoundError:
            self.send_json(dict(error="no such hole"), 404)

    def end_headers(self):
        if self.path.endswith((".jpg", ".png", ".json")): self.send_header("Cache-Control", "no-store")
        SimpleHTTPRequestHandler.end_headers(self)

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
            if path.startswith("/api/hole/"):
                hid = self.hole_id(path, "/api/hole/")
                save_hole(hid, body)
                if body.get("rebuild"): start_build(hid)
                return self.send_json(load_hole(hid))
            if path.startswith("/api/restore/"):
                hid = self.hole_id(path, "/api/restore/"); restore_hole(hid)
                return self.send_json(load_hole(hid))
            if path.startswith("/api/build/"):
                hid = self.hole_id(path, "/api/build/"); start_build(hid)
                return self.send_json(dict(job=jobs.get(hid)))
            self.send_error(404)
        except FileNotFoundError:
            self.send_json(dict(error="no such hole"), 404)
        except (ValueError, TypeError) as e:
            self.send_json(dict(error=str(e)), 400)


if __name__ == "__main__":
    os.chdir(GAME)
    port = int(os.environ.get("PORT", "8790"))
    print(f"Course editor on http://localhost:{port}  (game at http://localhost:{port}/game/)")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
