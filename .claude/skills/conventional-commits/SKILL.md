---
name: conventional-commits
description: Use every time you are about to create a git commit in this repo. Conventional Commits format plus the scopes and staging rules specific to beyond-horizon-media.
---

# Conventional commits (beyond-horizon-media)

```
<type>(<scope>): <subject>

<body>

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
```

- Subject: imperative, lowercase, no trailing period, ≤72 chars — completes
  "this commit will …".
- Body: optional, only when *why* isn't obvious from the subject.
- `BREAKING CHANGE: <what broke, what to do>` footer when a caller must change.

## Types

`feat` `fix` `refactor` `perf` `test` `docs` `build` `ci` `chore` `style`

Behaviour was promised and broke → `fix`. Never existed → `feat`.

## Scopes

| Scope | Covers |
|---|---|
| `publish` | `scripts/publish.py`, Buffer scheduling, media upload |
| `validate` | `scripts/validate.py`, spec schema rules |
| `renderer` | `renderer/`, Remotion carousel rendering |
| `content` | `content/`, week specs and captions |
| `media` | rendered images committed under `media/` |
| `config` | `config.json` — channels, timezone, media host |
| `ci` | `.github/workflows/` |

Omit the scope for genuinely repo-wide changes. Add a new one only when nothing
above fits.

## Rules for this repo

- Stage explicit paths. Never `git add -A` — `config.json` holds live channel IDs
  and the tree often has rendered images and `__pycache__` lying around.
- Never commit tokens: `BUFFER_ACCESS_TOKEN`, `AZURE_SAS` and friends live in
  GitHub secrets only. Check the diff before staging.
- Rendered images (`media/<week>/`) and receipts (`content/<week>/SCHEDULED.json`)
  are normally committed by the workflow, not by hand. Leave them to CI unless
  the user asks.
- One theme per commit; each commit must stand on its own.
- Commit and push only when asked. Work lands on `main` — the publish workflow
  pushes there too, so keep the history linear (`git pull --rebase`).
