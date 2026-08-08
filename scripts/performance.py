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

import glob
import json
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wells import CAPS, WELLS  # noqa: E402
from publish import ROOT, graphql  # noqa: E402

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
        print(f"analytics: {e.args[0]} not set — running blind on the playbook prior", file=sys.stderr)
        return []
    try:
        return _request(url).get("value", [])
    except (urllib.error.URLError, ValueError, TimeoutError) as e:
        print(f"analytics: table unreadable ({str(e)[:80]}) — running blind", file=sys.stderr)
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

    Used only as a deterministic tiebreak between wells of equal score. Unknown
    slugs are excluded before they reach here (see rank()), but the ValueError
    branch stays: sorting must never be the thing that raises.
    """
    try:
        return WELLS.index(well)
    except ValueError:
        return len(WELLS)


def rank(stats):
    """Wells good enough to lead, best first, then everything else in prior order.

    The sample floor is the main defence against locking onto a false winner: one
    lucky post should not decide a month of content.

    Only slugs that are currently in WELLS may qualify. rollup() passes through
    whatever `well` string sits on the Azure row, so renaming or removing a slug
    in wells.py — normal maintenance — leaves historical rows carrying the old
    one. Sorting such a slug merely last is not enough: with a high rate and
    enough samples it would win the champion days, be interpolated into the
    generator prompt as a mandatory assignment, and then be rejected by
    validate.py. That is an unsatisfiable instruction, and the run either
    silently substitutes something else (making the plan a lie) or burns the
    30-minute timeout. Drop them instead, and say so on stderr so the cause is
    visible in the step log.
    """
    unknown = sorted(w for w in stats if w not in WELLS)
    if unknown:
        print(f"analytics: ignoring {len(unknown)} table slug(s) not in wells.py "
              f"({', '.join(unknown)}) — renamed or retired?", file=sys.stderr)
    qualified = [w for w in stats if w in WELLS and stats[w]["n"] >= MIN_SAMPLE]
    qualified.sort(key=lambda w: (-stats[w]["rate"], _well_rank(w)))
    return qualified + [w for w in WELLS if w not in qualified]


DAY_ORDER = tuple(sorted(CHAMPION_DAYS + CHALLENGER_DAYS + (EXPLORE_DAY,)))


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


# Verified against the live API on 2026-08-08 by introspection: Query.post
# takes `input: PostInput!`, not `id:`, and the id itself is `PostId!`, not
# `String!`. Either wrong shape fails with an HTTP 400 that publish.graphql
# turns into a RuntimeError — which ingest() swallows, so every run would
# print N "metrics unavailable" lines and return 0, indistinguishable from
# "nothing has sent yet". Do not "simplify" this back to post(id: $id).
#
# metrics is an ARRAY of typed objects, not an object of named fields. Types
# seen: reactions, comments, engagementRate, views, shares, reach. There is
# no impressions field. `metrics` itself is nullable in the schema.
POST_METRICS = """
query Post($id: PostId!) {
  post(input: {id: $id}) {
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
    """The metrics array flattened to {type: value}.

    Defensive by construction: `metrics` is nullable, and a single malformed
    entry (missing "type", or not a dict at all) must not take down the whole
    ingest run over one bad element.
    """
    return {m["type"]: m.get("value") for m in (post.get("metrics") or [])
            if isinstance(m, dict) and "type" in m}


def well_for(week, day):
    """The well a given day's spec belongs to, or None if there is no such spec."""
    path = os.path.join(ROOT, "content", week, f"{day}.json")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f).get("well")


def ingest():
    """Refresh every scheduled post's metrics into the table. Returns rows written.

    Every failure mode here degrades, never raises: a malformed receipt, a
    malformed post entry, a Buffer error, a null post, a scheduled-not-sent
    post, or a single bad row must all be skippable without aborting the rest
    of the week. The sole exception is a KeyError out of upsert_row, which
    means the Azure credentials themselves are missing — every later write
    would fail identically, so that alone stops the run instead of logging
    the same failure dozens of times.
    """
    written = 0
    for receipt in sorted(glob.glob(os.path.join(ROOT, "content", "week*", "SCHEDULED.json"))):
        week = os.path.basename(os.path.dirname(receipt))
        try:
            with open(receipt) as f:
                posts = json.load(f)["posts"]
        except (OSError, ValueError, KeyError) as e:
            print(f"analytics: cannot read {receipt} ({str(e)[:60]}) — skipping receipt", file=sys.stderr)
            continue
        for post in posts:
            try:
                day, post_id, channel, due_at = (
                    post["day"], post["postId"], post["channel"], post["dueAt"])
            except (KeyError, TypeError) as e:
                print(f"analytics: malformed post entry in {receipt} ({str(e)[:60]}) — skipping", file=sys.stderr)
                continue
            well = well_for(week, day)
            if not well:
                continue
            try:
                data = graphql(POST_METRICS, {"id": post_id})["post"]
            except (RuntimeError, KeyError, SystemExit, urllib.error.URLError,
                    TimeoutError, ValueError) as e:
                print(f"analytics: metrics unavailable for {post_id} ({str(e)[:60]})", file=sys.stderr)
                continue
            if not data:
                continue
            if data.get("status") != SENT:
                continue
            m = metrics_map(data)
            try:
                upsert_row({
                    "PartitionKey": week,
                    "RowKey": post_id,
                    "well": well,
                    "channel": channel,
                    "day": day,
                    "dueAt": due_at,
                    "reach": m.get("reach") or 0,
                    "views": m.get("views") or 0,
                    "reactions": m.get("reactions") or 0,
                    "comments": m.get("comments") or 0,
                    "shares": m.get("shares") or 0,
                    "engagementRate": m.get("engagementRate"),
                    "updatedAt": data.get("metricsUpdatedAt") or due_at,
                })
                written += 1
            except KeyError as e:
                print(f"analytics: Azure credentials missing ({str(e)[:60]}) — stopping", file=sys.stderr)
                return written
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError) as e:
                print(f"analytics: row {post_id} rejected ({str(e)[:60]}) — skipping", file=sys.stderr)
                continue
    return written


def main():
    args = set(sys.argv[1:])
    if "--ingest" in args:
        print(f"ingested {ingest()} rows", file=sys.stderr)

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
