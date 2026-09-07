"""Postgres access layer. Everything lives in the database, no local files."""

import json
import os
from contextlib import contextmanager

import psycopg2
from psycopg2.extras import Json, RealDictCursor

DATABASE_URL = os.environ.get("DATABASE_URL", "")


@contextmanager
def get_conn():
    if not DATABASE_URL:
        raise RuntimeError(
            "La base de données n'est pas connectée : la variable DATABASE_URL "
            "est absente du service."
        )
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS recipes (
    id              SERIAL PRIMARY KEY,
    title           TEXT NOT NULL DEFAULT 'Nouvelle recette',
    emoji           TEXT,
    source_url      TEXT,
    source_platform TEXT,
    servings        TEXT,
    total_time      TEXT,
    ingredients     JSONB NOT NULL DEFAULT '[]'::jsonb,
    steps           JSONB NOT NULL DEFAULT '[]'::jsonb,
    notes           TEXT,
    image_data      BYTEA,
    image_mime      TEXT,
    is_draft        BOOLEAN NOT NULL DEFAULT FALSE,
    is_favorite     BOOLEAN NOT NULL DEFAULT FALSE,
    times_cooked    INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS recipes_browse_idx
    ON recipes (is_draft, is_favorite DESC, created_at DESC);
"""

CARD_COLS = """id, title, emoji, servings, total_time, is_favorite, times_cooked,
               source_platform, (image_data IS NOT NULL) AS has_image"""


def init_db():
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(SCHEMA)


def list_recipes(search=None):
    sql = f"SELECT {CARD_COLS} FROM recipes WHERE is_draft = FALSE"
    params = []
    if search:
        sql += " AND (title ILIKE %s OR ingredients::text ILIKE %s)"
        params += [f"%{search}%", f"%{search}%"]
    sql += " ORDER BY is_favorite DESC, created_at DESC"
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def get_recipe(rid):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            f"""SELECT {CARD_COLS}, source_url, ingredients, steps, notes, is_draft
                FROM recipes WHERE id = %s""",
            (rid,),
        )
        return cur.fetchone()


def get_image(rid):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT image_data, image_mime FROM recipes WHERE id = %s", (rid,))
        return cur.fetchone()


def create_draft(data, image=None):
    """image is a (bytes, mime) tuple or None. Returns the new id."""
    image_data, image_mime = image if image else (None, None)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO recipes
                 (title, emoji, source_url, source_platform, servings, total_time,
                  ingredients, steps, notes, image_data, image_mime, is_draft)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE)
               RETURNING id""",
            (
                data.get("title") or "Nouvelle recette",
                data.get("emoji"),
                data.get("source_url"),
                data.get("source_platform"),
                data.get("servings"),
                data.get("total_time"),
                Json(data.get("ingredients") or []),
                Json(data.get("steps") or []),
                data.get("notes"),
                psycopg2.Binary(image_data) if image_data else None,
                image_mime,
            ),
        )
        return cur.fetchone()["id"]


def save_recipe(rid, data, image=None):
    """Publish an edited recipe. Only replaces the photo when a new one is given."""
    sets = [
        "title = %s",
        "emoji = %s",
        "servings = %s",
        "total_time = %s",
        "ingredients = %s",
        "steps = %s",
        "notes = %s",
        "is_draft = FALSE",
        "updated_at = now()",
    ]
    params = [
        data.get("title") or "Nouvelle recette",
        data.get("emoji"),
        data.get("servings"),
        data.get("total_time"),
        Json(data.get("ingredients") or []),
        Json(data.get("steps") or []),
        data.get("notes"),
    ]
    if image:
        sets.insert(0, "image_data = %s")
        sets.insert(1, "image_mime = %s")
        params.insert(0, psycopg2.Binary(image[0]))
        params.insert(1, image[1])
    params.append(rid)
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(f"UPDATE recipes SET {', '.join(sets)} WHERE id = %s", params)


def delete_recipe(rid):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM recipes WHERE id = %s", (rid,))


def toggle_favorite(rid):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE recipes SET is_favorite = NOT is_favorite WHERE id = %s RETURNING is_favorite",
            (rid,),
        )
        row = cur.fetchone()
        return row["is_favorite"] if row else False


def mark_cooked(rid):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE recipes SET times_cooked = times_cooked + 1 WHERE id = %s RETURNING times_cooked",
            (rid,),
        )
        row = cur.fetchone()
        return row["times_cooked"] if row else 0


def purge_stale_drafts(hours=6):
    """Imports the user never finished shouldn't clutter the shelf."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM recipes WHERE is_draft = TRUE AND created_at < now() - make_interval(hours => %s)",
            (hours,),
        )


def counts():
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT count(*) AS total,
                      coalesce(sum(times_cooked), 0) AS cooked
               FROM recipes WHERE is_draft = FALSE"""
        )
        return cur.fetchone()


def set_draft(rid, flag):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("UPDATE recipes SET is_draft = %s WHERE id = %s", (flag, rid))
