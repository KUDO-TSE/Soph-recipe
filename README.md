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
3. On the project canvas: **+ New → Database → Add PostgreSQL**.
4. Open the web service → **Variables** → add:

   | Variable | Value |
   | --- | --- |
   | `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` — typed literally, braces included |
   | `ANTHROPIC_API_KEY` | your API key from console.anthropic.com |
   | `SECRET_KEY` | any long random string (signs the session cookie) |
   | `APP_PIN` | a 4–6 digit code, or leave it out for no lock |
   | `CLAUDE_MODEL` | optional, defaults to `claude-sonnet-5` |

   Adding a Postgres service does **not** inject `DATABASE_URL` into the web service —
   only into the database service itself. You have to reference it across, and the
   `${{Postgres.DATABASE_URL}}` syntax keeps it in sync if credentials rotate. If the
   internal hostname doesn't resolve on first boot, use `${{Postgres.DATABASE_PUBLIC_URL}}`.

   The repo's app files must sit at the **repo root**, not inside a subfolder, or Railpack
   won't detect a Python app. Alternatively set **Settings → Build → Root Directory**.

5. Web service → **Settings → Networking → Generate Domain**.
6. Open that domain on the phone and install it:
   - **Android / Chrome:** a green "Installe les recettes" banner appears after a few
     seconds — tap **Installer**. Chrome only offers this over HTTPS with a registered
     service worker, both of which Railway's domain satisfies.
   - **iPhone / Safari:** iOS never offers automatic installation, so the app shows the
     manual route instead — **Partager → Sur l'écran d'accueil**.

   Either way it lands as a standalone app with its own icon and no browser chrome.

The `recipes` table is created on boot, so there's no migration step. `/healthz` returns
`ok` once the database answers.

## Sharing from Instagram (Android)

The installed app declares itself a Web Share Target, so it appears in Android's share
sheet. Two routes into it:

- **Share the link.** Instagram → ••• → Partager → *Les recettes de Soph*. Android puts the
  URL in the `text` field, which `/share` pulls out with a regex.
- **Share a screenshot.** Screenshot the post first, then share the image. This is the
  reliable route, and the one to use for Reels: it sidesteps Meta's scraping blocks entirely
  because nothing is fetched from Instagram — Claude's vision reads the recipe off the
  picture. Works on private accounts you follow, too.

`/share` stores the payload and redirects immediately with a 303 to `/recipe/<id>/lecture`,
which shows a spinner and calls `/api/extract/<id>`. The parse takes ~10 seconds, far too
long to leave a POST navigation hanging. The service worker passes non-GET requests straight
through, so it never interferes with the share POST.

Share target requires the app to be **installed** — it won't show in the share sheet from a
browser tab. iOS doesn't support this at all; there it would need an Apple Shortcut.

If the session has expired, a share bounces to the login screen and the shared content is
lost — log in and share again. That's deliberate: leaving `/share` unauthenticated would let
anyone write rows and images into your database.

## Why there's no "log in as me" option

Meta closed this deliberately. The Instagram Basic Display API — the only one that read
personal accounts — reached end-of-life in December 2024, specifically to restrict
third-party access to personal accounts. The Graph API only reads media for accounts you own
or manage. The oEmbed endpoint returns embed HTML with no caption field. So no amount of
OAuth gets you a third party's post text.

Session-cookie scraping does work technically, but it pairs your real account's cookie with
a datacenter IP making non-human requests, which is Meta's bot signature — the realistic
outcome is a lock on your personal account, and the cookie needs re-harvesting every few
weeks anyway. The screenshot route above gets you the same result with none of that. If you
ever want hands-off link parsing, a resolver service (Apify, Bright Data, ScrapingBee) is the
contained option: it's a change to `fetch_page()` and nothing downstream moves.

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

## Language and units

Every screen, button, error and empty state is in French, including messages that come back
from the server. Technical details (a database connection string, an API status code) are
tucked behind a "Détail technique" fold rather than shown to whoever is cooking.

**Recipe content is forced into French and metric**, whatever language the source post was
in. `SYSTEM_PROMPT` in `extract.py` carries the conversion table — ounces, pounds, cups,
pints, inches and °F all get converted, with per-ingredient cup weights (flour 120 g, sugar
200 g, butter 225 g…) since a cup of flour and a cup of sugar are not the same mass.
Tablespoons and teaspoons stay as `c. à soupe` / `c. à café`, which is what a French kitchen
actually uses. Rounding is deliberately cook-friendly: 24 oz becomes 680 g, not 672 g.

For cards saved before this was enforced, the edit screen has **Passer en français et en
métrique** — it sends the stored card back through the same rules and rewrites it in place.
No need to re-import from the original link.

## Offline

`static/sw.js` caches the shell, the stylesheet and every recipe photo it has served. A
recipe you've opened once stays readable in the kitchen with no signal; adding a new one
needs the network. Bump `CACHE` in that file to force clients to refresh after a redeploy.

## Notes

- Photos are stored as `bytea` in Postgres, not on disk, so no Railway volume is needed and
  nothing breaks on redeploy. Each photo lands around 150–400 KB after downscaling.
- iPhone uploads: Safari converts HEIC to JPEG on upload in most cases. If a photo is
  silently skipped, that's an unconvertible HEIC — screenshot it and upload the screenshot.
- Unfinished imports are drafts, hidden from the shelf and deleted automatically after
  6 hours.
- `APP_PIN` is a soft lock for a family app on a public URL, not real authentication. Don't
  put anything sensitive in here.
- Layout is verified down to 320px portrait. Every call to action is anchored to both screen
  edges or set to wrap, and type uses `clamp()` rather than fixed sizes, so nothing clips on
  a small phone. The `@media (max-width: 360px)` block tightens padding for iPhone SE sizes.
