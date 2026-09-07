/* Diagnostic d'installation. Vérifie une à une les conditions que Chrome
   impose avant de proposer l'ajout à l'écran d'accueil. */

(function () {
  "use strict";

  var set = function (id, ok, label) {
    var el = document.getElementById(id);
    el.textContent = label;
    el.className = ok === null ? "" : (ok ? "diag-ok" : "diag-bad");
    return ok;
  };

  var results = {};

  results.https = set("c-https", location.protocol === "https:" ||
    location.hostname === "localhost",
    location.protocol === "https:" ? "oui" : "non — " + location.protocol);

  var ua = navigator.userAgent;
  var chromium = /chrome|chromium|edg/i.test(ua) && !/firefox/i.test(ua);
  results.browser = set("c-browser", chromium,
    chromium ? "compatible" : "ce navigateur ne sait pas installer d'application");

  var standalone = window.matchMedia("(display-mode: standalone)").matches ||
                   window.navigator.standalone === true;
  set("c-standalone", null, standalone ? "oui, tu es dans l'app installée" : "non");
  results.standalone = standalone;

  fetch("/manifest.webmanifest")
    .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
    .then(function (m) {
      results.manifest = set("c-manifest", true, "oui");
      var sizes = (m.icons || []).map(function (i) { return i.sizes; });
      var ok = sizes.indexOf("192x192") > -1 && sizes.indexOf("512x512") > -1;
      results.icons = set("c-icons", ok, ok ? sizes.join(", ") : "manquantes");
    })
    .catch(function (code) {
      results.manifest = set("c-manifest", false, "introuvable (" + code + ")");
      results.icons = set("c-icons", false, "non vérifiable");
    });

  if (!("serviceWorker" in navigator)) {
    results.sw = set("c-sw", false, "non pris en charge");
  } else {
    navigator.serviceWorker.getRegistration().then(function (reg) {
      if (reg && reg.active) {
        results.sw = set("c-sw", true, "actif");
      } else if (reg) {
        results.sw = set("c-sw", false, "en cours d'installation — recharge la page");
      } else {
        results.sw = set("c-sw", false, "non enregistré");
      }
      verdict();
    });
  }

  var promptReady = function () {
    results.prompt = set("c-prompt", true, "oui");
    document.getElementById("install-now").hidden = false;
    verdict();
  };

  if (window.__installEvent) {
    promptReady();
  } else {
    window.addEventListener("install-ready", promptReady);
    setTimeout(function () {
      if (!window.__installEvent) {
        results.prompt = set("c-prompt", false,
          standalone ? "déjà installée" : "pas encore — voir ci-dessous");
        verdict();
      }
    }, 3000);
  }

  document.getElementById("install-now").addEventListener("click", function () {
    if (window.__installEvent) window.__installEvent.prompt();
  });

  document.getElementById("reset-hidden").addEventListener("click", function () {
    try {
      localStorage.removeItem("soph-install-hidden");
      localStorage.removeItem("soph-installed");
    } catch (e) {}
    location.reload();
  });

  var done = false;
  var verdict = function () {
    if (done) return;
    var box = document.getElementById("verdict");
    var head = box.querySelector("b");
    var body = box.querySelector("span");

    if (results.standalone) {
      head.textContent = "C'est déjà installé";
      body.textContent = "Tu utilises l'application, pas le navigateur. " +
        "Le partage depuis Instagram doit fonctionner.";
    } else if (results.prompt) {
      head.textContent = "Tout est prêt";
      body.textContent = "Appuie sur « Installer maintenant » juste au-dessus.";
    } else if (results.browser === false) {
      head.textContent = "Change de navigateur";
      body.textContent = "Firefox et Safari sur ordinateur ne savent pas installer " +
        "d'application web. Ouvre le lien dans Chrome sur le téléphone d'Soph.";
    } else if (results.sw === false) {
      head.textContent = "Le service worker n'est pas actif";
      body.textContent = "Recharge la page une fois : il s'active au second " +
        "chargement. Si ça persiste, vide le cache du site.";
    } else if (results.https === false) {
      head.textContent = "Il faut du HTTPS";
      body.textContent = "Utilise l'adresse en https:// fournie par Railway.";
    } else {
      head.textContent = "Installe depuis le menu";
      body.textContent = "Tout est en place mais Chrome n'a pas proposé " +
        "l'installation. Ouvre le menu ⋮ puis « Installer l'application » — " +
        "ça marche aussi bien.";
      done = true;
    }
    box.hidden = false;
  };

  setTimeout(verdict, 3500);
})();
