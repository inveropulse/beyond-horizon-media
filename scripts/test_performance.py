#!/usr/bin/env python3
"""Assert-based tests. No framework, no network. Run: python3 scripts/test_performance.py"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error

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


def test_fetch_rows_swallows_a_stalled_read_timeout():
    """A stalled response (TimeoutError from r.read(), not wrapped by URLError)
    must degrade to blind too — see review finding for the reproduction."""
    os.environ["AZURE_ACCOUNT"] = "acct"
    os.environ["AZURE_TABLE_SAS"] = "sig=dummy"
    original = performance._request

    def _raise(*a, **k):
        raise TimeoutError("timed out")

    performance._request = _raise
    try:
        assert performance.fetch_rows() == []
    finally:
        performance._request = original
        del os.environ["AZURE_ACCOUNT"], os.environ["AZURE_TABLE_SAS"]


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
    assert chosen == WELLS[2], \
        "the oldest well that isn't already scheduled should explore, " \
        f"got {chosen}"


def test_ranking_listicle_capped_at_one_day():
    stats = {"ranking-listicle": {"rate": 0.9, "n": 9, "last": "2026-08-20"},
             "comparison": {"rate": 0.2, "n": 5, "last": "2026-08-20"}}
    plan = performance.plan_week(stats)
    used = list(plan.values()).count("ranking-listicle")
    assert used <= 1, f"ranking-listicle capped at 1 day, got {used}"


def test_unknown_well_slug_does_not_crash():
    """rollup() passes through whatever `well` string sits on the Azure row with
    no validation, so a stale or hand-edited row can carry a slug WELLS has
    never heard of. The planner must degrade, not brick — same contract as a
    missing SAS token."""
    stats = {"totally-made-up-well": {"rate": 0.9, "n": 9, "last": "2026-08-20"},
             "comparison": {"rate": 0.2, "n": 5, "last": "2026-08-20"}}
    plan = performance.plan_week(stats)
    assert list(plan) == DAYS, f"plan must still cover all seven days, got {list(plan)}"


def test_unknown_well_slug_never_reaches_the_plan():
    """Not crashing is not enough. A retired or renamed slug still sitting on
    historical table rows can out-score everything real, and rank() used to
    merely sort it last among equals — so it took all four champion days and
    was interpolated into the generator prompt as a mandatory assignment that
    validate.py then rejects. Unsatisfiable instruction: either the run
    silently substitutes something else (the plan becomes a lie) or it burns
    the 30-minute timeout. Drop unknown slugs outright."""
    stats = {"tiktok-hacks": {"rate": 9.9, "n": 5, "last": "2026-08-20"},
             "comparison": {"rate": 0.2, "n": 5, "last": "2026-08-20"}}
    plan = performance.plan_week(stats)
    assert "tiktok-hacks" not in plan.values(), \
        f"a slug not in wells.py must never be assigned, got {plan}"
    for day, well in plan.items():
        assert well in WELLS, f"{day} assigned unknown well {well!r}"
    assert plan["01_mon"] == "comparison", \
        "the best REAL qualifying well should lead, not the prior's first"


def test_rank_excludes_unknown_slugs_entirely():
    stats = {"tiktok-hacks": {"rate": 9.9, "n": 9, "last": "2026-08-20"}}
    order = performance.rank(stats)
    assert "tiktok-hacks" not in order, f"unknown slug leaked into rank(): {order}"
    assert list(order) == list(WELLS), \
        "with no usable data the ranking is exactly the playbook prior"


def test_day_order_is_derived_from_the_slot_tuples():
    """DAY_ORDER used to be a hand-written duplicate of the three slot tuples;
    any desync gives a KeyError out of plan_week."""
    assert set(performance.DAY_ORDER) == set(
        performance.CHAMPION_DAYS + performance.CHALLENGER_DAYS
        + (performance.EXPLORE_DAY,))
    assert list(performance.DAY_ORDER) == DAYS


def test_explore_never_duplicates_champion_or_challenger_and_caps_hold():
    """Regression pin for the all-tried case: the LRU fallback used to range
    over every well including champion/challenger, which could hand one topic
    5 of 7 days and let a capped well (e.g. product-led) blow past its cap."""
    all_tried = {w: {"rate": 0.1, "n": 5, "last": f"2026-08-{10 + i:02d}"}
                 for i, w in enumerate(WELLS)}
    plan = performance.plan_week(all_tried)
    champion, challenger, explore = plan["01_mon"], plan["03_wed"], plan["07_sun"]
    assert explore != champion and explore != challenger, \
        f"explore must be a third, distinct well: champion={champion} " \
        f"challenger={challenger} explore={explore}"

    from collections import Counter
    counts = Counter(plan.values())
    for well, n in counts.items():
        cap = performance.CAPS.get(well, 7)
        assert n <= cap, f"{well} scheduled {n} days but capped at {cap}"


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


def test_post_metrics_query_uses_the_verified_shape():
    """Query.post takes `input: PostInput!` with an id of `PostId!`, not
    `id: String!` — verified against the live schema by introspection on
    2026-08-08. Regression pin so this doesn't get "simplified" back to the
    wrong, 400-ing shape."""
    assert "$id: PostId!" in performance.POST_METRICS
    assert "input: {id: $id}" in performance.POST_METRICS


def test_metrics_map_survives_malformed_entries():
    """`metrics` is nullable, and individual entries are not guaranteed to be
    well-formed dicts — one bad element must not raise KeyError through
    ingest()."""
    assert performance.metrics_map({"metrics": None}) == {}
    assert performance.metrics_map({}) == {}
    assert performance.metrics_map(
        {"metrics": [{"type": "reach", "value": 10}, {"unit": "count"}, "garbage", None]}
    ) == {"reach": 10}


class _FakeGlob:
    """Stands in for the `glob` module inside performance.ingest() so tests
    can hand it synthetic receipt paths without touching the real content/
    tree or its real (valid) SCHEDULED.json files."""

    def __init__(self, paths):
        self._paths = paths

    def glob(self, _pattern):
        return self._paths


def _with_fake_receipt(posts_value, assertion):
    """Write `posts_value` (or raw text if a str) as a lone SCHEDULED.json,
    point performance.ingest() at only that receipt, run the assertion, and
    always clean up — including env vars ingest() needs to reach the receipt
    loop at all."""
    tmpdir = tempfile.mkdtemp()
    try:
        weekdir = os.path.join(tmpdir, "week9")
        os.makedirs(weekdir)
        path = os.path.join(weekdir, "SCHEDULED.json")
        with open(path, "w") as f:
            if isinstance(posts_value, str):
                f.write(posts_value)
            else:
                json.dump(posts_value, f)

        original_glob = performance.glob
        performance.glob = _FakeGlob([path])
        try:
            assertion()
        finally:
            performance.glob = original_glob
    finally:
        shutil.rmtree(tmpdir)


def test_ingest_skips_unparseable_receipt_json():
    """A truncated or hand-edited SCHEDULED.json must not abort the whole
    ingest run — just that receipt."""
    def run():
        assert performance.ingest() == 0
    _with_fake_receipt("{not valid json", run)


def test_ingest_skips_receipt_missing_posts_key():
    def run():
        assert performance.ingest() == 0
    _with_fake_receipt({"week": "week9"}, run)


def test_ingest_skips_malformed_post_entries():
    """Posts missing "day"/"postId"/"channel"/"dueAt", or that are not dicts
    at all, must each be skipped rather than raising out of ingest()."""
    def run():
        assert performance.ingest() == 0
    _with_fake_receipt(
        {"posts": [{"day": "01_mon"}, {"postId": "abc"}, "garbage", None]}, run)


def _stub(module_attr, replacement):
    """Monkeypatch a name on the performance module and return a restorer."""
    original = getattr(performance, module_attr)
    setattr(performance, module_attr, replacement)
    return lambda: setattr(performance, module_attr, original)


def test_ingest_skips_scheduled_not_sent_posts():
    """The most dangerous failure mode in the design: Buffer returns a full,
    non-zero-looking metrics array for posts that are merely scheduled. A
    missing or mutated status guard must be caught here, not in production
    numbers."""
    os.environ["AZURE_ACCOUNT"] = "acct"
    os.environ["AZURE_TABLE_SAS"] = "sig=dummy"
    calls = []
    restore_graphql = _stub("graphql", lambda q, v: {"post": {
        "status": "scheduled",
        "metricsUpdatedAt": "2026-08-20T00:00:00Z",
        "metrics": [{"type": "reach", "value": 1000, "unit": "count"},
                    {"type": "reactions", "value": 50, "unit": "count"}],
    }})
    restore_upsert = _stub("upsert_row", lambda entity: calls.append(entity))
    try:
        performance.ingest()
        assert calls == [], f"a merely-scheduled post must never be upserted, got {calls}"
    finally:
        restore_graphql()
        restore_upsert()
        del os.environ["AZURE_ACCOUNT"], os.environ["AZURE_TABLE_SAS"]


def test_ingest_survives_post_null_response():
    """GraphQL can answer with {"post": None} for a deleted/unknown id — that
    must be skipped, not raise AttributeError out of ingest()."""
    os.environ["AZURE_ACCOUNT"] = "acct"
    os.environ["AZURE_TABLE_SAS"] = "sig=dummy"
    restore = _stub("graphql", lambda q, v: {"post": None})
    try:
        assert performance.ingest() == 0
    finally:
        restore()
        del os.environ["AZURE_ACCOUNT"], os.environ["AZURE_TABLE_SAS"]


def test_ingest_survives_a_stalled_graphql_call():
    """A read-phase timeout from graphql() (raw TimeoutError, not wrapped in
    URLError) must not escape ingest() and abort the run."""
    os.environ["AZURE_ACCOUNT"] = "acct"
    os.environ["AZURE_TABLE_SAS"] = "sig=dummy"

    def _raise(*a, **k):
        raise TimeoutError("timed out")

    restore = _stub("graphql", _raise)
    try:
        assert performance.ingest() == 0
    finally:
        restore()
        del os.environ["AZURE_ACCOUNT"], os.environ["AZURE_TABLE_SAS"]


def test_ingest_survives_buffer_rejecting_the_api_key():
    """publish.graphql raises SystemExit on a 401 — that must degrade like
    every other Buffer failure here, not tear down the whole run."""
    os.environ["AZURE_ACCOUNT"] = "acct"
    os.environ["AZURE_TABLE_SAS"] = "sig=dummy"

    def _raise(*a, **k):
        raise SystemExit("Buffer rejected the API key")

    restore = _stub("graphql", _raise)
    try:
        assert performance.ingest() == 0
    finally:
        restore()
        del os.environ["AZURE_ACCOUNT"], os.environ["AZURE_TABLE_SAS"]


def test_ingest_survives_a_non_json_graphql_body():
    """A non-JSON response body (proxy error page, truncated stream) surfaces
    as ValueError from json.loads inside publish.graphql — that must degrade
    too, not escape."""
    os.environ["AZURE_ACCOUNT"] = "acct"
    os.environ["AZURE_TABLE_SAS"] = "sig=dummy"

    def _raise(*a, **k):
        raise ValueError("Expecting value: line 1 column 1 (char 0)")

    restore = _stub("graphql", _raise)
    try:
        assert performance.ingest() == 0
    finally:
        restore()
        del os.environ["AZURE_ACCOUNT"], os.environ["AZURE_TABLE_SAS"]


def test_ingest_skips_a_stalled_upsert_and_keeps_going():
    """A read-phase timeout writing one row (raw TimeoutError out of
    upsert_row's _request, not wrapped in URLError — the same shape of bug
    fixed in fetch_rows() during Task 4) must not abort the rest of the
    week."""
    os.environ["AZURE_ACCOUNT"] = "acct"
    os.environ["AZURE_TABLE_SAS"] = "sig=dummy"
    calls = []

    def fake_upsert(entity):
        calls.append(entity)
        if len(calls) == 1:
            raise TimeoutError("timed out")

    restore_graphql = _stub("graphql", lambda q, v: {"post": {
        "status": "sent",
        "metricsUpdatedAt": "2026-08-20T00:00:00Z",
        "metrics": [{"type": "reach", "value": 100, "unit": "count"},
                    {"type": "reactions", "value": 10, "unit": "count"}],
    }})
    restore_upsert = _stub("upsert_row", fake_upsert)
    try:
        written = performance.ingest()
        assert len(calls) > 1, \
            "later rows must still be attempted after the stalled first one"
        assert written == len(calls) - 1, \
            f"the stalled row must be skipped, not counted: written={written} calls={len(calls)}"
    finally:
        restore_graphql()
        restore_upsert()
        del os.environ["AZURE_ACCOUNT"], os.environ["AZURE_TABLE_SAS"]


def test_ingest_skips_one_bad_row_and_keeps_going():
    """A single poison row (e.g. an HTTP 413 on one post) must not block the
    rest of the week — only a credentials failure should stop the run."""
    os.environ["AZURE_ACCOUNT"] = "acct"
    os.environ["AZURE_TABLE_SAS"] = "sig=dummy"
    calls = []

    def fake_upsert(entity):
        calls.append(entity)
        if len(calls) == 1:
            raise urllib.error.HTTPError("url", 413, "too large", {}, None)

    restore_graphql = _stub("graphql", lambda q, v: {"post": {
        "status": "sent",
        "metricsUpdatedAt": "2026-08-20T00:00:00Z",
        "metrics": [{"type": "reach", "value": 100, "unit": "count"},
                    {"type": "reactions", "value": 10, "unit": "count"}],
    }})
    restore_upsert = _stub("upsert_row", fake_upsert)
    try:
        written = performance.ingest()
        assert len(calls) > 1, \
            "later rows must still be attempted after the poisoned first one"
        assert written == len(calls) - 1, \
            f"the poisoned row must be skipped, not counted: written={written} calls={len(calls)}"
    finally:
        restore_graphql()
        restore_upsert()
        del os.environ["AZURE_ACCOUNT"], os.environ["AZURE_TABLE_SAS"]


def test_ingest_stops_immediately_on_missing_azure_credentials():
    """Unlike a single bad row, a KeyError out of upsert_row means every
    later write will fail identically (missing AZURE_ACCOUNT/SAS) — stop on
    the first one rather than log the same failure dozens of times."""
    os.environ["AZURE_ACCOUNT"] = "acct"
    os.environ["AZURE_TABLE_SAS"] = "sig=dummy"
    calls = []

    def fake_upsert(entity):
        calls.append(entity)
        raise KeyError("AZURE_ACCOUNT")

    restore_graphql = _stub("graphql", lambda q, v: {"post": {
        "status": "sent",
        "metricsUpdatedAt": "2026-08-20T00:00:00Z",
        "metrics": [{"type": "reach", "value": 100, "unit": "count"}],
    }})
    restore_upsert = _stub("upsert_row", fake_upsert)
    try:
        written = performance.ingest()
        assert written == 0
        assert len(calls) == 1, \
            f"a KeyError must stop the run after the first attempt, got {len(calls)}"
    finally:
        restore_graphql()
        restore_upsert()
        del os.environ["AZURE_ACCOUNT"], os.environ["AZURE_TABLE_SAS"]


def test_plan_stdout_is_pure_payload_when_blind():
    """The workflow captures --plan's stdout verbatim as the day->well plan
    (see .github/workflows/generate-week.yml), then feeds it straight into a
    prompt with each line treated as an assignment. Any diagnostic printed to
    stdout — such as the blind-mode notice that fires on every credential-less
    run — would be swallowed as a bogus eighth assignment. Diagnostics must go
    to stderr; stdout must carry only the seven day=well lines."""
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = {k: v for k, v in os.environ.items()
           if k not in ("AZURE_ACCOUNT", "AZURE_TABLE_SAS", "BUFFER_ACCESS_TOKEN")}
    result = subprocess.run(
        [sys.executable, "scripts/performance.py", "--plan"],
        capture_output=True, text=True, cwd=repo_root, env=env,
    )
    assert result.returncode == 0, f"blind run must exit 0, got {result.returncode}"
    lines = [line for line in result.stdout.splitlines() if line]
    assert len(lines) == 7, f"expected exactly 7 stdout lines, got {len(lines)}: {lines}"
    for line in lines:
        assert re.fullmatch(r"\d{2}_[a-z]{3}=[a-z-]+", line), \
            f"line does not match day=well shape: {line!r}"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok  {name}")
    print("\nall tests pass")
