// BattleGolf service worker: keeps the game itself on the phone so it opens instantly and offline.
// Online match data (Supabase) always goes to the network and is never cached here.
// Bump VERSION whenever game files change so phones pick up the new ones.
const VERSION = "bg-v1";
const CORE = [
  "./", "index.html", "config.js", "manifest.webmanifest",
  "game_data.json", "game_data_portrait.json",
  "course.jpg", "course_portrait.jpg", "detail_land.jpg", "detail_portrait.jpg",
  "detail_land_heat.png", "detail_portrait_heat.png", "detail_land_contours.png", "detail_portrait_contours.png",
  "icons/icon-192.png", "icons/icon-512.png", "icons/apple-touch-icon.png",
  "https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.45.4/dist/umd/supabase.js",
];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(VERSION).then(c => c.addAll(CORE)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k !== VERSION).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});
self.addEventListener("fetch", e => {
  const req = e.request, url = new URL(req.url);
  if (req.method !== "GET" || url.hostname.endsWith("supabase.co")) return;   // live match data: network only
  // the page itself: network first (so updates show up), falling back to the cached copy offline
  if (req.mode === "navigate") {
    e.respondWith(fetch(req).then(r => { const copy = r.clone(); caches.open(VERSION).then(c => c.put("index.html", copy)); return r; })
      .catch(() => caches.match("index.html")));
    return;
  }
  // everything else: cached copy straight away, refreshed in the background
  e.respondWith(caches.match(req, { ignoreSearch: true }).then(hit => {
    const net = fetch(req).then(r => { if (r.ok) { const copy = r.clone(); caches.open(VERSION).then(c => c.put(req, copy)); } return r; }).catch(() => hit);
    return hit || net;
  }));
});
