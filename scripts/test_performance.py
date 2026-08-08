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
