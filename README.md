# Beyond Horizon — content automation

Renders a week of carousels and schedules them to TikTok, Instagram and Facebook
through Buffer. Runs on GitHub Actions on a weekly cron. After setup there is no
manual step.

## Setup — one secret, about five minutes

**1. Push this repo** to `github.com/inveropulse/beyond-horizon-media`:

```bash
cd beyond-horizon-media
git init -b main
git remote add origin https://github.com/inveropulse/beyond-horizon-media.git
git add -A && git commit -m "Content automation + week 1"
git push -u origin main
```

**2. The repo must be public.** The rendered images are served from
`raw.githubusercontent.com`, and Buffer fetches them server-side with no
credentials. Everything here is publishable social content, so this is fine.

**3. Add one repository secret** — Settings → Secrets and variables → Actions →
New repository secret:

| Secret | Value |
|---|---|
| `BUFFER_ACCESS_TOKEN` | generate at https://publish.buffer.com/settings/api |

That's the only secret. Buffer channel IDs and posting times live in
`config.json`, not in secrets — they aren't sensitive.

**4. Run it.** Actions → *Render and schedule a content week* → Run workflow.
`week` = `week1`, `start` = the Monday you want it to begin (`2026-08-10`).

Tick `dry_run` the first time: it validates the specs, renders all 70 images and
prints the full posting plan without scheduling anything.

## Media hosting

`config.json` → `mediaHost` selects where images are served from:

- **`github`** (default) — images are committed to `media/<week>/` and served
  from `raw.githubusercontent.com`. Nothing to configure. Buffer fetches each
  image once at publish time, so the load is trivial.
- **`azure`** — uploads to Azure Blob Storage instead. Set `mediaHost` to
  `azure` and add `AZURE_ACCOUNT`, `AZURE_CONTAINER` and `AZURE_SAS` as secrets.
  The container's anonymous access level must be **Blob** — Buffer cannot use a
  SAS. Worth switching to once the repo gets large; roughly 7MB a week.

Either way the pipeline fetches the first image anonymously and aborts with a
clear message if it isn't publicly readable, rather than creating 21 broken posts.

## What a run does

1. **Validates** every spec — the budget must reconcile exactly against the
   reckoning figure, ≤10 slides (Buffer's carousel cap), a rand figure in the
   hook, exactly 5 hashtags, a caption ending in a question. Nothing proceeds
   until all pass.
2. **Renders** 10 JPEGs per post at 1080×1350 through Remotion.
3. **Publishes the media** — commits it (github host) or uploads it (azure),
   then proves the first image is anonymously readable.
4. **Schedules** 21 posts in Buffer: 7 days × 3 channels, one carousel each.
5. **Writes a receipt** (`content/<week>/SCHEDULED.json`) with every post ID and
   commits it, so a re-run can't double-schedule. `force` overrides.

## Posting times (SAST)

| Channel | Time |
|---|---|
| TikTok | 12:35 |
| Instagram | 17:20 |
| Facebook | 19:45 |

Same content, staggered. Edit `config.json` to change them. These are a starting
hypothesis — tune from Buffer analytics after about three weeks.

## Adding a week

Drop 7 specs into `content/week2/` named `01_mon.json` … `07_sun.json`. The
Sunday cron picks up the earliest week with no `SCHEDULED.json` receipt and
publishes it for the coming Monday. Nothing unscheduled means the run does
nothing.

Write specs with the `beyond-horizon-carousels` and `beyond-horizon-reels`
skills, then check them before committing:

```bash
python3 scripts/validate.py content/week2
```

## Buffer's free tier

7 posts per channel per week against a 10-per-channel cap. It fits while you
post once a day. A second daily piece needs Essentials.

## Constraints worth remembering

**Buffer caps carousels at 10 images** on both TikTok and Instagram. TikTok
itself allows 35. The playbook's data says 12+ slides roughly doubles median
views against 8 or fewer, so this cap has a real cost — the specs here are
written to 10 deliberately rather than truncated.

**Instagram requires 4:5 or wider.** 1080×1350 is exactly 4:5, the tallest
allowed. Don't make the canvas taller.

**TikTok accepts JPG and WebP**, not PNG. The renderer outputs JPEG.

## Local development

```bash
cd renderer && npm install
node render-carousels.mjs ../content/week1 ../media/week1

python3 scripts/publish.py --week week1 --start 2026-08-10 --dry-run
```

`PRODUCTION-SPEC.md` documents the design system, motion rules, layout grid and
acceptance checklist.
