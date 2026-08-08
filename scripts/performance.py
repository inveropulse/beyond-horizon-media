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
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wells import CAPS, WELLS  # noqa: E402
from publish import ROOT, graphql  # noqa: E402

TABLE = "postmetrics"

# Azure Table returns at most 1000 entities per response. At 21 posts a week
# that ceiling arrives inside the first year, so fetch_rows() follows the
# continuation headers — but never forever: a service that kept handing back a
# token would hang the generate job, and a hung job writes no content.
MAX_PAGES = 50


def _env(name):
    """A required environment value, or KeyError.

    An unset GitHub secret interpolates as the empty string rather than being
    absent, so os.environ[name] would hand back "" and the failure would surface
    much later as a malformed URL — once per row, dozens of times. That is the
    state of the very first live runs. Treat blank as missing.
    """
    value = (os.environ.get(name) or "").strip()
    if not value:
        raise KeyError(name)
    return value


def table_url():
    """Base URL with no SAS attached — safe to print. Callers add auth separately."""
    return f"https://{_env('AZURE_ACCOUNT')}.table.core.windows.net/{TABLE}"


def _sas():
    # .strip() is load-bearing: a secret pasted with a trailing newline or a
    # stray space produces http.client.InvalidURL ("URL can't contain control
    # characters"), whose message echoes the whole SAS back into the log.
    return _env("AZURE_TABLE_SAS").lstrip("?")


def _safe(e):
    """Error text with the SAS redacted and truncated — messages can echo the URL.

    http.client.InvalidURL quotes the offending path with repr(), so the SAS can
    appear backslash-escaped rather than literally; redact both forms.
    """
    text = str(e)
    try:
        sas = _sas()
    except KeyError:
        return text[:80]
    for form in (sas, repr(sas)[1:-1]):
        if form:
            text = text.replace(form, "<sas-redacted>")
    return text[:80]


def _request(url, method="GET", body=None):
    """Returns (parsed body, response headers). Headers carry the continuation."""
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Accept", "application/json;odata=nometadata")
    req.add_header("x-ms-version", "2019-02-02")
    if body is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read()
        headers = r.headers
    return (json.loads(raw) if raw else {}), headers


def fetch_rows():
    """Every stored post row. [] when blind — missing credentials or a bad service.

    `except Exception` is deliberate, not laziness. The entire contract of this
    function is "degrade to the playbook prior", so an allow-list can only ever
    be wrong: http.client.InvalidURL, for instance, is not a ValueError (it
    descends from HTTPException) and escaped the old tuple with the SAS in its
    message. Anything that goes wrong here means the same thing — run blind.
    """
    try:
        base, sas = table_url(), _sas()
    except KeyError as e:
        print(f"analytics: {e.args[0]} not set — running blind on the playbook prior", file=sys.stderr)
        return []
    rows = []
    try:
        query = ""
        for _ in range(MAX_PAGES):
            payload, headers = _request(f"{base}(){query}&{sas}" if query else f"{base}()?{sas}")
            rows.extend(payload.get("value", []))
            token = {k: headers.get(f"x-ms-continuation-{k}")
                     for k in ("NextPartitionKey", "NextRowKey")}
            token = {k: v for k, v in token.items() if v}
            if not token:
                return rows
            query = "?" + urllib.parse.urlencode(token)
        print(f"analytics: stopped following continuations after {MAX_PAGES} pages "
              f"({len(rows)} rows) — ranking on a partial table", file=sys.stderr)
        return rows
    except Exception as e:
        print(f"analytics: table unreadable ({_safe(e)}) — running blind", file=sys.stderr)
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
    """well -> {rate, n, last: newest updatedAt, due: newest dueAt}.

    `last` and `due` answer different questions and the explore rotation needs
    the second one. updatedAt is Buffer's metricsUpdatedAt, and ingest()
    re-upserts every row of every past week on every run, so it refreshes as
    Buffer refreshes its metrics — "least recently updated" therefore means
    "least recently metrics-refreshed", not "least recently posted". As those
    timestamps converge the ordering collapses and the explore slot freezes on
    one well, which is exactly what the rotation exists to prevent. dueAt is
    when the post actually went out and never moves.
    """
    acc = {}
    for row in rows:
        well = row.get("well")
        if not well:
            continue
        slot = acc.setdefault(well, {"rates": [], "last": "", "due": ""})
        slot["last"] = max(slot["last"], row.get("updatedAt") or "")
        slot["due"] = max(slot["due"], row.get("dueAt") or "")
        rate = engagement_rate(row)
        if rate is not None:
            slot["rates"].append(rate)
    return {w: {"rate": sum(s["rates"]) / len(s["rates"]) if s["rates"] else 0.0,
                "n": len(s["rates"]), "last": s["last"], "due": s["due"]}
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
    # Unreachable while `order` covers every well, but it must not become a trap:
    # a bare WELLS[0] would ignore both the exclude set and the cap being filtered
    # on, and could hand the same well two slots.
    return next((w for w in WELLS if w not in exclude), WELLS[0])


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
        # Least recently POSTED, not least recently metrics-refreshed — see
        # rollup(). `last` and the prior order stay on as tiebreaks only.
        explore = min(candidates, key=lambda w: (stats[w].get("due", ""),
                                                 stats[w].get("last", ""),
                                                 _well_rank(w)))

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
# metrics is an ARRAY of typed objects, not an object of named fields. Each
# PostMetric has five fields: description, name, type, unit, value. The type is
# a 16-value PostMetricType enum: clicks, comments, engagementRate, follows,
# impressions, likes, postCount, quotes, reach, reactions, reposts, saves,
# shares, totalTimeWatched, viewers, views. We ask for the six we rank or
# reconcile on. impressions DOES exist — it is simply not what we rank on,
# because reach (unique accounts) is the denominator engagementRate is built
# from, while impressions counts repeat views. `metrics` itself is nullable in
# the schema, and any given type may be absent for a channel that has no
# concept of it.
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
    of the week. The guards are `except Exception` rather than allow-lists
    because that claim has to hold for failures nobody enumerated — every
    wrong-SHAPE receipt ([1,2,3], {"posts": 5}, a bare 5) raises TypeError,
    which the original tuple of (OSError, ValueError, KeyError) let straight
    out.

    Two things deliberately stop the run early, because they mean every
    remaining iteration would fail identically and log the same line forty-odd
    times: a KeyError out of upsert_row (the Azure credentials are missing) and
    a Buffer 401 (publish.graphql raises SystemExit; the API key is dead).
    """
    written = 0
    for receipt in sorted(glob.glob(os.path.join(ROOT, "content", "week*", "SCHEDULED.json"))):
        week = os.path.basename(os.path.dirname(receipt))
        try:
            with open(receipt) as f:
                posts = json.load(f)["posts"]
            if not isinstance(posts, list):
                raise TypeError(f'"posts" is {type(posts).__name__}, not a list')
        except Exception as e:
            print(f"analytics: cannot read {receipt} ({str(e)[:60]}) — skipping receipt", file=sys.stderr)
            continue
        for post in posts:
            try:
                day, post_id, channel, due_at = (
                    post["day"], post["postId"], post["channel"], post["dueAt"])
            except Exception as e:
                print(f"analytics: malformed post entry in {receipt} ({str(e)[:60]}) — skipping", file=sys.stderr)
                continue
            try:
                well = well_for(week, day)
            except Exception as e:
                print(f"analytics: cannot read the {week}/{day} spec ({str(e)[:60]}) — skipping", file=sys.stderr)
                continue
            if not well:
                continue
            try:
                data = graphql(POST_METRICS, {"id": post_id})["post"]
            except SystemExit as e:
                # publish.graphql raises this only on a 401. The key is dead;
                # asking forty more times changes nothing and buries the cause.
                print(f"analytics: Buffer rejected the API key ({str(e)[:60]}) — stopping", file=sys.stderr)
                return written
            except Exception as e:
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
            except Exception as e:
                print(f"analytics: row {post_id} rejected ({_safe(e)}) — skipping", file=sys.stderr)
                continue
    return written


def main():
    """Every branch is wrapped, so "analytics never blocks generation" is a
    structural property of this file rather than something the workflow's
    `|| true` has to rescue. In particular --plan always emits seven day=well
    lines on stdout and exits 0: the workflow interpolates that output straight
    into the generator prompt after the words "the assignment is measured", and
    a blank there leaves the prompt dangling mid-sentence."""
    args = set(sys.argv[1:])
    if "--ingest" in args:
        try:
            print(f"ingested {ingest()} rows", file=sys.stderr)
        except Exception as e:
            print(f"analytics: ingest failed ({_safe(e)}) — continuing", file=sys.stderr)

    try:
        stats = rollup(fetch_rows())
    except Exception as e:
        print(f"analytics: rollup failed ({_safe(e)}) — running blind", file=sys.stderr)
        stats = {}

    if "--show" in args or not args:
        try:
            print(f"\n{'well':<20} {'rate':>8} {'n':>4}  last")
            print("-" * 52)
            for well in rank(stats):
                s = stats.get(well, {"rate": 0.0, "n": 0, "last": "never"})
                flag = "" if s["n"] >= MIN_SAMPLE else "  (unproven)"
                print(f"{well:<20} {s['rate']:>8.3f} {s['n']:>4}  {s['last'] or 'never'}{flag}")
        except Exception as e:
            print(f"analytics: cannot render the ranking ({_safe(e)})", file=sys.stderr)

    if "--plan" in args:
        try:
            plan = plan_week(stats)
        except Exception as e:
            print(f"analytics: planner failed ({_safe(e)}) — falling back to the "
                  f"playbook prior", file=sys.stderr)
            plan = plan_week({})
        for day, well in plan.items():
            print(f"{day}={well}")


if __name__ == "__main__":
    main()
