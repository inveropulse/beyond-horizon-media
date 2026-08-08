---
name: beyond-horizon-rendering
description: The rendering contract for Beyond Horizon social assets — how a carousel spec becomes 1080x1350 JPEG slides, the motion and layout rules, brand colours and type, and the acceptance checklist every output must pass. Use whenever changing anything under renderer/, adjusting the design system, debugging a render, adding a new slide kind, changing image dimensions or format, or working out why output looks wrong. Also use before touching scripts/publish.py, since the platform limits documented here (image counts, aspect ratios, file formats) are what that script enforces.
---

# Beyond Horizon rendering

`renderer/` is a Remotion project that turns a carousel spec into slides. One
spec produces one post; `render-carousels.mjs` does a whole week.

```bash
cd renderer && npm install
node render-carousels.mjs ../content/week2 ../media/week2
```

`references/production-spec.md` is the full contract — layout grid, safe areas,
type scale, motion rules, acceptance checklist. Read it before changing
anything visual.

## The rules that keep output predictable

Each of these exists because breaking it produced a real defect. Don't relax
them without a reason.

**Copy is measured, never clipped.** Text is measured with
`@remotion/layout-utils` and the type scale steps down until it fits the safe
box. Long copy gets smaller; it never overflows.

**Amounts never wrap.** SA amounts use a space as the thousands separator, which
naive wrapping splits — `R26 500` breaking after `R26` reads as a bug. A
non-breaking space is substituted before measuring. Same for hook lines and the
persona block, where the breaks are authored deliberately.

**One anchor for the body.** Every line-item slide starts its copy at the same
y, so the eye never has to re-find the text mid-swipe. Only the three title
cards (hook, persona, close) centre instead.

**Nothing renders below the progress bar.** That band is platform UI.

**Never hardcode a browser path.** It must fall back to the one Remotion
downloads, or CI breaks. This has happened once already.

**The `index` prop must be passed via `composition.props`.** `selectComposition`
bakes resolved props onto the composition object, so passing `inputProps` alone
silently renders slide 1 ten times. Dimension and file-count checks do not catch
this — only looking at the images does.

## Brand

Navy `#051D3B`, green `#5BD748`, white — sampled from the logo. Poppins 600/700
for display, Inter 400/500 for body. `renderer/public/logo.png` is the on-dark
lockup; the supplied logo is navy on transparent and vanishes on the background.

## Platform limits these outputs must satisfy

| | Limit | Why it matters |
|---|---|---|
| Images per carousel | 10 | Buffer's cap on TikTok and Instagram. TikTok itself allows 35. |
| Aspect ratio | 4:5 to 1.91:1 | 1080×1350 is exactly 4:5, the tallest Instagram allows. Do not go taller. |
| Format | JPG or WebP | TikTok does not accept PNG. The renderer outputs JPEG. |
| File size | ≤8 MB | Instagram's limit; ours run under 100 KB. |

## Video

The renderer can also produce 1080×1920 reels — the composition exists and
`make_bed.py` generates an audio bed through FluidSynth. It is not currently
used: the playbook's evidence is that carousels beat video in this niche on
TikTok, so all three channels get carousels. `references/production-spec.md`
covers the reel path if that changes.
