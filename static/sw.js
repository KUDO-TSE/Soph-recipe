/* Service worker. Deux rôles :
   1. rendre l'application installable (Chrome exige un gestionnaire fetch)
   2. garder les recettes lisibles en cuisine même sans réseau */

var CACHE = "soph-v4";

var SHELL = [
  "/",
  "/static/style.css",
  "/static/app.js",
  "/static/install-check.js",
  "/static/icon-192.png",
  "/static/icon-512.png"
];

self.addEventListener("install", function (ev) {
  ev.waitUntil(
    caches.open(CACHE).then(function (c) {
      return c.addAll(SHELL).catch(function () { /* hors ligne à l'installation */ });
    }).then(function () { return self.skipWaiting(); })
  );
});

self.addEventListener("activate", function (ev) {
  ev.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(keys.map(function (k) {
        return k === CACHE ? null : caches.delete(k);
      }));
    }).then(function () { return self.clients.claim(); })
  );
});

var OFFLINE_PAGE =
  '<!doctype html><html lang="fr"><head><meta charset="utf-8">' +
  '<meta name="viewport" content="width=device-width,initial-scale=1">' +
  '<title>Hors ligne</title><style>body{margin:0;padding:60px 24px;background:#F2F5F1;' +
  'color:#16261E;font:400 18px/1.5 system-ui,sans-serif;text-align:center}' +
  'h1{font-size:1.6rem;margin:0 0 10px}p{color:#4A5C52}</style></head><body>' +
  "<h1>Pas de réseau</h1><p>Les recettes déjà ouvertes restent accessibles. " +
  "Reconnecte-toi pour en ajouter une nouvelle.</p></body></html>";

self.addEventListener("fetch", function (ev) {
  var req = ev.request;
  if (req.method !== "GET") return;

  var url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  // Photos et fichiers statiques : le cache d'abord, ils ne changent pas.
  if (url.pathname.startsWith("/static/") || url.pathname.startsWith("/image/")) {
    ev.respondWith(
      caches.match(req).then(function (hit) {
        return hit || fetch(req).then(function (res) {
          if (res.ok) {
            var copy = res.clone();
            caches.open(CACHE).then(function (c) { c.put(req, copy); });
          }
          return res;
        });
      })
    );
    return;
  }

  // Pages : le réseau d'abord pour avoir les dernières recettes,
  // le cache en secours quand la cuisine n'a pas de signal.
  ev.respondWith(
    fetch(req).then(function (res) {
      if (res.ok && res.type === "basic") {
        var copy = res.clone();
        caches.open(CACHE).then(function (c) { c.put(req, copy); });
      }
      return res;
    }).catch(function () {
      return caches.match(req).then(function (hit) {
        return hit || new Response(OFFLINE_PAGE, {
          status: 200,
          headers: { "Content-Type": "text/html; charset=utf-8" }
        });
      });
    })
  );
});
