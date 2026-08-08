#!/usr/bin/env python3
"""Shared validation for Beyond Horizon carousel specs.

Every gate here exists because breaking it produced a real defect: budgets that
didn't add up, amounts that wrapped mid-number, posts over the platform image
cap, captions that didn't ask anything.
"""

import glob
import json
import os
import re
import sys

BUFFER_IMAGE_CAP = 10       # TikTok and Instagram, via Buffer
MAX_CAPTION = 2200
HASHTAGS = 5


def rand(amount):
    """'R6 200 p/m' -> 6200. Handles the SA space thousands separator."""
    if not amount:
        return 0
    m = re.match(r"R\s?([\d  ]+)", amount)
    return int(m.group(1).replace(" ", "").replace(" ", "")) if m else 0


def check(spec, name="spec"):
    """Return a list of problems. Empty list means the spec is publishable."""
    p = []
    slides = spec.get("slides") or []
    income = spec.get("income")

    if not slides:
        return [f"{name}: no slides"]
    if len(slides) > BUFFER_IMAGE_CAP:
        p.append(f"{name}: {len(slides)} slides, Buffer caps carousels at {BUFFER_IMAGE_CAP}")
    if len(slides) < 8:
        p.append(f"{name}: only {len(slides)} slides")

    kinds = [s.get("kind") for s in slides]
    for required in ("hook", "persona", "reckoning", "cta"):
        if required not in kinds:
            p.append(f"{name}: missing a '{required}' slide")
    if kinds and kinds[0] != "hook":
        p.append(f"{name}: first slide is '{kinds[0]}', must be the hook")
    if kinds and kinds[-1] != "cta":
        p.append(f"{name}: last slide is '{kinds[-1]}', must be the close")

    # the arithmetic — the single most important gate
    lines = [s for s in slides if s.get("kind") == "line"]
    rec = next((s for s in slides if s.get("kind") == "reckoning"), None)
    if income and rec:
        total = sum(rand(s.get("amount")) for s in lines)
        left = rand(rec.get("amount"))
        if income - total != left:
            p.append(f"{name}: ARITHMETIC — {income} - {total} = {income - total}, "
                     f"but the reckoning says {left}")
    elif not income:
        p.append(f"{name}: no income, the share-of-salary rail will not render")

    hook = next((s for s in slides if s.get("kind") == "hook"), None)
    if hook and not re.search(r"R\s?\d", hook.get("title", "")):
        p.append(f"{name}: no rand figure in the hook")

    for s in slides:
        a = s.get("amount") or ""
        if "," in a:
            p.append(f"{name}: '{a}' uses a comma; SA format is a space")

    caption = (spec.get("caption") or "").strip()
    tags = spec.get("hashtags") or []
    if not caption:
        p.append(f"{name}: no caption")
    elif not caption.endswith("?"):
        p.append(f"{name}: caption does not end in a question")
    if len(tags) != HASHTAGS:
        p.append(f"{name}: {len(tags)} hashtags, must be {HASHTAGS}")
    if len(f"{caption}\n\n{' '.join(tags)}") > MAX_CAPTION:
        p.append(f"{name}: caption over {MAX_CAPTION} characters")

    return p


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else "content/week1"
    # day specs are 01_mon.json .. 07_sun.json; the same glob publish.py uses, so
    # SCHEDULED.json and any other sidecar in the folder is left alone
    files = sorted(glob.glob(os.path.join(target, "[0-9]*.json")))
    if not files:
        sys.exit(f"no specs found in {target}")

    problems = []
    for f in files:
        name = os.path.basename(f)
        try:
            spec = json.load(open(f))
        except Exception as e:
            problems.append(f"{name}: unreadable — {e}")
            continue
        found = check(spec, name)
        problems += found
        print(f"{'OK  ' if not found else 'FAIL'} {name}: {len(spec.get('slides', []))} slides")

    if problems:
        print("\n" + "\n".join(f"  - {x}" for x in problems))
        sys.exit(1)
    print(f"\nall {len(files)} specs pass")


if __name__ == "__main__":
    main()
