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


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok  {name}")
    print("\nall tests pass")
