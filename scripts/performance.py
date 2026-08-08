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
