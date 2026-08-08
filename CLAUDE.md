# Beyond Horizon — content automation

This repo renders a week of social carousels and schedules them to TikTok,
Instagram and Facebook through Buffer. Two workflows run it on a weekly cycle:

| Workflow | When | Does |
|---|---|---|
| `generate-week.yml` | Sun 03:30 UTC | Claude Code writes the next week's specs and commits them |
| `publish.yml` | Sun 05:15 UTC | Renders, uploads to Azure, schedules 21 posts in Buffer |

Each is the other's safety net: if generation fails, publish still picks up the
earliest week that has no `SCHEDULED.json` receipt; if publish fails, the specs
are already committed and the run can be repeated by hand.

## Layout

```
content/weekN/01_mon.json … 07_sun.json   the written carousels (source of truth)
content/weekN/SCHEDULED.json              receipt, written after a successful schedule
media/weekN/<day>/slide_NN.jpg            rendered output (gitignored on Azure)
renderer/                                 Remotion project, 1080x1350 stills
scripts/validate.py                       spec gates — run before committing anything
scripts/publish.py                        uploads media, schedules in Buffer
.claude/skills/                           the craft: how to write and how to render
config.json                               channels, times, media host
```

## Writing a week of content

Seven pieces, one per day, `01_mon.json` through `07_sun.json`. Use the
`beyond-horizon-carousels` skill, and read
`.claude/skills/beyond-horizon-carousels/SKILL.md` and both files in its
`references/` folder first — they carry the brand voice, the compliance limits
and the performance evidence. The format is not negotiable; it was derived from
a 268-post sample in this exact niche.

**Non-negotiables**, all enforced by `scripts/validate.py`:

- Exactly 10 slides. Buffer caps carousels at 10 images on TikTok and Instagram.
- The line items must sum **exactly** to income minus the reckoning figure.
- A rand amount in the hook slide.
- Amounts written `R6 200 p/m` — space as the thousands separator, never a comma.
- Exactly 5 hashtags; the caption must end in a real question.

**Structure**: hook → persona → 5 line items → one grouped "Everything else"
slide → reckoning → close.

**Variety across the week** matters as much as any single post. Vary income
level (skew below R40k — it performs better) and life stage. Do
not reuse a persona, city or hook that appears in any recent `content/week*/`
file. Read them before writing.

**Every spec needs a `well`** — one of the ten slugs in `scripts/wells.py`. It is
how a post's performance is attributed to a topic, and `validate.py` rejects
anything unknown. When the generator assigns you a well for a day, write in that
well; vary persona, city, income and hook instead.

**Always include** at least one number the persona is not proud of, and the
lines most budget content omits — black tax, stokvel, funeral policy. They are
the strongest authenticity signals in this niche.

**Never**: tell the reader what to do with their money (that is regulated
financial advice in South Africa), present a persona as a real customer, invent
a testimonial, or claim an app feature that does not exist.

## Before committing specs

```bash
python3 scripts/validate.py content/weekN
```

It must pass with zero problems. If the arithmetic fails, fix the numbers —
never the reckoning figure alone, since the whole point is that the budget
reconciles.

## Checking what performed

During a generation run, the per-day well assignment in the prompt already
encodes what performed — it comes from `scripts/performance.py`, which reads
measured Buffer engagement. Do not separately query Buffer for angles during
generation; write within the assigned well instead.

The manual check below is for a human session, not something to run as part of
generating a week. Buffer's GraphQL API is at `https://api.buffer.com` with
`Authorization: Bearer $BUFFER_ACCESS_TOKEN`. Use `get_aggregated_post_metrics`
or query posts with `includeMetrics` to see which hooks and income bands
landed.

## Skills in this repo

| Skill | Covers |
|---|---|
| `beyond-horizon-carousels` | what to write — voice, format, compliance, the 268-post evidence base |
| `beyond-horizon-rendering` | how it gets rendered — layout, motion, brand, platform limits |

Any Claude Code session opened in this repo picks these up automatically, so the
approach travels with the code rather than living in someone's account.

## Updating a workflow or skill from a remote session

Remote tools cannot write to `.github/workflows/` or `.claude/` — both are
protected. Stage the files under `ci/` instead (gitignored), then copy them
across from a shell:

```bash
cp ci/generate-week.yml .github/workflows/generate-week.yml
cp -R ci/skills/. .claude/skills/
```

## Gotchas that have already bitten

- Buffer's endpoint for API keys is `api.buffer.com`, **not** `graph.buffer.com`
  (that one exists but rejects API keys).
- Instagram multi-image posts use `type: "post"`, not `"carousel"` — the schema
  lists `carousel` but it is rejected in practice.
- Buffer re-fetches media at publish time and its fetcher intermittently fails
  on cold blobs. `publish.py` retries four times; do not remove that.
- Never hardcode a browser path in the renderer. It must fall back to the one
  Remotion downloads, or CI breaks.
