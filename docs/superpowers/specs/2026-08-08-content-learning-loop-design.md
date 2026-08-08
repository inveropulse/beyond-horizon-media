# Content learning loop — design

Date: 2026-08-08
Status: approved, not yet implemented

## Problem

`generate-week.yml` writes a fresh week of carousels every Sunday, but it writes
them blind. The prompt asks Claude to "let what actually performed steer this
week's angles" with no data behind it, so nothing steers anything — every week is
an independent guess. Two consequences:

- The system cannot get better. A topic that lands and a topic that flops are
  equally likely to reappear.
- Nothing records *what a post was about* in a machine-readable way, so even if
  metrics were fetched there would be nothing to attribute them to.

Goal: each week posts a deliberate mix of topics, weights toward what measurably
worked, and always tests something new — so the account improves over time
rather than repeating itself.

## Non-goals

- Rewriting the renderer, the publish path, or the spec format beyond one field.
- Optimising *within* a topic (hook phrasing, income level, city). Only topic
  selection is in scope.
- Real-time or per-post reaction. The loop runs once a week, with the generator.
- Statistical rigour beyond a sorted ranking. See "Why not a bandit" below.

## Constraints

These shape the design and are not negotiable by the implementation.

1. **No signal for roughly two weeks.** As of 2026-08-08 nothing has been sent —
   week1 starts 2026-08-10. Buffer metrics also lag up to ~24h. The first
   meaningful ranking lands around 2026-08-24. Every component must behave
   correctly against an empty dataset, and that path is the one exercised first.
2. **The images container is anonymously public.** It must be, because Buffer
   fetches media server-side with no credentials. Performance data therefore
   cannot live there.
3. **No performance data in the repo.** It may contain sensitive information.
4. **No new Python dependencies.** The existing scripts are stdlib-only
   (`urllib`, `json`). The Azure SDK is a large dependency for two HTTP verbs.

## Data model

One Azure Table, `postmetrics`, in the existing storage account, reached at
`https://<AZURE_ACCOUNT>.table.core.windows.net`. The Table service has no
anonymous access mode, so constraint 2 cannot recur here.

| Column | Type | Notes |
|---|---|---|
| `PartitionKey` | string | week folder, e.g. `week1` |
| `RowKey` | string | Buffer post ID — naturally unique, makes writes idempotent |
| `well` | string | one of the ten canonical wells below |
| `channel` | string | `tiktok` / `instagram` / `facebook` |
| `day` | string | spec basename, e.g. `01_mon` |
| `dueAt` | string | ISO 8601 |
| `reach` | int | unique people; may be absent, see "Missing metrics" |
| `views` | int | video watches; TikTok/IG only |
| `reactions` | int | |
| `comments` | int | |
| `shares` | int | |
| `engagementRate` | double | Buffer's own, as a percentage |
| `updatedAt` | string | ISO 8601, Buffer's `metricsUpdatedAt` |

**Verified against the live API, 2026-08-08.** Buffer returns `metrics` as an
array of `{type, name, value, unit}` objects, not an object of named fields, and
the available types are `reactions`, `comments`, `engagementRate`, `views`,
`shares`, `reach`. There is no `impressions` field.

Buffer computes `engagementRate` itself, normalised per platform, so we store and
rank on theirs rather than deriving our own — a locally-computed
`engaged / reach` would use a denominator that means something different on each
channel. Where Buffer omits it, fall back to
`(reactions + comments + shares) / reach`.

**No aggregate table.** Well rankings are computed in memory from these rows on
every run. At 21 posts/week that is ~1 100 rows after a year — a trivial scan,
and it removes any chance of a rollup drifting out of sync with its source.

Rows are upserted (`MERGE`) keyed on post ID, so re-running against the same week
refreshes metrics rather than duplicating them.

## The ten wells

Canonical slugs, taken from
`.claude/skills/beyond-horizon-carousels/references/format-playbook.md`, which
already ranks them by prior performance:

`salary-breakdown`, `household-budget`, `comparison`, `debt-journey`,
`one-off-event`, `cost-of-ownership`, `money-leak`, `month-in-review`,
`ranking-listicle`, `product-led`

This list is the single source of truth. `validate.py` rejects anything else, so
a typo cannot silently create an eleventh well and fragment the data.

## Components

### 1. Spec attribution

Every content spec gains a required `well` field holding one of the ten slugs.
Without it no metric can be tied back to a topic, so this is the foundation
everything else rests on.

`validate.py` gains one check: `well` is present and is a known slug. Existing
week1 and week2 specs must be backfilled — they were written before the field
existed, and their metrics are the first real data the loop will see. Backfill is
a one-off manual classification of 14 specs against the playbook.

### 2. `scripts/performance.py`

Stdlib only, mirroring the style of `publish.py`.

**Ingest.** For each `content/week*/SCHEDULED.json`, take the post IDs and ask
Buffer for their metrics via a GraphQL query against `https://api.buffer.com`,
reusing the authenticated request helper `publish.py` already has (same
`BUFFER_ACCESS_TOKEN`, same retry and 401 handling). Join each post to its well
by reading `content/<week>/<day>.json`. Upsert one row per post into
`postmetrics`.

**Roll up.** Scan all rows, group by well, and compute mean engagement rate and
sample size (count of posts with usable metrics).

**Plan.** Emit next week's day-to-well assignment (see Algorithm).

**`--show`.** Print the current well ranking as a text table. Keeps "what is the
system currently thinking" a one-line command, which is otherwise lost by moving
off a readable file in the repo.

### 3. Workflow wiring

`generate-week.yml` runs `performance.py` before the Claude step, with
`AZURE_ACCOUNT` and `AZURE_TABLE_SAS` in the environment. The computed plan is
passed into the prompt as an explicit per-day well assignment. No ledger commit
step — nothing performance-related enters the repo.

Claude's job narrows to what it is actually good at: writing seven distinct,
non-repeating specs within topics it has been assigned. It does not choose the
mix.

## Algorithm

### Weekly allocation — 4 / 2 / 1

| Day | Well |
|---|---|
| Mon, Tue, Thu, Sat | champion — highest mean engagement rate |
| Wed, Fri | challenger — second highest |
| Sun | explore slot — a new well |

### Ranking rules

- **Metric:** mean engagement rate, `(reactions + comments + shares) /
  impressions`. Scale-free, so a TikTok post and a Facebook post are comparable
  and one viral outlier does not dominate a well's average.
- **Minimum sample:** a well needs **≥3 posts with usable metrics** before it can
  be champion or challenger. Below that it is "unproven" and ranked by the
  playbook's prior order instead. This is the main defence against locking onto a
  false winner from a single lucky post.
- **Cold start:** with no qualifying wells, champion and challenger come from the
  playbook prior — `salary-breakdown`, then `household-budget`.
- **Explore slot:** prefer a well never tried. Once all ten have been tried,
  rotate to least-recently-used, so the system keeps re-testing rather than
  freezing on early winners.

### Editorial caps

Engagement rate alone can select against the actual goal. The playbook records
that `ranking-listicle` pulls big reach but "an audience that isn't there for
budgeting", and that `product-led` reads as an ad beyond about one post in five.
Both can plausibly top an engagement-rate ranking while working against audience
growth. Therefore, regardless of rank:

- `ranking-listicle` — at most 1 day per week
- `product-led` — at most 2 days per week

When a cap blocks a well from a slot, the next-ranked eligible well takes it.
These caps are domain knowledge the metric cannot see, and removing them means
trusting engagement rate as a complete proxy for audience quality, which it is
not.

### Only sent posts count

Buffer returns a full metrics array of zeros for posts that are merely
*scheduled*, with `metricsUpdatedAt` populated — indistinguishable in shape from
a real result. Ingest must therefore filter on `status == "sent"`. Without that
filter the 42 posts currently scheduled would each score 0%, and every well would
look dead. This is the single most dangerous failure mode in the design, because
it produces plausible numbers rather than an error.

### Missing metrics

A sent post with absent or zero `reach` yields no engagement rate. Such posts are
stored (so the row exists and refreshes later) but excluded from rollups and from
sample counts. A post sent yesterday whose metrics have not landed must not drag
a well's average toward zero.

### Why not a bandit

Thompson sampling over ten arms is the statistically correct answer to
explore/exploit, and it is the wrong tool at this scale. With ~21 posts a week
across three channels, the sample per well per week is a handful of posts — far
too noisy for posterior updates to beat a sorted list, and much harder to
override by hand when editorial judgement disagrees. Revisit if volume grows by
an order of magnitude.

## Degradation

Analytics must never block content generation. If `AZURE_TABLE_SAS` is unset, the
Table service is unreachable, or Buffer's metrics call fails, `performance.py`
logs plainly that it is running blind and returns the cold-start plan. The
workflow continues. A week generated from the playbook prior is a normal week,
not a failure.

## Security

- Performance data lives only in the private Table. Never in the repo, never in
  the public images container.
- `AZURE_TABLE_SAS` must be minted scoped to the `postmetrics` table only, so a
  leak cannot reach the images container. The scope of the existing `AZURE_SAS`
  has not been verified; if it turns out to be account-wide it should be
  re-minted against the images container alone, so the two credentials stay
  genuinely separate rather than nominally so.
- `content/week*/SCHEDULED.json` stays in the repo. It holds Buffer post IDs and
  due dates, no metrics, so it is not performance data. Moving it would be the
  same mechanism if that judgement changes.
- Workflow logs must not echo the SAS. Follow `publish.py`, which keeps it out of
  printed URLs.

## Testing

`scripts/test_performance.py`, asserts only, no framework, HTTP stubbed so it
runs offline with no credentials:

1. Cold start — empty dataset yields the playbook prior, not a crash.
2. Champion selection — highest qualifying mean engagement rate wins.
3. Minimum sample — a well with 2 posts and a huge rate does not become champion.
4. Explore slot — never assigns an already-tried well while untried ones remain;
   falls back to least-recently-used once all are tried.
5. Editorial caps — `ranking-listicle` never exceeds 1 day even when ranked top.
6. Rollup arithmetic — engagement rate computed correctly; zero-impression posts
   excluded from both the mean and the sample count.

## Setup required before this does anything

1. Create the `postmetrics` table in the existing storage account.
2. Mint a table-scoped SAS with read/write.
3. Add it as the `AZURE_TABLE_SAS` GitHub secret.

Until then the loop runs on the playbook prior — harmless, but no learning.

## Rollout

1. Add the `well` field, the validator rule, and backfill week1 and week2.
2. Build `performance.py` with tests, run it by hand against real data once
   metrics exist.
3. Wire it into `generate-week.yml` last, once its output has been eyeballed.

Step 3 is deliberately last: until the plan it produces looks sensible by hand,
it should not be steering live content.

## Open question

Week1 and week2 were written without topic diversity as a goal, so the first real
data may show most posts clustered in one or two wells. If the backfill shows
fewer than three wells represented, the first few "champions" will be decided by
a very thin field, and the prior may be the better guide for longer than two
weeks. Worth re-checking once the backfill is done.
