# Les recettes de Soph

A phone-first recipe shelf. Paste an Instagram or Facebook link, and Claude turns the post
into a clean recipe card: photo, dish name, ingredient checklist, numbered steps. Everything
lives in Postgres, so any phone with the URL sees the same shelf. No local files, no sync.

## Screens

| Screen | Route | What it does |
| --- | --- | --- |
| Shelf | `/` | Grid of photo tiles, favourites first, search once you pass 5 recipes |
| Import | `/add` | Paste a link, paste text, or upload a photo |
| Review | `/recipe/<id>/edit` | Check what Claude extracted before it's saved |
| Card | `/recipe/<id>` | Photo, two tabs (ingredients / steps), cook mode |
| Cook mode | in-page overlay | One giant step at a time, big Next button, screen stays put |

Ingredient ticks are stored in the phone's `localStorage`, so a half-ticked shopping list
survives a reload. Tapping through to the last step increments a "cooked N times" counter.

## Deploy on Railway

1. **Push this repo to GitHub** (commands at the bottom).
2. In Railway: **New Project → Deploy from GitHub repo → `KUDO-TSE/Soph-recipe`**.
3. On the project canvas: **+ New → Database → Add PostgreSQL**. Railway injects
   `DATABASE_URL` into the web service automatically — don't set it by hand.
4. Open the web service → **Variables** → add:

   | Variable | Value |
   | --- | --- |
   | `ANTHROPIC_API_KEY` | your API key from console.anthropic.com |
   | `SECRET_KEY` | any long random string (signs the session cookie) |
   | `APP_PIN` | a 4–6 digit code, or leave it out for no lock |
   | `CLAUDE_MODEL` | optional, defaults to `claude-sonnet-5` |

5. Web service → **Settings → Networking → Generate Domain**.
6. Open that domain on the phone, then **Share → Add to Home Screen**. It installs as a
   standalone app with its own icon, no browser chrome.

The `recipes` table is created on boot, so there's no migration step. `/healthz` returns
`ok` once the database answers.

## How the import actually works

```
link ──▶ fetch Open Graph tags (og:title, og:description, og:image)
     ├──▶ download the post photo, downscale to 1400px JPEG
     └──▶ send caption + photo to Claude ──▶ strict JSON ──▶ review screen ──▶ Postgres
```

The photo goes to Claude too, which matters: a lot of Instagram recipes are written *on*
the image rather than in the caption, and the vision pass reads them.

**Worth knowing before you judge the results:** Instagram and Facebook actively block
server-side scraping. Public Facebook posts and web recipe sites usually return their Open
Graph tags fine. Instagram is hit-and-miss — it often serves a login wall to datacenter IPs
like Railway's, and Reels are the worst case. So the flow is built to degrade gracefully
rather than pretend: if the fetch comes back empty, the app asks you to paste the caption,
and everything downstream works identically. Pasting a caption is two taps on a phone
(Instagram → ••• → Copy link / select caption), and that path is 100% reliable.

If you later want the automatic path to work more often, the options are an official
Instagram Graph API token (needs a Meta app and a connected professional account) or a
third-party resolver service. Both are additions to `extract.fetch_page()` and nothing else
has to change.

Recipe sites with schema.org markup (Marmiton, NYT Cooking, most food blogs) parse very
well, since `fetch_page()` picks up their JSON-LD recipe block.

## Files

```
app.py          routes, PIN gate, PWA manifest
db.py           schema + every query
extract.py      Open Graph scrape, image downscaling, Claude call
templates/      Jinja views
static/         one stylesheet, one script, app icons
tools/          regenerate the app icons
```

## Running it locally

```bash
pip install -r requirements.txt
cp .env.example .env        # fill in DATABASE_URL and ANTHROPIC_API_KEY
export $(grep -v '^#' .env | xargs)
python app.py               # http://localhost:5000
```

## Notes

- Photos are stored as `bytea` in Postgres, not on disk, so no Railway volume is needed and
  nothing breaks on redeploy. Each photo lands around 150–400 KB after downscaling.
- iPhone uploads: Safari converts HEIC to JPEG on upload in most cases. If a photo is
  silently skipped, that's an unconvertible HEIC — screenshot it and upload the screenshot.
- Unfinished imports are drafts, hidden from the shelf and deleted automatically after
  6 hours.
- `APP_PIN` is a soft lock for a family app on a public URL, not real authentication. Don't
  put anything sensitive in here.
