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
    except (urllib.error.URLError, ValueError, TimeoutError) as e:
        print(f"analytics: table unreadable ({str(e)[:80]}) — running blind")
        return []


def upsert_row(entity):
    """Insert-or-merge keyed on PartitionKey/RowKey, so re-runs refresh not duplicate."""
    pk, rk = entity["PartitionKey"], entity["RowKey"]
    url = f"{table_url()}(PartitionKey='{pk}',RowKey='{rk}')?{_sas()}"
    _request(url, method="MERGE", body=json.dumps(entity).encode())


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


MIN_SAMPLE = 3
CHAMPION_DAYS = ("01_mon", "02_tue", "04_thu", "06_sat")
CHALLENGER_DAYS = ("03_wed", "05_fri")
EXPLORE_DAY = "07_sun"


def _well_rank(well):
    """WELLS position, or last place for a slug that isn't one of ours.

    rollup() passes through whatever `well` string is on the Azure row with no
    validation, so a stale or hand-edited row can carry a slug WELLS has never
    heard of. That must degrade gracefully, not crash the planner — nothing here
    may block content generation.
    """
    try:
        return WELLS.index(well)
    except ValueError:
        return len(WELLS)


def rank(stats):
    """Wells good enough to lead, best first, then everything else in prior order.

    The sample floor is the main defence against locking onto a false winner: one
    lucky post should not decide a month of content.
    """
    qualified = [w for w in stats if stats[w]["n"] >= MIN_SAMPLE]
    qualified.sort(key=lambda w: (-stats[w]["rate"], _well_rank(w)))
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

    candidates = [w for w in WELLS if w not in (champion, challenger)]
    untried = [w for w in candidates if w not in stats]
    if untried:
        explore = untried[0]
    else:
        explore = min(candidates, key=lambda w: (stats[w]["last"], _well_rank(w)))

    slots = {EXPLORE_DAY: explore}
    slots.update({d: champion for d in CHAMPION_DAYS})
    slots.update({d: challenger for d in CHALLENGER_DAYS})
    return {day: slots[day] for day in DAY_ORDER}
