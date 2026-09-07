import json
import os
import re
from functools import wraps

from flask import (
    Flask,
    Response,
    send_from_directory,
    abort,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

import db
import extract

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-change-me")
app.config["MAX_CONTENT_LENGTH"] = 12 * 1024 * 1024  # 12 MB photo upload ceiling
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

APP_PIN = os.environ.get("APP_PIN", "").strip()

try:
    db.init_db()
except Exception as exc:  # the app should still boot and show a readable error
    app.logger.error("Database init failed: %s", exc)


def locked(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if APP_PIN and not session.get("unlocked"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "Session expirée. Recharge la page."}), 401
            return redirect(url_for("login", next=request.full_path))
        return view(*args, **kwargs)

    return wrapper


@app.route("/login", methods=["GET", "POST"])
def login():
    if not APP_PIN:
        return redirect(url_for("index"))
    error = None
    if request.method == "POST":
        if request.form.get("pin", "").strip() == APP_PIN:
            session["unlocked"] = True
            session.permanent = True
            return redirect(request.args.get("next") or url_for("index"))
        error = "Ce code ne marche pas."
    return render_template("login.html", error=error)


@app.get("/")
@locked
def index():
    search = (request.args.get("q") or "").strip()
    try:
        db.purge_stale_drafts()
        recipes = db.list_recipes(search or None)
        stats = db.counts()
    except Exception as exc:
        app.logger.error("index failed: %s", exc)
        return render_template(
            "error.html",
            message="L'application n'arrive pas à joindre la base de données.",
            detail=str(exc),
        ), 500
    return render_template("index.html", recipes=recipes, search=search, stats=stats)


@app.get("/add")
@locked
def add():
    return render_template("add.html")


@app.post("/api/import")
@locked
def api_import():
    payload = request.form if request.form else (request.get_json(silent=True) or {})
    url = payload.get("url", "")
    text = payload.get("text", "")
    upload = None
    if "photo" in request.files and request.files["photo"].filename:
        upload = request.files["photo"].read()

    if not (url.strip() or text.strip() or upload):
        return jsonify({"error": "Colle un lien ou le texte de la recette."}), 400

    try:
        recipe, image = extract.build_draft(url=url, text=text, upload=upload)
        rid = db.create_draft(recipe, image=image)
    except extract.ExtractError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        app.logger.exception("import failed: %s", exc)
        return jsonify(
            {
                "error": "Quelque chose a bloqué de notre côté. Réessaie, ou colle "
                         "directement le texte de la recette."
            }
        ), 500

    return jsonify({"id": rid, "next": url_for("edit", rid=rid)})


@app.post("/api/blank")
@locked
def api_blank():
    rid = db.create_draft({"title": "", "ingredients": [], "steps": []})
    return jsonify({"id": rid, "next": url_for("edit", rid=rid)})


@app.post("/share")
@locked
def share():
    """Cible de partage Android.

    Instagram envoie soit un lien (dans `text`), soit une capture d'écran
    (dans `photo`), soit les deux. On enregistre tel quel et on renvoie tout
    de suite vers l'écran de lecture : la lecture par Claude prend une dizaine
    de secondes, trop long pour laisser un POST en attente.
    """
    text = " ".join(
        filter(None, [request.form.get("title", ""), request.form.get("text", "")])
    ).strip()
    url = (request.form.get("url") or "").strip()

    if not url:
        found = re.search(r"https?://\S+", text)
        if found:
            url = found.group(0).rstrip(").,")

    image = None
    if "photo" in request.files and request.files["photo"].filename:
        image = extract.shrink(request.files["photo"].read())

    if not (text or url or image):
        return redirect(url_for("add"))

    rid = db.create_draft(
        {
            "title": "",
            "raw_source": text,
            "source_url": url or None,
            "source_platform": extract.detect_platform(url),
        },
        image=image,
    )
    return redirect(url_for("reading", rid=rid), code=303)


@app.get("/recipe/<int:rid>/lecture")
@locked
def reading(rid):
    if not db.get_recipe(rid):
        abort(404)
    return render_template("reading.html", rid=rid)


@app.post("/api/extract/<int:rid>")
@locked
def api_extract(rid):
    """Lit le contenu déjà stocké par /share et le transforme en fiche."""
    raw = db.get_raw(rid)
    if not raw:
        return jsonify({"error": "Ce partage n'existe plus."}), 404

    image = None
    if raw.get("image_data"):
        image = (bytes(raw["image_data"]), raw.get("image_mime") or "image/jpeg")

    try:
        recipe_data, fetched_image = extract.build_draft(
            url=raw.get("source_url") or "",
            text=raw.get("raw_source") or "",
            preloaded_image=image,
        )
    except extract.ExtractError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        app.logger.exception("share extract failed: %s", exc)
        return jsonify(
            {"error": "La lecture a échoué. Ouvre la fiche et écris-la à la main."}
        ), 500

    db.save_recipe(rid, recipe_data, image=fetched_image if not image else None)
    db.set_draft(rid, True)
    db.clear_raw(rid)
    return jsonify({"next": url_for("edit", rid=rid)})


@app.get("/diagnostic")
@locked
def diagnostic():
    """Montre ce que le serveur reçoit pour un lien, sans appeler Claude.

    Sert à savoir en quelques secondes si l'import automatique a une chance
    de fonctionner depuis l'IP de Railway pour un lien donné.
    """
    url = (request.args.get("url") or "").strip()
    if not url:
        return render_template("diagnostic.html", url="", result=None, verdict=None)

    result = extract.fetch_page(url)
    usable = bool(result.get("description") or result.get("page_text")
                  or result.get("image_alt"))

    if result.get("status") in (401, 403, 429) or result.get("status") == 0:
        verdict = {
            "head": "Meta bloque le serveur",
            "body": "Ce lien ne pourra pas être lu automatiquement. Fais une capture "
                    "d'écran de la publication et partage-la : c'est la voie fiable.",
        }
    elif usable:
        verdict = {
            "head": "Ce lien est lisible automatiquement",
            "body": "Le texte récupéré suffit à construire une fiche. Tu peux coller "
                    "le lien directement dans l'écran d'ajout.",
        }
    elif result.get("image_url"):
        verdict = {
            "head": "Photo seule récupérée",
            "body": "Aucun texte n'est accessible, mais la photo l'est. Claude tentera "
                    "de lire la recette dessus. Si elle n'est pas écrite sur l'image, "
                    "partage plutôt une capture d'écran.",
        }
    else:
        verdict = {
            "head": "Rien à lire sur ce lien",
            "body": "Ni texte ni photo. Passe par la capture d'écran, ou colle le "
                    "texte de la recette à la main.",
        }

    return render_template("diagnostic.html", url=url, result=result, verdict=verdict)


@app.get("/recipe/<int:rid>")
@locked
def recipe(rid):
    row = db.get_recipe(rid)
    if not row:
        abort(404)
    if row["is_draft"]:
        return redirect(url_for("edit", rid=rid))
    return render_template("recipe.html", r=row)


@app.get("/recipe/<int:rid>/edit")
@locked
def edit(rid):
    row = db.get_recipe(rid)
    if not row:
        abort(404)
    return render_template("edit.html", r=row)


@app.post("/recipe/<int:rid>/save")
@locked
def save(rid):
    if not db.get_recipe(rid):
        abort(404)
    try:
        data = json.loads(request.form.get("payload") or "{}")
    except json.JSONDecodeError:
        return redirect(url_for("edit", rid=rid))

    image = None
    if "photo" in request.files and request.files["photo"].filename:
        image = extract.shrink(request.files["photo"].read())

    db.save_recipe(rid, extract.normalise(data), image=image)
    return redirect(url_for("recipe", rid=rid))


@app.post("/recipe/<int:rid>/delete")
@locked
def delete(rid):
    db.delete_recipe(rid)
    return redirect(url_for("index"))


@app.post("/recipe/<int:rid>/favorite")
@locked
def favorite(rid):
    return jsonify({"is_favorite": db.toggle_favorite(rid)})


@app.post("/recipe/<int:rid>/cooked")
@locked
def cooked(rid):
    return jsonify({"times_cooked": db.mark_cooked(rid)})


@app.post("/recipe/<int:rid>/translate")
@locked
def translate(rid):
    """Convertit une recette existante en français + unités métriques."""
    row = db.get_recipe(rid)
    if not row:
        abort(404)
    was_draft = row["is_draft"]
    try:
        fixed = extract.retranslate(dict(row))
    except extract.ExtractError as exc:
        return render_template("error.html", message=str(exc)), 502
    except Exception as exc:
        app.logger.exception("translate failed: %s", exc)
        return render_template(
            "error.html", message="La conversion a échoué. Réessaie dans un instant."
        ), 500

    db.save_recipe(rid, fixed)
    if was_draft:
        db.set_draft(rid, True)
    return redirect(url_for("edit", rid=rid))


@app.get("/image/<int:rid>")
@locked
def image(rid):
    row = db.get_image(rid)
    if not row or not row.get("image_data"):
        abort(404)
    return Response(
        bytes(row["image_data"]),
        mimetype=row.get("image_mime") or "image/jpeg",
        headers={"Cache-Control": "private, max-age=604800"},
    )


@app.get("/sw.js")
def service_worker():
    """Servi depuis la racine pour que le scope couvre tout le site."""
    res = send_from_directory(app.static_folder, "sw.js")
    res.headers["Content-Type"] = "application/javascript; charset=utf-8"
    res.headers["Service-Worker-Allowed"] = "/"
    res.headers["Cache-Control"] = "no-cache"
    return res


@app.get("/manifest.webmanifest")
def manifest():
    return Response(
        json.dumps(
            {
                "name": "Les recettes de Soph",
                "short_name": "Recettes",
                "start_url": "/",
                "description": "Les recettes de la maison, prêtes à cuisiner.",
                "display": "standalone",
                "orientation": "portrait",
                "lang": "fr",
                "scope": "/",
                "background_color": "#F2F5F1",
                "theme_color": "#16261E",
                "share_target": {
                    "action": "/share",
                    "method": "POST",
                    "enctype": "multipart/form-data",
                    "params": {
                        "title": "title",
                        "text": "text",
                        "url": "url",
                        "files": [
                            {"name": "photo", "accept": ["image/*"]}
                        ],
                    },
                },
                "icons": [
                    {"src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png"},
                    {
                        "src": "/static/icon-512.png",
                        "sizes": "512x512",
                        "type": "image/png",
                        "purpose": "any maskable",
                    },
                ],
            }
        ),
        mimetype="application/manifest+json",
    )


@app.get("/healthz")
def healthz():
    try:
        db.counts()
        return "ok", 200
    except Exception as exc:
        return f"db error: {exc}", 500


@app.errorhandler(404)
def not_found(_):
    return render_template(
        "error.html", message="Cette recette n'existe pas, ou elle a été supprimée."
    ), 404


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
