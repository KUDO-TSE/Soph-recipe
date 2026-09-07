import json
import os
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
