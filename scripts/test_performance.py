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


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok  {name}")
    print("\nall tests pass")
