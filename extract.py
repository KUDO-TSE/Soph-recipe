"""Turn a social media link (or pasted text) into a structured recipe.

Two stages:
  1. fetch_page()  -> pull Open Graph metadata + the post photo
  2. structure()   -> hand the caption and the photo to Claude, get clean JSON back
"""

import base64
import logging
import io
import json
import os
import re

import requests
from bs4 import BeautifulSoup
from PIL import Image

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5")

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
}

MAX_PX = 1400
JPEG_QUALITY = 82


class ExtractError(Exception):
    pass


def detect_platform(url):
    u = (url or "").lower()
    if "instagram.com" in u:
        return "instagram"
    if "facebook.com" in u or "fb.watch" in u or "fb.me" in u:
        return "facebook"
    if "tiktok.com" in u:
        return "tiktok"
    if u.startswith("http"):
        return "web"
    return None


def fetch_page(url):
    """Best-effort Open Graph scrape. Returns dict, never raises on a bad page."""
    out = {"title": "", "description": "", "image_url": "", "page_text": ""}
    try:
        r = requests.get(url, headers=HEADERS, timeout=20, allow_redirects=True)
        if r.status_code >= 400:
            return out
        soup = BeautifulSoup(r.text, "html.parser")

        def meta(*names):
            for n in names:
                tag = soup.find("meta", attrs={"property": n}) or soup.find(
                    "meta", attrs={"name": n}
                )
                if tag and tag.get("content"):
                    return tag["content"].strip()
            return ""

        out["title"] = meta("og:title", "twitter:title")
        out["description"] = meta("og:description", "twitter:description", "description")
        out["image_url"] = meta("og:image", "og:image:secure_url", "twitter:image")

        # Some pages ship a full recipe as schema.org JSON-LD — far better than a caption.
        for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
            raw = (script.string or "").strip()
            if raw and "ecipe" in raw:
                out["page_text"] = raw[:8000]
                break
    except Exception:
        pass
    return out


def download_image(url):
    """Returns (bytes, mime) or None."""
    if not url:
        return None
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=25)
        if r.status_code >= 400 or not r.content:
            return None
        return shrink(r.content)
    except Exception:
        return None


def shrink(raw):
    """Normalise any upload/download to a reasonably sized JPEG."""
    try:
        img = Image.open(io.BytesIO(raw))
        img = img.convert("RGB")
        img.thumbnail((MAX_PX, MAX_PX), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
        return buf.getvalue(), "image/jpeg"
    except Exception:
        return None


SYSTEM_PROMPT = """Tu transformes des publications de réseaux sociaux en fiches recette \
claires, destinées à être lues sur un téléphone par un enfant qui cuisine avec un adulte.

Réponds UNIQUEMENT avec un objet JSON valide, sans texte avant ou après, sans balises \
Markdown. Structure exacte :

{
  "title": "nom du plat, court et concret (max 45 caractères)",
  "emoji": "un seul emoji qui représente le plat",
  "servings": "ex: 4 personnes",
  "total_time": "ex: 45 min",
  "ingredients": [{"qty": "200 g", "item": "farine"}],
  "steps": ["phrase à l'impératif"],
  "notes": "astuce courte, ou chaîne vide"
}

## Langue

Écris TOUT en français : titre, ingrédients, étapes, notes. Peu importe la langue de la \
publication d'origine. Si elle est en anglais, en espagnol ou dans une autre langue, \
traduis. Utilise les noms culinaires français usuels ("raviolis", "crème épaisse", \
"cassonade", "levure chimique"), pas du mot-à-mot.

## Unités : système métrique uniquement

Ne laisse JAMAIS d'once, de livre, de cup, de pinte, de pouce ni de degré Fahrenheit dans \
la fiche. Convertis tout, puis arrondis à un nombre que l'on peut lire en cuisinant.

Poids et volumes :
- 1 oz = 28 g · 1 lb = 450 g · 1 fl oz = 30 ml · 1 pint = 475 ml · 1 quart = 950 ml
- 1 cup = 240 ml pour un liquide
- 1 cup d'un ingrédient sec se convertit en poids : farine 120 g · sucre 200 g · \
cassonade 180 g · beurre 225 g · riz 185 g · sucre glace 120 g · cacao 100 g · \
fromage râpé 100 g · pépites de chocolat 170 g · noix concassées 120 g
- 1 tablespoon = 1 c. à soupe · 1 teaspoon = 1 c. à café (garde ces deux-là en cuillères, \
c'est ce qu'on utilise en cuisine française)
- Au-delà de 1000 g écris en kg (1,2 kg), au-delà de 1000 ml écris en litres (1,5 l)

Températures et longueurs :
- Fahrenheit vers Celsius : (F − 32) ÷ 1,8, arrondi aux 5 °C les plus proches \
(350 °F = 180 °C, 375 °F = 190 °C, 425 °F = 220 °C)
- 1 inch = 2,5 cm

Arrondis comme un cuisinier, pas comme une calculatrice : 24 oz devient 680 g, pas 672 g. \
1,5 lb devient 700 g. Utilise la virgule décimale française (1,5 kg).

## Contenu

- Le titre nomme le plat, jamais l'auteur ni le compte : "Gâteau au yaourt", pas \
"La recette de Marie".
- Une étape = une action. Phrases courtes, verbes simples à l'impératif, pas de jargon. \
Indique les températures et les durées dans l'étape concernée.
- "qty" peut être vide si la publication ne donne pas de quantité. N'invente pas de \
quantités précises quand elles sont absentes : mets une quantité vide plutôt qu'un \
chiffre faux.
- Si la photo contient du texte (recette écrite sur l'image), lis-le et sers-t'en.
- Si tu ne trouves vraiment aucune recette, renvoie {"error": "aucune recette trouvée"}.
"""


def structure(text, image=None, source_url=None):
    """Ask Claude for structured recipe JSON. `image` is a (bytes, mime) tuple."""
    if not ANTHROPIC_KEY:
        raise ExtractError(
            "La clé ANTHROPIC_API_KEY n'est pas configurée sur le serveur. "
            "Ajoute-la dans les variables Railway."
        )

    content = []
    if image:
        content.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": image[1] or "image/jpeg",
                    "data": base64.b64encode(image[0]).decode("ascii"),
                },
            }
        )
    brief = ""
    if source_url:
        brief += f"Lien d'origine : {source_url}\n\n"
    brief += "Contenu de la publication :\n" + (text or "(aucun texte disponible)")
    content.append({"type": "text", "text": brief})

    payload = {
        "model": CLAUDE_MODEL,
        "max_tokens": 2000,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": content}],
    }
    try:
        r = requests.post(
            ANTHROPIC_URL,
            headers={
                "x-api-key": ANTHROPIC_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=payload,
            timeout=90,
        )
    except requests.RequestException as e:
        raise ExtractError(f"Impossible de joindre l'API Claude : {e}")

    if r.status_code >= 400:
        logging.error("Anthropic API %s: %s", r.status_code, r.text[:300])
        if r.status_code in (401, 403):
            msg = ("La clé ANTHROPIC_API_KEY est refusée. Vérifie-la dans les "
                   "variables Railway.")
        elif r.status_code == 429:
            msg = "Trop de demandes d'un coup. Attends une minute et réessaie."
        elif r.status_code >= 500:
            msg = "Le service Claude est indisponible pour le moment. Réessaie."
        else:
            msg = "La lecture de la recette a échoué. Réessaie."
        raise ExtractError(msg)

    blocks = r.json().get("content", [])
    raw = "\n".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()
    raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.MULTILINE).strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            raise ExtractError("Claude n'a pas renvoyé de recette lisible. Réessaie.")
        data = json.loads(match.group(0))

    if data.get("error"):
        raise ExtractError(
            "Aucune recette trouvée dans ce contenu. Copie-colle le texte de la recette "
            "et réessaie."
        )
    return normalise(data)


def normalise(data):
    ingredients = []
    for row in data.get("ingredients") or []:
        if isinstance(row, str):
            ingredients.append({"qty": "", "item": row.strip()})
        elif isinstance(row, dict):
            item = str(row.get("item") or row.get("name") or "").strip()
            if item:
                ingredients.append({"qty": str(row.get("qty") or "").strip(), "item": item})

    steps = [str(s).strip() for s in (data.get("steps") or []) if str(s).strip()]

    return {
        "title": (str(data.get("title") or "").strip() or "Nouvelle recette")[:120],
        "emoji": (str(data.get("emoji") or "").strip() or None),
        "servings": str(data.get("servings") or "").strip() or None,
        "total_time": str(data.get("total_time") or "").strip() or None,
        "ingredients": ingredients,
        "steps": steps,
        "notes": str(data.get("notes") or "").strip() or None,
    }


def retranslate(row):
    """Repasse une recette déjà enregistrée en français et en unités métriques."""
    lines = [f"Titre : {row.get('title') or ''}"]
    if row.get("servings"):
        lines.append(f"Pour : {row['servings']}")
    if row.get("total_time"):
        lines.append(f"Durée : {row['total_time']}")
    lines.append("Ingrédients :")
    for ing in row.get("ingredients") or []:
        lines.append(f"- {ing.get('qty', '')} {ing.get('item', '')}".rstrip())
    lines.append("Étapes :")
    for i, step in enumerate(row.get("steps") or [], 1):
        lines.append(f"{i}. {step}")
    if row.get("notes"):
        lines.append(f"Note : {row['notes']}")

    return structure("\n".join(lines), source_url=row.get("source_url"))


def retranslate(recipe):
    """Re-run an already-saved recipe through the same French + metric rules.

    For cards imported before the prompt enforced French, or pasted in by hand
    with imperial units.
    """
    lines = [f"Titre : {recipe.get('title') or ''}"]
    if recipe.get("servings"):
        lines.append(f"Pour : {recipe['servings']}")
    if recipe.get("total_time"):
        lines.append(f"Durée : {recipe['total_time']}")
    lines.append("\nIngrédients :")
    for ing in recipe.get("ingredients") or []:
        qty = (ing.get("qty") or "").strip()
        lines.append(f"- {qty} {ing.get('item', '')}".replace("-  ", "- "))
    lines.append("\nÉtapes :")
    for i, step in enumerate(recipe.get("steps") or [], 1):
        lines.append(f"{i}. {step}")
    if recipe.get("notes"):
        lines.append(f"\nNote : {recipe['notes']}")

    out = structure("\n".join(lines))
    out["emoji"] = out.get("emoji") or recipe.get("emoji")
    return out


def build_draft(url="", text="", upload=None, preloaded_image=None):
    """Main entry point. Returns (recipe_dict, image_tuple_or_None).

    `preloaded_image` is an already-shrunk (bytes, mime) tuple — used by the
    Android share target, where the screenshot arrived before we got here.
    """
    url = (url or "").strip()
    text = (text or "").strip()
    platform = detect_platform(url)
    image = preloaded_image or (shrink(upload) if upload else None)
    caption_parts = []

    if url and not platform:
        raise ExtractError("Ce lien n'a pas l'air valide. Il doit commencer par https://")

    if url:
        page = fetch_page(url)
        for key in ("title", "description", "page_text"):
            if page.get(key):
                caption_parts.append(page[key])
        if image is None:
            image = download_image(page.get("image_url"))

    if text:
        caption_parts.append(text)

    caption = "\n\n".join(caption_parts).strip()

    if not caption and image is None:
        raise ExtractError(
            "Instagram et Facebook bloquent parfois la lecture automatique. "
            "Ouvre la publication, copie la légende, colle-la ici et réessaie."
        )

    recipe = structure(caption, image=image, source_url=url or None)
    recipe["source_url"] = url or None
    recipe["source_platform"] = platform
    return recipe, image
