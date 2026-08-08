#!/usr/bin/env python3
"""Resolve media URLs and schedule a content week in Buffer.

Runs on a GitHub Actions runner. The Cowork sandbox blocks every object store,
CDN and the Buffer API, so this step cannot run there.

Two media hosts, selected by config.json -> mediaHost:

  "github"  the rendered images are committed to this repo and served from
            raw.githubusercontent.com. No secrets, nothing else to configure.
  "azure"   images are uploaded to Azure Blob Storage with a SAS. Needs the
            AZURE_* environment variables and a container whose anonymous
            access level is set to Blob.

  python3 scripts/publish.py --week week1 --start 2026-08-10 [--dry-run]
"""

import argparse
import glob
import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from validate import check  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = json.load(open(os.path.join(ROOT, "config.json")))
# Buffer's GraphQL endpoint for API-key auth is api.buffer.com. graph.buffer.com
# also exists and answers GraphQL, but rejects API keys with UNAUTHENTICATED --
# it expects a session/OAuth token. See developers.buffer.com/guides/authentication
GRAPHQL = os.environ.get("BUFFER_GRAPHQL_URL", "https://api.buffer.com")

CREATE_POST = """
mutation CreatePost($input: CreatePostInput!) {
  createPost(input: $input) {
    __typename
    ... on PostActionSuccess { post { id status dueAt channelId } }
    ... on InvalidInputError { message }
    ... on NotFoundError { message }
    ... on UnauthorizedError { message }
    ... on LimitReachedError { message }
    ... on RestProxyError { message code }
    ... on UnexpectedError { message }
  }
}
"""


def media_url(week, post, filename):
    host = CONFIG["mediaHost"]
    if host == "github":
        g = CONFIG["github"]
        return (f"https://raw.githubusercontent.com/{g['owner']}/{g['repo']}/"
                f"{g['branch']}/media/{week}/{post}/{filename}")
    account = os.environ["AZURE_ACCOUNT"]
    container = os.environ["AZURE_CONTAINER"]
    return f"https://{account}.blob.core.windows.net/{container}/{week}/{post}/{filename}"


def azure_put(local_path, week, post, filename):
    sas = os.environ["AZURE_SAS"].lstrip("?")
    url = media_url(week, post, filename)
    ctype = mimetypes.guess_type(local_path)[0] or "application/octet-stream"
    req = urllib.request.Request(f"{url}?{sas}", data=open(local_path, "rb").read(), method="PUT")
    req.add_header("x-ms-blob-type", "BlockBlob")
    req.add_header("Content-Type", ctype)
    req.add_header("x-ms-blob-content-type", ctype)
    with urllib.request.urlopen(req, timeout=180) as r:
        if r.status not in (201, 202):
            raise RuntimeError(f"{url}: HTTP {r.status}")
    return url


def assert_public(url, tries=8):
    """Buffer fetches media server-side, so it must be anonymously readable.
    raw.githubusercontent.com can lag a few seconds behind a push, so retry."""
    last = None
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url), timeout=45) as r:
                if r.status == 200 and r.read(64):
                    return
                last = f"HTTP {r.status}"
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"
        except Exception as e:  # transient DNS/TLS
            last = str(e)[:80]
        time.sleep(min(2 ** i, 15))
    host = CONFIG["mediaHost"]
    hint = ("the repo must be public — Buffer cannot authenticate to raw.githubusercontent.com"
            if host == "github" else
            "set the container's anonymous access level to 'Blob'; Buffer cannot use your SAS")
    raise SystemExit(f"\n{url}\n  is not publicly readable ({last}).\n  {hint}\n")


def graphql(query, variables):
    token = os.environ["BUFFER_ACCESS_TOKEN"]
    body = json.dumps({"query": query, "variables": variables}).encode()
    for attempt in range(3):
        req = urllib.request.Request(GRAPHQL, data=body, method="POST")
        req.add_header("Authorization", f"Bearer {token}")
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                out = json.loads(r.read())
            if out.get("errors"):
                raise RuntimeError(json.dumps(out["errors"])[:400])
            return out["data"]
        except urllib.error.HTTPError as e:
            detail = e.read().decode()[:400]
            if e.code in (429, 500, 502, 503) and attempt < 2:
                time.sleep(3 * (attempt + 1))
                continue
            if e.code == 401:
                raise SystemExit(
                    f"\nBuffer rejected the API key (401) at {GRAPHQL}.\n"
                    "  Check the BUFFER_ACCESS_TOKEN secret against a fresh key from\n"
                    "  https://publish.buffer.com/settings/api\n")
            raise RuntimeError(f"HTTP {e.code}: {detail}")
    raise RuntimeError("unreachable")


def metadata_for(channel_key, image_count):
    if channel_key == "instagram":
        # "post" is verified against the live account for a 10-image carousel.
        # The schema also lists "carousel" but it is rejected in practice.
        return {"instagram": {"type": "post", "shouldShareToFeed": True}}
    if channel_key == "facebook":
        return {"facebook": {"type": "post"}}
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", default="week1")
    ap.add_argument("--start", required=True, help="Monday of the posting week, YYYY-MM-DD")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()

    host = CONFIG["mediaHost"]
    content_dir = os.path.join(ROOT, "content", a.week)
    media_dir = os.path.join(ROOT, "media", a.week)
    receipt = os.path.join(content_dir, "SCHEDULED.json")

    if os.path.exists(receipt) and not a.force and not a.dry_run:
        sys.exit(f"content/{a.week}/SCHEDULED.json exists — already scheduled. Use --force.")

    specs = sorted(glob.glob(os.path.join(content_dir, "[0-9]*.json")))
    if not specs:
        sys.exit(f"no specs in content/{a.week}")

    start = datetime.strptime(a.start, "%Y-%m-%d").date()
    if start.weekday() != 0:
        print(f"warning: {a.start} is not a Monday")

    # 1. validate everything before touching the network
    problems = []
    for f in specs:
        problems += check(json.load(open(f)), os.path.basename(f))
    if problems:
        print("validation failed:")
        for x in problems:
            print("  -", x)
        sys.exit(1)
    print(f"validated {len(specs)} specs, media host = {host}")

    # 2. resolve media
    urls = {}
    for f in specs:
        post = os.path.splitext(os.path.basename(f))[0]
        images = sorted(glob.glob(os.path.join(media_dir, post, "*.jpg")))
        spec = json.load(open(f))
        if len(images) != len(spec["slides"]):
            sys.exit(f"{post}: {len(images)} images but {len(spec['slides'])} slides "
                     f"— run the render step first")
        if host == "azure" and not a.dry_run:
            urls[post] = [azure_put(p, a.week, post, os.path.basename(p)) for p in images]
        else:
            urls[post] = [media_url(a.week, post, os.path.basename(p)) for p in images]
        print(f"{len(urls[post]):>3} images for {post}")

    if a.dry_run:
        for f in specs:
            post = os.path.splitext(os.path.basename(f))[0]
            for i, c in enumerate(CONFIG["channels"]):
                day = start + timedelta(days=specs.index(f))
                print(f"DRY  {post} -> {c['key']:<9} {day}T{c['time']} ({len(urls[post])} images)")
        print(f"\nfirst URL would be:\n  {urls[list(urls)[0]][0]}")
        print("\ndry run — nothing uploaded or scheduled")
        return

    # 3. prove the first image is publicly fetchable before creating 21 posts
    first = urls[os.path.splitext(os.path.basename(specs[0]))[0]][0]
    assert_public(first)
    print(f"public read confirmed: {first}")

    # 4. schedule
    results = []
    for i, f in enumerate(specs):
        post = os.path.splitext(os.path.basename(f))[0]
        spec = json.load(open(f))
        day = start + timedelta(days=i)
        text = f"{spec['caption'].strip()}\n\n{' '.join(spec['hashtags'][:5])}"
        hook = next((s for s in spec["slides"] if s.get("kind") == "hook"), {})
        alt = hook.get("title", "Beyond Horizon").replace("\n", " ")
        assets = [{"image": {"url": u, "metadata": {
                       "altText": f"{alt} — slide {n} of {len(urls[post])}"}}}
                  for n, u in enumerate(urls[post], 1)]

        for c in CONFIG["channels"]:
            payload = {
                "channelId": c["id"],
                "mode": "customScheduled",
                "schedulingType": "automatic",
                "dueAt": f"{day.isoformat()}T{c['time']}:00{CONFIG['timezone']}",
                "text": text,
                "assets": assets,
            }
            md = metadata_for(c["key"], len(assets))
            if md:
                payload["metadata"] = md

            # Buffer's media fetcher intermittently fails to read an image even
            # when it is definitely served correctly. Retry before giving up.
            data = None
            for attempt in range(4):
                try:
                    data = graphql(CREATE_POST, {"input": payload})["createPost"]
                except RuntimeError as e:
                    if "could not be read" in str(e) and attempt < 3:
                        time.sleep(20 * (attempt + 1))
                        continue
                    raise
                if data["__typename"] == "PostActionSuccess":
                    break
                msg = data.get("message") or ""
                if "could not be read" in msg and attempt < 3:
                    time.sleep(20 * (attempt + 1))
                    continue
                raise SystemExit(f"{post}/{c['key']}: {data['__typename']} — {msg}")
            time.sleep(8)  # pace so the host is not hammered
            p = data["post"]
            results.append({"day": post, "channel": c["key"], "postId": p["id"],
                            "dueAt": p["dueAt"], "status": p["status"]})
            print(f"scheduled {post} -> {c['key']:<9} {payload['dueAt']}  id={p['id']}")

    json.dump({"week": a.week, "start": a.start, "mediaHost": host,
               "scheduledAt": datetime.utcnow().isoformat() + "Z",
               "posts": results}, open(receipt, "w"), indent=2)
    print(f"\n{len(results)} posts scheduled — receipt at content/{a.week}/SCHEDULED.json")


if __name__ == "__main__":
    main()
