# Content Learning Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the weekly content generator pick topics from measured Buffer engagement instead of guessing, while always testing one new topic.

**Architecture:** A new stdlib-only `scripts/performance.py` ingests Buffer post metrics into a private Azure Table, rolls them up by content well, and emits a deterministic 4/2/1 day-to-well plan. `generate-week.yml` runs it before Claude and passes the plan into the prompt. Claude writes specs within assigned topics; it does not choose the mix.

**Tech Stack:** Python 3.11 stdlib only (`urllib`, `json`, `hmac`, `datetime`), Azure Table Storage REST API, Buffer GraphQL API, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-08-content-learning-loop-design.md`

## Global Constraints

- **No new Python dependencies.** Stdlib only. No `azure-data-tables`, no `requests`. The existing scripts use `urllib.request` and `json`.
- **No performance data in the repo.** Metrics live only in the Azure Table. Never write them to `content/`, never commit them.
- **Analytics never blocks generation.** Any failure — missing SAS, unreachable Table, Buffer error — logs plainly and returns the cold-start plan. Exit code stays 0.
- **The ten canonical wells**, verbatim, are the only legal values: `salary-breakdown`, `household-budget`, `comparison`, `debt-journey`, `one-off-event`, `cost-of-ownership`, `money-leak`, `month-in-review`, `ranking-listicle`, `product-led`.
- **Editorial caps:** `ranking-listicle` at most 1 day/week; `product-led` at most 2 days/week. Applied regardless of rank.
- **Minimum sample:** a well needs ≥3 posts with usable metrics to be champion or challenger.
- **Only `status == "sent"` posts are ingested.** Buffer returns zeroed metrics for merely-scheduled posts, shaped identically to real results. Ingesting them scores every well at 0%.
- **Engagement rate is Buffer's own `engagementRate`** (a percentage), falling back to `100 * (reactions + comments + shares) / reach` only where Buffer omits it. There is no `impressions` field in Buffer's API.
- **Playbook prior order** for cold start, verbatim: `salary-breakdown`, `household-budget`, `comparison`, `debt-journey`, `one-off-event`, `cost-of-ownership`, `money-leak`, `month-in-review`, `ranking-listicle`, `product-led`.
- **Secrets are never printed.** `AZURE_TABLE_SAS` must not appear in logs or in any printed URL.
- **Commit style:** Conventional Commits per `.claude/skills/conventional-commits/SKILL.md`. Scopes available: `publish`, `validate`, `renderer`, `content`, `media`, `config`, `ci`. This work introduces `performance` as a new scope.

## File Structure

| File | Responsibility |
|---|---|
| `scripts/wells.py` | **Create.** The canonical well list and prior order. Single source of truth imported by everything else. |
| `scripts/validate.py` | **Modify.** Add the `well` field check to `check()`. |
| `scripts/performance.py` | **Create.** Buffer ingest, Azure Table I/O, rollup, planner, `--show`. |
| `scripts/test_performance.py` | **Create.** Assert-based tests, HTTP stubbed, runs offline. |
| `content/week1/*.json`, `content/week2/*.json` | **Modify.** Backfill the `well` field on 14 specs. |
| `.github/workflows/generate-week.yml` | **Modify.** Run the planner, pass its output into the prompt. |
| `CLAUDE.md` | **Modify.** Document the `well` field so hand-written specs include it. |

`wells.py` is separate from `performance.py` so `validate.py` can import the list without pulling in the Azure and Buffer machinery — `validate.py` runs in the publish workflow where no analytics credentials exist.

---

### Task 1: The canonical well list

**Files:**
- Create: `scripts/wells.py`
- Test: `scripts/test_performance.py`

**Interfaces:**
- Consumes: nothing
- Produces: `WELLS` (tuple of 10 strings, prior order), `is_well(value) -> bool`

- [ ] **Step 1: Write the failing test**

Create `scripts/test_performance.py`:

```python
#!/usr/bin/env python3
"""Assert-based tests. No framework, no network. Run: python3 scripts/test_performance.py"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from wells import WELLS, is_well


def test_wells():
    assert len(WELLS) == 10, f"expected 10 wells, got {len(WELLS)}"
    assert WELLS[0] == "salary-breakdown", "prior order must start with salary-breakdown"
    assert WELLS[1] == "household-budget", "prior order must have household-budget second"
    assert len(set(WELLS)) == 10, "wells must be unique"
    assert is_well("money-leak")
    assert not is_well("Money Leak")
    assert not is_well("nonsense")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok  {name}")
    print("\nall tests pass")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 scripts/test_performance.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'wells'`

- [ ] **Step 3: Write minimal implementation**

Create `scripts/wells.py`:

```python
#!/usr/bin/env python3
"""The ten content wells, in the playbook's prior-performance order.

Single source of truth. `validate.py` rejects anything not in this tuple, so a
typo cannot silently create an eleventh well and fragment the metrics.

Order matters: it is the cold-start ranking used before any real data exists.
Taken from .claude/skills/beyond-horizon-carousels/references/format-playbook.md
"""

WELLS = (
    "salary-breakdown",
    "household-budget",
    "comparison",
    "debt-journey",
    "one-off-event",
    "cost-of-ownership",
    "money-leak",
    "month-in-review",
    "ranking-listicle",
    "product-led",
)

# Domain knowledge the engagement metric cannot see. Rankings pull reach from an
# audience that is not there to budget; product-led reads as an ad past roughly
# one post in five. Either can top an engagement ranking while working against
# audience growth, so the planner caps them regardless of rank.
CAPS = {"ranking-listicle": 1, "product-led": 2}


def is_well(value):
    return value in WELLS
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 scripts/test_performance.py`
Expected: `ok  test_wells` then `all tests pass`

- [ ] **Step 5: Commit**

```bash
git add scripts/wells.py scripts/test_performance.py
git commit -m "feat(performance): add the canonical content well list

Single source of truth for the ten wells and their prior order, kept apart
from the analytics code so validate.py can import it without needing Azure
or Buffer credentials."
```

---

### Task 2: Validate the `well` field

**Files:**
- Modify: `scripts/validate.py` (imports at line 9-13, `check()` at line 28)
- Test: `scripts/test_performance.py`

**Interfaces:**
- Consumes: `WELLS`, `is_well` from Task 1
- Produces: `check()` now returns a problem string when `well` is missing or unknown

- [ ] **Step 1: Write the failing test**

Append to `scripts/test_performance.py`, above the `__main__` block:

```python
from validate import check


def _spec(**over):
    """A minimal spec that passes every existing gate, so tests isolate one rule."""
    slides = [{"kind": "hook", "title": "How I spend my R26 500 p/m salary"},
              {"kind": "persona"}]
    slides += [{"kind": "line", "amount": "R1 000"} for _ in range(6)]
    slides += [{"kind": "reckoning", "amount": "R500"}, {"kind": "cta"}]
    spec = {"income": 6500, "well": "salary-breakdown", "slides": slides,
            "caption": "What would you cut?",
            "hashtags": ["#a", "#b", "#c", "#d", "#e"]}
    spec.update(over)
    return spec


def test_well_required():
    clean = _spec()
    assert check(clean) == [], f"baseline spec should pass, got {check(clean)}"

    missing = _spec()
    del missing["well"]
    assert any("well" in p for p in check(missing)), "missing well must be reported"

    unknown = _spec(well="salary breakdown")
    assert any("well" in p for p in check(unknown)), "unknown well must be reported"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 scripts/test_performance.py`
Expected: FAIL on `test_well_required` with `AssertionError: missing well must be reported`

- [ ] **Step 3: Write minimal implementation**

In `scripts/validate.py`, add to the imports after line 13:

```python
from wells import WELLS, is_well
```

Add `sys.path` setup directly under the imports so the module resolves when
`validate.py` is run from the repo root:

```python
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
```

In `check()`, immediately after the `if not slides:` early return, add:

```python
    well = spec.get("well")
    if not well:
        p.append(f"{name}: no 'well' — set one of {', '.join(WELLS)}")
    elif not is_well(well):
        p.append(f"{name}: unknown well '{well}' — must be one of {', '.join(WELLS)}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 scripts/test_performance.py`
Expected: `ok  test_well_required`, `ok  test_wells`, `all tests pass`

- [ ] **Step 5: Commit**

```bash
git add scripts/validate.py scripts/test_performance.py
git commit -m "feat(validate): require a known content well on every spec

Without an attributable topic no metric can be tied back to anything, so the
learning loop rests on this field being present and spelled correctly."
```

---

### Task 3: Backfill `well` on weeks 1 and 2

**Files:**
- Modify: `content/week1/01_mon.json` … `content/week1/07_sun.json`, `content/week2/01_mon.json` … `content/week2/07_sun.json` (14 files)

**Interfaces:**
- Consumes: `WELLS` from Task 1, the validator rule from Task 2
- Produces: 14 specs that pass validation and carry attributable topics

**Why this is a task and not a footnote:** these 14 posts are the first real data the loop will ever see. Classifying them wrongly poisons the first several weeks of ranking.

- [ ] **Step 1: Verify the specs currently fail validation**

Run: `python3 scripts/validate.py content/week1`
Expected: FAIL, 7 problems, each `no 'well'`

- [ ] **Step 2: Read each spec and classify it**

For each of the 14 files, read the hook title and persona slide, then pick the well it actually belongs to. Guidance:

| If the post is… | Well |
|---|---|
| One person's salary split across categories | `salary-breakdown` |
| A couple's or family's combined income | `household-budget` |
| Two personas set side by side | `comparison` |
| Paying down a named debt total | `debt-journey` |
| A wedding, funeral, matric dance, first car | `one-off-event` |
| The true monthly cost of owning one thing | `cost-of-ownership` |
| Named wasted spend — subscriptions, fees | `money-leak` |
| Budget vs actual for a month just ended | `month-in-review` |
| A ranked list of suburbs, jobs, prices | `ranking-listicle` |
| A walkthrough of the app itself | `product-led` |

Add the field near the top of each spec, beside `income`:

```json
  "income": 26500,
  "well": "salary-breakdown",
```

- [ ] **Step 3: Verify both weeks pass**

Run: `python3 scripts/validate.py content/week1 && python3 scripts/validate.py content/week2`
Expected: `all 7 specs pass` twice

- [ ] **Step 4: Report the spread**

Run:

```bash
python3 -c "
import glob, json, collections
c = collections.Counter(json.load(open(f))['well']
                        for f in glob.glob('content/week*/[0-9]*.json'))
for well, n in c.most_common():
    print(f'{n:>3}  {well}')
print(f'\n{len(c)} distinct wells across {sum(c.values())} posts')"
```

Expected: a printed distribution. **If fewer than 3 distinct wells appear, stop and report it** — the spec flags this as an open question, because early champions would then be decided by a field too thin to be meaningful, and the prior should stay in charge longer than planned.

- [ ] **Step 5: Commit**

```bash
git add content/week1 content/week2
git commit -m "content: backfill the well field on weeks 1 and 2

These 14 posts are the first data the learning loop sees, so their topic
attribution decides the first several weeks of ranking."
```

---

### Task 4: Azure Table client

**Files:**
- Create: `scripts/performance.py`
- Test: `scripts/test_performance.py`

**Interfaces:**
- Consumes: nothing from earlier tasks
- Produces: `table_url()`, `upsert_row(entity)`, `fetch_rows()`. `fetch_rows()` returns `list[dict]`; returns `[]` and logs when credentials are absent or the service errors.

- [ ] **Step 1: Write the failing test**

Append to `scripts/test_performance.py`, above the `__main__` block:

```python
import performance


def test_fetch_rows_without_credentials_is_blind_not_fatal():
    """Analytics must never block generation — no SAS means empty, not an exception."""
    saved = {k: os.environ.pop(k, None) for k in ("AZURE_ACCOUNT", "AZURE_TABLE_SAS")}
    try:
        assert performance.fetch_rows() == []
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v


def test_table_url_excludes_the_sas():
    """The SAS must never end up in a printed or logged URL."""
    os.environ["AZURE_ACCOUNT"] = "acct"
    os.environ["AZURE_TABLE_SAS"] = "sig=SECRETVALUE"
    try:
        url = performance.table_url()
        assert "SECRETVALUE" not in url, "table_url() must not embed the SAS"
        assert url.startswith("https://acct.table.core.windows.net/postmetrics")
    finally:
        del os.environ["AZURE_ACCOUNT"], os.environ["AZURE_TABLE_SAS"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 scripts/test_performance.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'performance'`

- [ ] **Step 3: Write minimal implementation**

Create `scripts/performance.py`:

```python
#!/usr/bin/env python3
"""Rank content wells by measured Buffer engagement and plan the next week.

Metrics live in a private Azure Table, never in this repo — they may contain
sensitive information, and the images container cannot hold them because it is
anonymously public by necessity (Buffer fetches media with no credentials).

Nothing here may block content generation. Every failure path degrades to the
playbook prior and exits 0.

  python3 scripts/performance.py --show      print the current ranking
  python3 scripts/performance.py --plan      print next week's day -> well plan
  python3 scripts/performance.py --ingest    refresh metrics from Buffer
"""

import json
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wells import CAPS, WELLS  # noqa: E402

TABLE = "postmetrics"


def table_url():
    """Base URL with no SAS attached — safe to print. Callers add auth separately."""
    account = os.environ["AZURE_ACCOUNT"]
    return f"https://{account}.table.core.windows.net/{TABLE}"


def _sas():
    return os.environ["AZURE_TABLE_SAS"].lstrip("?")


def _request(url, method="GET", body=None):
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Accept", "application/json;odata=nometadata")
    req.add_header("x-ms-version", "2019-02-02")
    if body is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read()
    return json.loads(raw) if raw else {}


def fetch_rows():
    """Every stored post row. [] when blind — missing credentials or a bad service."""
    try:
        url = f"{table_url()}()?{_sas()}"
    except KeyError as e:
        print(f"analytics: {e.args[0]} not set — running blind on the playbook prior")
        return []
    try:
        return _request(url).get("value", [])
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError) as e:
        print(f"analytics: table unreadable ({str(e)[:80]}) — running blind")
        return []


def upsert_row(entity):
    """Insert-or-merge keyed on PartitionKey/RowKey, so re-runs refresh not duplicate."""
    pk, rk = entity["PartitionKey"], entity["RowKey"]
    url = f"{table_url()}(PartitionKey='{pk}',RowKey='{rk}')?{_sas()}"
    _request(url, method="MERGE", body=json.dumps(entity).encode())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 scripts/test_performance.py`
Expected: `ok  test_fetch_rows_without_credentials_is_blind_not_fatal`, `ok  test_table_url_excludes_the_sas`, `all tests pass`

- [ ] **Step 5: Commit**

```bash
git add scripts/performance.py scripts/test_performance.py
git commit -m "feat(performance): add the Azure Table client

Stdlib REST rather than azure-data-tables — two HTTP verbs do not justify the
SDK. Missing credentials degrade to blind rather than raising, because
analytics must never block content generation."
```

---

### Task 5: Rollup by well

**Files:**
- Modify: `scripts/performance.py`
- Test: `scripts/test_performance.py`

**Interfaces:**
- Consumes: `fetch_rows()` from Task 4
- Produces: `engagement_rate(row) -> float | None`, `rollup(rows) -> dict[str, dict]` where each value is `{"rate": float, "n": int, "last": str}`

- [ ] **Step 1: Write the failing test**

Append to `scripts/test_performance.py`:

```python
def _row(well, reach, reactions=0, comments=0, shares=0, rate=None,
         updated="2026-08-20"):
    row = {"PartitionKey": "week1", "RowKey": f"{well}{reach}{reactions}",
           "well": well, "reach": reach, "reactions": reactions,
           "comments": comments, "shares": shares, "updatedAt": updated}
    if rate is not None:
        row["engagementRate"] = rate
    return row


def test_engagement_rate_prefers_buffers_own():
    """Buffer computes this per platform; ours is only a fallback."""
    assert performance.engagement_rate(_row("money-leak", 100, 5, rate=7.5)) == 7.5


def test_engagement_rate_falls_back_to_computed():
    # (5 + 3 + 2) / 100 = 10%
    assert performance.engagement_rate(_row("money-leak", 100, 5, 3, 2)) == 10.0
    assert performance.engagement_rate(_row("money-leak", 0, 5)) is None, \
        "zero reach has no rate"
    assert performance.engagement_rate({"well": "money-leak"}) is None, \
        "absent metrics have no rate"


def test_rollup_excludes_unusable_posts():
    rows = [_row("money-leak", 100, 10),      # 10.0
            _row("money-leak", 100, 20),      # 20.0
            _row("money-leak", 0, 999)]       # no rate, must not count
    out = performance.rollup(rows)
    assert out["money-leak"]["n"] == 2, "zero-reach post must not count toward n"
    assert abs(out["money-leak"]["rate"] - 15.0) < 1e-9, \
        f"mean should be 15.0, got {out['money-leak']['rate']}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 scripts/test_performance.py`
Expected: FAIL with `AttributeError: module 'performance' has no attribute 'engagement_rate'`

- [ ] **Step 3: Write minimal implementation**

Append to `scripts/performance.py`:

```python
def engagement_rate(row):
    """Percentage. None when the post cannot be scored.

    Buffer computes engagementRate itself, normalised per platform, so prefer
    theirs — a local engaged/reach uses a denominator meaning something different
    on each channel. Fall back to computing it only where Buffer omits it.

    A post whose numbers have not landed yet must not drag its well's average
    toward zero, so 'unscoreable' and 'scored zero' stay distinct.
    """
    own = row.get("engagementRate")
    if own is not None:
        return float(own)
    reach = row.get("reach") or 0
    if reach <= 0:
        return None
    engaged = (row.get("reactions") or 0) + (row.get("comments") or 0) + (row.get("shares") or 0)
    return 100.0 * engaged / reach


def rollup(rows):
    """well -> {rate: mean engagement, n: scoreable posts, last: newest updatedAt}."""
    acc = {}
    for row in rows:
        well = row.get("well")
        if not well:
            continue
        slot = acc.setdefault(well, {"rates": [], "last": ""})
        slot["last"] = max(slot["last"], row.get("updatedAt") or "")
        rate = engagement_rate(row)
        if rate is not None:
            slot["rates"].append(rate)
    return {w: {"rate": sum(s["rates"]) / len(s["rates"]) if s["rates"] else 0.0,
                "n": len(s["rates"]), "last": s["last"]}
            for w, s in acc.items()}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 scripts/test_performance.py`
Expected: `ok  test_engagement_rate`, `ok  test_rollup_excludes_unusable_posts`, `all tests pass`

- [ ] **Step 5: Commit**

```bash
git add scripts/performance.py scripts/test_performance.py
git commit -m "feat(performance): roll post metrics up by well

Engagement rate is scale-free so channels stay comparable. Posts whose metrics
have not landed are stored but excluded from the mean, so a fresh post cannot
drag its well down."
```

---

### Task 6: The planner

**Files:**
- Modify: `scripts/performance.py`
- Test: `scripts/test_performance.py`

**Interfaces:**
- Consumes: `rollup()` from Task 5, `WELLS` and `CAPS` from Task 1
- Produces: `rank(stats) -> list[str]`, `plan_week(stats) -> dict[str, str]` mapping the seven day names `01_mon`…`07_sun` to well slugs

**Allocation:** `01_mon`, `02_tue`, `04_thu`, `06_sat` → champion. `03_wed`, `05_fri` → challenger. `07_sun` → explore.

- [ ] **Step 1: Write the failing test**

Append to `scripts/test_performance.py`:

```python
DAYS = ["01_mon", "02_tue", "03_wed", "04_thu", "05_fri", "06_sat", "07_sun"]


def test_cold_start_uses_the_prior():
    plan = performance.plan_week({})
    assert list(plan) == DAYS, f"plan must cover all seven days, got {list(plan)}"
    assert plan["01_mon"] == "salary-breakdown", "cold-start champion is the prior's first"
    assert plan["03_wed"] == "household-budget", "cold-start challenger is the prior's second"
    assert plan["07_sun"] not in ("salary-breakdown", "household-budget"), \
        "the explore slot must differ from champion and challenger"


def test_minimum_sample_blocks_a_lucky_well():
    stats = {"money-leak": {"rate": 0.9, "n": 2, "last": "2026-08-20"},
             "comparison": {"rate": 0.1, "n": 5, "last": "2026-08-20"}}
    plan = performance.plan_week(stats)
    assert plan["01_mon"] == "comparison", \
        "a 2-post well must not be champion however good its rate"


def test_champion_is_the_best_qualifying_well():
    stats = {"money-leak": {"rate": 0.5, "n": 4, "last": "2026-08-20"},
             "comparison": {"rate": 0.2, "n": 5, "last": "2026-08-20"}}
    plan = performance.plan_week(stats)
    assert plan["01_mon"] == "money-leak"
    assert plan["03_wed"] == "comparison"


def test_explore_slot_prefers_untried_then_least_recently_used():
    tried = {w: {"rate": 0.1, "n": 5, "last": "2026-08-20"} for w in WELLS[:9]}
    assert performance.plan_week(tried)["07_sun"] == WELLS[9], \
        "the one untried well must take the explore slot"

    all_tried = {w: {"rate": 0.1, "n": 5, "last": f"2026-08-{10 + i:02d}"}
                 for i, w in enumerate(WELLS)}
    chosen = performance.plan_week(all_tried)["07_sun"]
    assert chosen == WELLS[0], \
        f"with everything tried, the oldest should explore, got {chosen}"


def test_ranking_listicle_capped_at_one_day():
    stats = {"ranking-listicle": {"rate": 0.9, "n": 9, "last": "2026-08-20"},
             "comparison": {"rate": 0.2, "n": 5, "last": "2026-08-20"}}
    plan = performance.plan_week(stats)
    used = list(plan.values()).count("ranking-listicle")
    assert used <= 1, f"ranking-listicle capped at 1 day, got {used}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 scripts/test_performance.py`
Expected: FAIL with `AttributeError: module 'performance' has no attribute 'plan_week'`

- [ ] **Step 3: Write minimal implementation**

Append to `scripts/performance.py`:

```python
MIN_SAMPLE = 3
CHAMPION_DAYS = ("01_mon", "02_tue", "04_thu", "06_sat")
CHALLENGER_DAYS = ("03_wed", "05_fri")
EXPLORE_DAY = "07_sun"


def rank(stats):
    """Wells good enough to lead, best first, then everything else in prior order.

    The sample floor is the main defence against locking onto a false winner: one
    lucky post should not decide a month of content.
    """
    qualified = [w for w in stats if stats[w]["n"] >= MIN_SAMPLE]
    qualified.sort(key=lambda w: (-stats[w]["rate"], WELLS.index(w)))
    return qualified + [w for w in WELLS if w not in qualified]


DAY_ORDER = ("01_mon", "02_tue", "03_wed", "04_thu", "05_fri", "06_sat", "07_sun")


def _first_fitting(order, days_needed, exclude):
    """Best-ranked well that can legally fill a slot needing `days_needed` days.

    A well capped below the slot size simply cannot hold it — ranking-listicle
    (cap 1) can never be champion or challenger however well it scores. That is
    the cap doing its job, not a special case.
    """
    for well in order:
        if well in exclude:
            continue
        if CAPS.get(well, 7) >= days_needed:
            return well
    return WELLS[0]


def plan_week(stats):
    """day -> well for the seven days, in calendar order, honouring the caps."""
    order = rank(stats)
    champion = _first_fitting(order, len(CHAMPION_DAYS), set())
    challenger = _first_fitting(order, len(CHALLENGER_DAYS), {champion})

    untried = [w for w in WELLS if w not in stats]
    if untried:
        explore = untried[0]
    else:
        explore = min(WELLS, key=lambda w: (stats[w]["last"], WELLS.index(w)))

    slots = {EXPLORE_DAY: explore}
    slots.update({d: champion for d in CHAMPION_DAYS})
    slots.update({d: challenger for d in CHALLENGER_DAYS})
    return {day: slots[day] for day in DAY_ORDER}
```

The plan comes back in calendar order because the generator prompt lists days Monday-first.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 scripts/test_performance.py`
Expected: five new `ok  test_…` lines, `all tests pass`

- [ ] **Step 5: Commit**

```bash
git add scripts/performance.py scripts/test_performance.py
git commit -m "feat(performance): plan the week 4/2/1 with editorial caps

Champion four days, challenger two, one untried well to keep exploring. The
sample floor stops one lucky post deciding a month, and the caps stop the
metric selecting rankings or product-led content that grows the wrong audience."
```

---

### Task 7: Buffer ingest

**Files:**
- Modify: `scripts/performance.py`
- Test: `scripts/test_performance.py`

**Interfaces:**
- Consumes: `upsert_row()` from Task 4
- Produces: `well_for(week, day) -> str | None`, `ingest() -> int` returning rows written

- [ ] **Step 1: Write the failing test**

Append to `scripts/test_performance.py`:

```python
def test_well_for_reads_the_spec():
    assert performance.well_for("week1", "01_mon") is not None, \
        "week1/01_mon.json must carry a well after the backfill"
    assert performance.well_for("week1", "99_xxx") is None, \
        "a missing spec yields None rather than raising"


def test_ingest_without_credentials_is_blind_not_fatal():
    saved = {k: os.environ.pop(k, None)
             for k in ("BUFFER_ACCESS_TOKEN", "AZURE_ACCOUNT", "AZURE_TABLE_SAS")}
    try:
        assert performance.ingest() == 0
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 scripts/test_performance.py`
Expected: FAIL with `AttributeError: module 'performance' has no attribute 'well_for'`

- [ ] **Step 3: Write minimal implementation**

Append to `scripts/performance.py`. Reuse `publish.py`'s request helper rather than writing a second one:

```python
import glob  # add to the imports at the top of the file

from publish import ROOT, graphql  # noqa: E402  add beside the wells import

# Verified against the live API on 2026-08-08: metrics is an ARRAY of typed
# objects, not an object of named fields. Types seen: reactions, comments,
# engagementRate, views, shares, reach. There is no impressions field.
POST_METRICS = """
query Post($id: String!) {
  post(id: $id) {
    id
    status
    metricsUpdatedAt
    metrics { type value unit }
  }
}
"""

# Buffer returns a full array of zeros for merely-scheduled posts, with
# metricsUpdatedAt populated — shaped identically to a real result. Ingesting
# those would score every scheduled post at 0% and make every well look dead.
SENT = "sent"


def metrics_map(post):
    """The metrics array flattened to {type: value}."""
    return {m["type"]: m["value"] for m in (post.get("metrics") or [])}


def well_for(week, day):
    """The well a given day's spec belongs to, or None if there is no such spec."""
    path = os.path.join(ROOT, "content", week, f"{day}.json")
    if not os.path.exists(path):
        return None
    return json.load(open(path)).get("well")


def ingest():
    """Refresh every scheduled post's metrics into the table. Returns rows written."""
    written = 0
    for receipt in sorted(glob.glob(os.path.join(ROOT, "content", "week*", "SCHEDULED.json"))):
        week = os.path.basename(os.path.dirname(receipt))
        for post in json.load(open(receipt))["posts"]:
            well = well_for(week, post["day"])
            if not well:
                continue
            try:
                data = graphql(POST_METRICS, {"id": post["postId"]})["post"]
            except (RuntimeError, KeyError, SystemExit, urllib.error.URLError) as e:
                print(f"analytics: metrics unavailable for {post['postId']} ({str(e)[:60]})")
                continue
            if data.get("status") != SENT:
                continue
            m = metrics_map(data)
            try:
                upsert_row({
                    "PartitionKey": week,
                    "RowKey": post["postId"],
                    "well": well,
                    "channel": post["channel"],
                    "day": post["day"],
                    "dueAt": post["dueAt"],
                    "reach": m.get("reach") or 0,
                    "views": m.get("views") or 0,
                    "reactions": m.get("reactions") or 0,
                    "comments": m.get("comments") or 0,
                    "shares": m.get("shares") or 0,
                    "engagementRate": m.get("engagementRate"),
                    "updatedAt": data.get("metricsUpdatedAt") or post["dueAt"],
                })
                written += 1
            except (KeyError, urllib.error.URLError, urllib.error.HTTPError) as e:
                print(f"analytics: cannot write row ({str(e)[:60]}) — running blind")
                return written
    return written
```

The metrics shape above was verified against the live API on 2026-08-08 — do not "simplify" `metrics { type value unit }` back into named fields, and do not drop the `status != SENT` guard. Both were corrected from an earlier wrong guess in this plan.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 scripts/test_performance.py`
Expected: `ok  test_well_for_reads_the_spec`, `ok  test_ingest_without_credentials_is_blind_not_fatal`, `all tests pass`

- [ ] **Step 5: Commit**

```bash
git add scripts/performance.py scripts/test_performance.py
git commit -m "feat(performance): ingest Buffer metrics into the table

Joins each scheduled post back to its spec's well via the receipts, so metrics
become attributable to a topic. Reuses publish.py's authenticated GraphQL
helper rather than growing a second one."
```

---

### Task 8: The `--show` and `--plan` entry points

**Files:**
- Modify: `scripts/performance.py`
- Test: manual

**Interfaces:**
- Consumes: everything above
- Produces: a CLI. `--plan` prints seven `day=well` lines suitable for a workflow to capture.

**Why `--show` matters:** moving the ledger out of the repo means you can no longer open a file to see what the system believes. This restores that as a one-liner.

- [ ] **Step 1: Write the implementation**

Append to `scripts/performance.py`:

```python
def main():
    args = set(sys.argv[1:])
    if "--ingest" in args:
        print(f"ingested {ingest()} rows")

    stats = rollup(fetch_rows())

    if "--show" in args or not args:
        print(f"\n{'well':<20} {'rate':>8} {'n':>4}  last")
        print("-" * 52)
        for well in rank(stats):
            s = stats.get(well, {"rate": 0.0, "n": 0, "last": "never"})
            flag = "" if s["n"] >= MIN_SAMPLE else "  (unproven)"
            print(f"{well:<20} {s['rate']:>8.3f} {s['n']:>4}  {s['last'] or 'never'}{flag}")

    if "--plan" in args:
        for day, well in plan_week(stats).items():
            print(f"{day}={well}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run both entry points with no credentials**

Run: `python3 scripts/performance.py --show`
Expected: the blind-mode notice, then all ten wells at rate `0.000`, n `0`, marked `(unproven)`

Run: `python3 scripts/performance.py --plan`
Expected: exactly seven lines, `01_mon=salary-breakdown` through `07_sun=<some third well>`

- [ ] **Step 3: Verify it exits clean**

Run: `python3 scripts/performance.py --plan >/dev/null; echo "exit=$?"`
Expected: `exit=0` — a blind run is a normal run, not a failure

- [ ] **Step 4: Commit**

```bash
git add scripts/performance.py
git commit -m "feat(performance): add the --show and --plan entry points

--show keeps 'what does the system currently believe' a one-liner now that the
ledger has moved out of the repo and into a private table."
```

---

### Task 9: Wire the planner into the generator

**Files:**
- Modify: `.github/workflows/generate-week.yml` (add a step before line 57, extend the prompt), `CLAUDE.md`

**Interfaces:**
- Consumes: `performance.py --plan` from Task 8
- Produces: a generator that writes each day within an assigned well

- [ ] **Step 1: Add the planning step**

In `.github/workflows/generate-week.yml`, immediately before the `Write the week with Claude Code` step:

```yaml
      - name: Plan the topic mix
        id: plan
        if: steps.cfg.outputs.skip != 'true'
        env:
          BUFFER_ACCESS_TOKEN: ${{ secrets.BUFFER_ACCESS_TOKEN }}
          AZURE_ACCOUNT: ${{ secrets.AZURE_ACCOUNT }}
          AZURE_TABLE_SAS: ${{ secrets.AZURE_TABLE_SAS }}
        run: |
          python3 scripts/performance.py --ingest --show
          {
            echo 'assignment<<PLAN_EOF'
            python3 scripts/performance.py --plan
            echo PLAN_EOF
          } >> "$GITHUB_OUTPUT"
```

- [ ] **Step 2: Feed the plan into the prompt**

In the `prompt:` block, replace the paragraph beginning `If BUFFER_ACCESS_TOKEN is set, query https://api.buffer.com` with:

```
            Each day has an assigned content well. Write that day's post in that
            well and no other — the assignment is measured, not a suggestion:

            ${{ steps.plan.outputs.assignment }}

            The wells are defined in
            .claude/skills/beyond-horizon-carousels/references/format-playbook.md.
            Set the matching "well" value in each spec's JSON. Four days share a
            well and two share another, so vary persona, city, income and hook
            hard within them — same topic must not mean same post.
```

- [ ] **Step 3: Document the field**

In `CLAUDE.md`, beside the existing guidance on varying persona and income, add:

```markdown
**Every spec needs a `well`** — one of the ten slugs in `scripts/wells.py`. It is
how a post's performance is attributed to a topic, and `validate.py` rejects
anything unknown. When the generator assigns you a well for a day, write in that
well; vary persona, city, income and hook instead.
```

- [ ] **Step 4: Verify the planner step runs in CI**

Push, then trigger the generator and watch the new step specifically:

```bash
git push origin main
gh workflow run generate-week.yml --ref main
RUN=$(gh run list --workflow=generate-week.yml -L 1 --json databaseId -q '.[0].databaseId')
gh run watch "$RUN" --exit-status
gh run view "$RUN" --log | grep -A12 "Plan the topic mix"
```

Expected: the ranking table, then seven `day=well` lines. With `AZURE_TABLE_SAS` not yet set this prints the blind-mode notice and the cold-start plan — that is the correct behaviour, not a failure.

Confirm the generated specs honour the assignment:

```bash
git pull --rebase origin main
python3 -c "
import glob, json, os
for f in sorted(glob.glob('content/week*/[0-9]*.json'))[-7:]:
    print(f'{os.path.basename(f):<12} {json.load(open(f))[\"well\"]}')"
```

Expected: four days sharing one well, two sharing another, one different.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/generate-week.yml CLAUDE.md
git commit -m "feat(ci): assign each day a measured content well

The generator no longer picks its own topics; the planner does, from Buffer
engagement. Claude's job narrows to writing distinct specs within assigned
wells, which is what it is actually good at."
```

---

## Self-review

**Spec coverage.** Attribution → Task 2, 3. Data model and Table client → Task 4. Rollup, missing-metric handling → Task 5. Planner, 4/2/1, sample floor, cold start, explore rotation, editorial caps → Task 6. Buffer ingest → Task 7. `--show` → Task 8. Workflow wiring, degradation-in-CI → Task 9. Testing → folded into each task per TDD. Security: no repo writes (Task 4 docstring), SAS never printed (Task 4 test), table-scoped credential (setup, outside code).

**Not covered by any task, by design:** creating the Azure table and minting the SAS. That is manual account setup, recorded in the spec's "Setup required" section and handed to the user separately.

**Known soft spot.** Task 7's `POST_METRICS` GraphQL shape is unverified — Buffer's metrics field names must be confirmed against the live schema. The task says so explicitly rather than pretending otherwise, because wrong field names yield zeros indistinguishable from real ones.

**Type consistency.** `rollup()` returns `{well: {"rate", "n", "last"}}`, consumed with those exact keys by `rank()`, `plan_week()`, and `main()`. `plan_week()` returns day→well keyed `01_mon`…`07_sun`, matching the spec filenames `well_for()` reads and the `DAYS` list in the tests.
