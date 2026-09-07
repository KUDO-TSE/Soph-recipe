/* Les recettes de Soph — one small script for all screens. */

(function () {
  "use strict";

  var $ = function (sel, root) { return (root || document).querySelector(sel); };
  var $$ = function (sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); };

  /* ---------------- Installation sur l'écran d'accueil ---------------- */

  // Enregistré tout de suite, pas sur l'événement load : Chrome ne considère le
  // site installable qu'une fois le service worker actif, et attendre load
  // retardait ça d'un chargement de page entier.
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js").catch(function () {});
  }

  var standalone = window.matchMedia("(display-mode: standalone)").matches ||
                   window.navigator.standalone === true;
  var isIOS = /iphone|ipad|ipod/i.test(navigator.userAgent);
  var isAndroid = /android/i.test(navigator.userAgent);
  var HIDE_KEY = "soph-install-hidden";

  var hidden = false;
  try {
    hidden = localStorage.getItem(HIDE_KEY) === "1" ||
             localStorage.getItem("soph-installed") === "1";
  } catch (e) {}

  var shown = false;

  var showInstall = function (html, onInstall) {
    if (shown || standalone || hidden) return;
    shown = true;

    var el = document.createElement("div");
    el.className = "install";

    var text = document.createElement("div");
    text.className = "install-text";
    text.innerHTML = html;
    el.appendChild(text);

    if (onInstall) {
      var go = document.createElement("button");
      go.className = "install-go";
      go.type = "button";
      go.textContent = "Installer";
      go.addEventListener("click", function () { onInstall(el); });
      el.appendChild(go);
    }

    var close = document.createElement("button");
    close.className = "install-x";
    close.type = "button";
    close.setAttribute("aria-label", "Masquer");
    close.textContent = "×";
    close.addEventListener("click", function () {
      el.remove();
      try { localStorage.setItem(HIDE_KEY, "1"); } catch (e) {}
    });
    el.appendChild(close);

    document.body.appendChild(el);
  };

  var oneTap = function () {
    var ev = window.__installEvent;
    if (!ev) return false;
    showInstall(
      "<b>Installe les recettes</b><span>Pour l'ouvrir comme une vraie app, et " +
      "pouvoir partager depuis Instagram.</span>",
      function (el) {
        ev.prompt();
        (ev.userChoice || Promise.resolve()).then(function () { el.remove(); });
      }
    );
    return true;
  };

  // Si l'événement est déjà arrivé (capturé dans le <head>), on l'utilise.
  // Sinon on attend qu'il arrive, avec un repli manuel si rien ne vient :
  // beforeinstallprompt ne se déclenche jamais sur iOS, ni sur Firefox, et pas
  // toujours au premier chargement sur Chrome.
  if (!standalone && !hidden) {
    window.addEventListener("install-ready", oneTap);

    if (!oneTap()) {
      setTimeout(function () {
        if (oneTap()) return;
        if (isIOS) {
          showInstall(
            "<b>Installe les recettes</b><span>Appuie sur <b>Partager</b> en bas " +
            "de l'écran, puis sur <b>Sur l'écran d'accueil</b>.</span>"
          );
        } else if (isAndroid) {
          showInstall(
            "<b>Installe les recettes</b><span>Ouvre le menu <b>⋮</b> en haut à " +
            "droite, puis <b>Installer l'application</b>.</span>"
          );
        } else {
          showInstall(
            "<b>Installe les recettes</b><span>Dans Chrome, clique sur l'icône " +
            "d'installation dans la barre d'adresse, ou menu <b>⋮</b> puis " +
            "<b>Installer</b>. <a href=\"/installation\">Vérifier l'installation</a>" +
            "</span>"
          );
        }
      }, 2500);
    }
  }

  /* ---------------- Écran de lecture (partage Android) ---------------- */

  var reading = $("#reading");
  if (reading) {
    var rid = reading.getAttribute("data-rid");

    fetch("/api/extract/" + rid, { method: "POST" })
      .then(function (res) { return res.json().then(function (d) { return { ok: res.ok, d: d }; }); })
      .then(function (r) {
        if (r.ok && r.d.next) {
          window.location.replace(r.d.next);
          return;
        }
        $("#reading-msg").textContent = "Lecture impossible";
        $("#reading-sub").hidden = true;
        var err = $("#reading-error");
        err.textContent = r.d.error || "Le contenu partagé n'a pas pu être lu.";
        err.hidden = false;
        $("#reading-out").hidden = false;
      })
      .catch(function () {
        $("#reading-msg").textContent = "Lecture impossible";
        $("#reading-sub").hidden = true;
        var err2 = $("#reading-error");
        err2.textContent = "Pas de réponse du serveur. Vérifie ta connexion.";
        err2.hidden = false;
        $("#reading-out").hidden = false;
      });
  }

  /* ---------------- Import screen ---------------- */

  var importForm = $("#import-form");
  if (importForm) {
    var working = $("#working");
    var errorBox = $("#import-error");

    var showError = function (msg) {
      errorBox.textContent = msg;
      errorBox.hidden = false;
      working.hidden = true;
      errorBox.scrollIntoView({ block: "center", behavior: "smooth" });
    };

    importForm.addEventListener("submit", function (ev) {
      ev.preventDefault();
      errorBox.hidden = true;

      var url = $("#url").value.trim();
      var text = $("#text").value.trim();
      var photo = $("#photo").files[0];

      if (!url && !text && !photo) {
        showError("Colle un lien, ou le texte de la recette.");
        $("#manual-fold").open = true;
        return;
      }

      var body = new FormData();
      body.append("url", url);
      body.append("text", text);
      if (photo) body.append("photo", photo);

      working.hidden = false;

      fetch("/api/import", { method: "POST", body: body })
        .then(function (res) { return res.json().then(function (d) { return { ok: res.ok, d: d }; }); })
        .then(function (r) {
          if (!r.ok) {
            showError(r.d.error || "La lecture a échoué.");
            $("#manual-fold").open = true;
            return;
          }
          window.location.href = r.d.next;
        })
        .catch(function () {
          showError("Pas de réponse du serveur. Vérifie ta connexion et réessaie.");
        });
    });

    $("#blank-go").addEventListener("click", function () {
      fetch("/api/blank", { method: "POST" })
        .then(function (res) { return res.json(); })
        .then(function (d) { window.location.href = d.next; })
        .catch(function () { showError("Impossible de créer une fiche vide."); });
    });
  }

  /* ---------------- Recipe card ---------------- */

  var card = $(".card");
  if (card) {
    var recipeId = card.getAttribute("data-recipe-id");

    // Tabs
    $$(".tab").forEach(function (tab) {
      tab.addEventListener("click", function () {
        $$(".tab").forEach(function (t) {
          var on = t === tab;
          t.classList.toggle("on", on);
          t.setAttribute("aria-selected", on ? "true" : "false");
          $("#" + t.getAttribute("data-panel")).hidden = !on;
        });
      });
    });

    // Ingredient ticks survive a reload — handy mid-shop or mid-cook.
    var storeKey = "soph-ticks-" + recipeId;
    var ticks = {};
    try { ticks = JSON.parse(localStorage.getItem(storeKey) || "{}"); } catch (e) { ticks = {}; }

    $$(".ing-check").forEach(function (box) {
      var key = box.getAttribute("data-key");
      if (ticks[key]) box.checked = true;
      box.addEventListener("change", function () {
        ticks[key] = box.checked;
        try { localStorage.setItem(storeKey, JSON.stringify(ticks)); } catch (e) {}
      });
    });

    var uncheck = $("#uncheck-all");
    if (uncheck) {
      uncheck.addEventListener("click", function () {
        $$(".ing-check").forEach(function (b) { b.checked = false; });
        ticks = {};
        try { localStorage.removeItem(storeKey); } catch (e) {}
      });
    }

    // Favourite
    var fav = $("#fav");
    if (fav) {
      fav.addEventListener("click", function () {
        fetch("/recipe/" + recipeId + "/favorite", { method: "POST" })
          .then(function (res) { return res.json(); })
          .then(function (d) {
            fav.classList.toggle("on", d.is_favorite);
            fav.setAttribute("aria-pressed", d.is_favorite ? "true" : "false");
          });
      });
    }

    // Delete guard (kept in JS so apostrophes in titles can't break the prompt)
    var deleteForm = $("#delete-form");
    if (deleteForm) {
      deleteForm.addEventListener("submit", function (ev) {
        var title = deleteForm.getAttribute("data-title") || "cette recette";
        if (!window.confirm("Supprimer « " + title + " » ?")) ev.preventDefault();
      });
    }

    // Cook mode
    var cook = $("#cook");
    if (cook) {
      var steps = JSON.parse($("#cook-data").textContent);
      var at = 0;
      var noEl = $("#cook-no");
      var textEl = $("#cook-text");
      var countEl = $("#cook-count");
      var prev = $("#cook-prev");
      var next = $("#cook-next");

      var paint = function () {
        noEl.textContent = at + 1;
        textEl.textContent = steps[at];
        countEl.textContent = "Étape " + (at + 1) + " sur " + steps.length;
        prev.disabled = at === 0;
        next.textContent = at === steps.length - 1 ? "C'est prêt !" : "Suivant";
      };

      var open = function () {
        at = 0;
        paint();
        cook.hidden = false;
        document.body.style.overflow = "hidden";
      };

      var close = function () {
        cook.hidden = true;
        document.body.style.overflow = "";
      };

      $("#cook-go").addEventListener("click", open);
      $("#cook-close").addEventListener("click", close);

      prev.addEventListener("click", function () {
        if (at > 0) { at -= 1; paint(); }
      });

      next.addEventListener("click", function () {
        if (at < steps.length - 1) {
          at += 1;
          paint();
        } else {
          fetch("/recipe/" + recipeId + "/cooked", { method: "POST" }).catch(function () {});
          close();
        }
      });

      document.addEventListener("keydown", function (ev) {
        if (cook.hidden) return;
        if (ev.key === "Escape") close();
        if (ev.key === "ArrowRight") next.click();
        if (ev.key === "ArrowLeft") prev.click();
      });
    }
  }

  /* ---------------- Editor ---------------- */

  var editForm = $("#edit-form");
  if (editForm) {
    var seed = JSON.parse($("#seed").textContent || "{}");
    var ingRows = $("#ing-rows");
    var stepRows = $("#step-rows");

    var renumber = function () {
      $$(".row-no", stepRows).forEach(function (el, i) { el.textContent = i + 1; });
    };

    var killButton = function (row) {
      var b = document.createElement("button");
      b.type = "button";
      b.className = "row-kill";
      b.setAttribute("aria-label", "Supprimer cette ligne");
      b.textContent = "×";
      b.addEventListener("click", function () { row.remove(); renumber(); });
      return b;
    };

    var addIng = function (ing) {
      var row = document.createElement("div");
      row.className = "row";

      var qty = document.createElement("input");
      qty.type = "text";
      qty.className = "qty";
      qty.placeholder = "200 g";
      qty.value = (ing && ing.qty) || "";

      var item = document.createElement("input");
      item.type = "text";
      item.className = "item";
      item.placeholder = "farine";
      item.value = (ing && ing.item) || "";

      row.appendChild(qty);
      row.appendChild(item);
      row.appendChild(killButton(row));
      ingRows.appendChild(row);
      return item;
    };

    var addStep = function (text) {
      var row = document.createElement("div");
      row.className = "row";

      var no = document.createElement("span");
      no.className = "row-no";

      var box = document.createElement("textarea");
      box.rows = 2;
      box.placeholder = "Mélange la farine et le sucre.";
      box.value = text || "";

      row.appendChild(no);
      row.appendChild(box);
      row.appendChild(killButton(row));
      stepRows.appendChild(row);
      renumber();
      return box;
    };

    (seed.ingredients || []).forEach(addIng);
    (seed.steps || []).forEach(addStep);
    if (!(seed.ingredients || []).length) addIng();
    if (!(seed.steps || []).length) addStep();

    $("#ing-add").addEventListener("click", function () { addIng().focus(); });
    $("#step-add").addEventListener("click", function () { addStep().focus(); });

    editForm.addEventListener("submit", function () {
      var ingredients = $$(".row", ingRows).map(function (row) {
        return {
          qty: $(".qty", row).value.trim(),
          item: $(".item", row).value.trim()
        };
      }).filter(function (x) { return x.item; });

      var steps = $$("textarea", stepRows).map(function (t) {
        return t.value.trim();
      }).filter(Boolean);

      $("#payload").value = JSON.stringify({
        title: $("#f-title").value.trim(),
        emoji: $("#f-emoji").value.trim(),
        servings: $("#f-servings").value.trim(),
        total_time: $("#f-time").value.trim(),
        notes: $("#f-notes").value.trim(),
        ingredients: ingredients,
        steps: steps
      });
    });
  }
})();
