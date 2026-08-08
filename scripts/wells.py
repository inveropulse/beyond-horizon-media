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
