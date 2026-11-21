// BattleGolf service worker: keeps the game on the phone so it still opens offline.
// Online match data (Supabase) always goes to the network and is never cached here.
// The game's own files (page, course list, hole pictures) are network-first: a rebuilt hole keeps its file
// names, so serving the cache first would show the old one. The cache is the offline fallback, and hole
// pictures are added to it as each hole is played.
const VERSION = "bg-v34";
const CORE = [
  "./", "index.html", "config.js", "manifest.webmanifest", "courses/courses.json", "logo.webp",
  "icons/icon-192.png", "icons/icon-512.png", "icons/apple-touch-icon.png", "audio/mischief.mp3",
  "https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.45.4/dist/umd/supabase.js",
];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(VERSION).then(c => c.addAll(CORE)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k !== VERSION).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});
const store = (key, r) => { if (r.ok) { const copy = r.clone(); caches.open(VERSION).then(c => c.put(key, copy)); } return r; };
self.addEventListener("fetch", e => {
  const req = e.request, url = new URL(req.url);
  if (req.method !== "GET" || url.hostname.endsWith("supabase.co")) return;   // live match data: network only
  if (req.mode === "navigate") {
    e.respondWith(fetch(req).then(r => store("index.html", r)).catch(() => caches.match("index.html")));
    return;
  }
  if (url.origin === location.origin) {                    // game files: fresh when online, cached when not
    e.respondWith(fetch(req).then(r => store(req, r)).catch(() => caches.match(req, { ignoreSearch: true })));
    return;
  }
  if (url.hostname !== "cdn.jsdelivr.net") return;         // ads and anything else: straight to the network
  // the pinned CDN library never changes: cache first
  e.respondWith(caches.match(req).then(hit => hit || fetch(req).then(r => store(req, r))));
});
